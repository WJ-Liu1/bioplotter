from __future__ import annotations

import math
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES
from app.core.random_seed import seed_control


HELP_TEXT = """
Mantel Test + Corrplot（原生 Plotly 版本）
输入数据：
  1. Data 1（spec data）
     - 无表头格式：第 1 行分组名称，第 2 行变量名称，第 3 行开始为数值矩阵
  2. CorrplotData（env data）
     - 每列为一个环境变量，第 1 行为列名
功能：
  - 计算 env 变量相关矩阵，用 corrplot 图形符号（circle/square/star/pie/ellipse）显示
  - 符号大小与颜色均随相关系数变化，正相关偏红、负相关偏灰
  - 计算每个 spec 分组与 env 的 Mantel 检验，用彩色曲线把分组连接到对应变量
  - 曲线颜色表示 Mantel 检验的 p 值，曲线粗细表示 Mantel 相关系数
  - 支持 upper / lower 布局、显示相关系数数字、自定义标题与图例
说明：
  - 图形符号、连线与图例采用经典相关图布局
  - Plotly 版本支持缩放、悬停查看具体配对
"""


# ---------------------------------------------------------------- 颜色工具

_NAMED = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
    "grey": "#808080",
    "gray": "#808080",
    "yellow": "#FFFF00",
    "orange": "#FFA500",
    "purple": "#800080",
    "pink": "#FFC0CB",
}


def _safe_hex_color(value, fallback="#000000") -> str:
    if value is None:
        return fallback
    v = str(value).strip()
    if not v:
        return fallback
    if v.startswith("#"):
        return v
    return _NAMED.get(v.lower(), fallback)


def _theme_hex(theme: dict, key: str, fallback: str) -> str:
    return _safe_hex_color(theme.get(key), fallback)


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    v = _safe_hex_color(value).lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        v = "000000"
    return tuple(int(v[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02X}" for c in rgb)


def _mix(c1: str, c2: str, t: float) -> str:
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _gradient(low: str, mid: str, high: str, value: float) -> str:
    """按 low / mid / high 三色在 [-1, 1] 区间取插值色。"""
    v = float(np.clip(value, -1.0, 1.0))
    if v <= 0:
        return _mix(mid, low, min(1.0, -v))
    return _mix(mid, high, min(1.0, v))


# ---------------------------------------------------------------- 数据读取


def _sample_spec_bytes() -> bytes:
    return sample_bytes("mantel_spec")


def _sample_env_bytes() -> bytes:
    return sample_bytes("mantel_env")


def _read_spec_table(uploaded, mode: str = "auto"):
    if uploaded is None:
        return None, "请上传 Data 1。"
    try:
        name = getattr(uploaded, "name", "").lower()
        if mode == "xlsx" or name.endswith(".xlsx"):
            return pd.read_excel(uploaded, header=None), None
        data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else None
        if data is not None:
            return pd.read_csv(BytesIO(data), header=None, sep=None, engine="python"), None
        return pd.read_csv(uploaded, header=None, sep=None, engine="python"), None
    except Exception as exc:
        return None, f"Data 1 读取失败：{exc}"


def _read_env_table(uploaded):
    if uploaded is None:
        return None, "请上传 CorrplotData。"
    try:
        return read_table(uploaded, getattr(uploaded, "name", None)), None
    except Exception as exc:
        return None, f"CorrplotData 读取失败：{exc}"


def _load_sample_tables():
    spec = pd.read_csv(get_sample_path("mantel_spec"), header=None)
    env_path = get_sample_path("mantel_env")
    env = read_table(env_path, env_path.name)
    return spec, env


def _parse_spec_data(raw: pd.DataFrame):
    if raw is None or raw.shape[0] < 3 or raw.shape[1] < 2:
        raise ValueError("Data 1 格式不正确，至少需要 3 行和 2 列。")

    group_labels = raw.iloc[0].astype(str).tolist()
    var_names = raw.iloc[1].astype(str).tolist()

    spec = raw.iloc[2:].copy()
    spec.columns = var_names
    spec = spec.apply(pd.to_numeric, errors="coerce")

    if spec.isna().all(axis=None):
        raise ValueError("Data 1 数值矩阵为空。")

    group_map: dict[str, list[str]] = {}
    for i, grp in enumerate(group_labels):
        group_map.setdefault(str(grp), []).append(var_names[i])

    spec = spec.dropna(axis=0, how="all").dropna(axis=1, how="all")
    group_map = {k: [c for c in v if c in spec.columns] for k, v in group_map.items()}
    group_map = {k: v for k, v in group_map.items() if len(v) > 0}

    if not group_map:
        raise ValueError("Data 1 中没有可用分组。")

    return spec, group_map


# ---------------------------------------------------------------- 统计计算


def _pairwise_euclidean(df: pd.DataFrame) -> np.ndarray:
    x = np.asarray(df, dtype=float)
    diff = x[:, None, :] - x[None, :, :]
    return np.sqrt(np.nansum(diff ** 2, axis=2))


def _upper_tri_values(m: np.ndarray) -> np.ndarray:
    idx = np.triu_indices_from(m, k=1)
    return m[idx]


def _mantel_test(x: np.ndarray, y: np.ndarray, perms: int = 999, seed: int = 42):
    if x.shape != y.shape:
        raise ValueError("Mantel test 的两个距离矩阵维度必须相同。")

    xv = _upper_tri_values(x)
    yv = _upper_tri_values(y)

    mask = np.isfinite(xv) & np.isfinite(yv)
    xv, yv = xv[mask], yv[mask]

    if len(xv) < 3:
        return np.nan, np.nan

    r_obs = float(np.corrcoef(xv, yv)[0, 1])

    rng = np.random.default_rng(seed)
    n = x.shape[0]
    perm_rs = []

    for _ in range(perms):
        idx = rng.permutation(n)
        xp = x[idx][:, idx]
        xpv = _upper_tri_values(xp)[mask]
        if len(xpv) != len(yv):
            continue
        perm_rs.append(float(np.corrcoef(xpv, yv)[0, 1]))

    perm_rs = np.asarray(perm_rs, dtype=float)
    if len(perm_rs) == 0:
        return r_obs, np.nan

    p = (np.sum(perm_rs >= r_obs) + 1) / (len(perm_rs) + 1)
    return r_obs, float(p)


def _cut_r_category(r: float) -> str:
    if r < 0.2:
        return "< 0.2"
    if r < 0.4:
        return "0.2 - 0.4"
    return ">= 0.4"


def _cut_p_category(p: float) -> str:
    if p < 0.01:
        return "< 0.01"
    if p < 0.05:
        return "0.01 - 0.05"
    return ">= 0.05"


def _line_size_values(level: int):
    mapping = {
        1: [0.25, 0.5, 1.0],
        2: [0.5, 1.0, 2.0],
        3: [1.0, 2.0, 4.0],
        4: [1.5, 3.0, 6.0],
        5: [2.0, 4.0, 8.0],
    }
    return mapping.get(level, [0.5, 1.0, 2.0])


# ---------------------------------------------------------------- 图形符号
# corrplot 的五种符号都在单元格内绘制 polygon；|r| 由中心向外线性缩放。


def _poly_circle(cx: float, cy: float, rx: float, ry: float, n: int = 64):
    ang = np.linspace(0, 2 * math.pi, n)
    return [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in ang]


def _poly_square(cx: float, cy: float, rx: float, ry: float):
    return [
        (cx - rx, cy - ry),
        (cx + rx, cy - ry),
        (cx + rx, cy + ry),
        (cx - rx, cy + ry),
    ]


def _poly_star(cx: float, cy: float, rx: float, ry: float, points: int = 5):
    verts = []
    for k in range(points * 2):
        ang = math.pi / 2 + k * math.pi / points
        rad = 1.0 if k % 2 == 0 else 0.42
        verts.append((cx + rx * rad * math.cos(ang), cy + ry * rad * math.sin(ang)))
    return verts


def _poly_pie(cx: float, cy: float, rx: float, ry: float, r_value: float):
    """corrplot 的 pie：扇形角度 = 360°·|r|，正相关从 12 点顺时针，负相关逆时针。"""
    sweep = 2 * math.pi * min(1.0, abs(r_value))
    if sweep <= 0.02:
        sweep = 0.02
    direction = -1.0 if r_value >= 0 else 1.0
    steps = max(6, int(48 * abs(r_value)) + 2)
    verts = [(cx, cy)]
    for k in range(steps + 1):
        ang = -math.pi / 2 + direction * sweep * k / steps
        verts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
    verts.append((cx, cy))
    return verts


def _poly_ellipse(cx: float, cy: float, rx: float, ry: float, angle: float = math.pi / 4):
    a, b = rx, ry * 0.5
    ca, sa = math.cos(angle), math.sin(angle)
    verts = []
    for t in np.linspace(0, 2 * math.pi, 64):
        x = a * math.cos(t)
        y = b * math.sin(t)
        verts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return verts


def _glyph(shape: str, cx: float, cy: float, size: float, r_value: float):
    if size <= 0.004:
        return None
    if shape == "square":
        return _poly_square(cx, cy, size, size)
    if shape == "star":
        return _poly_star(cx, cy, size, size)
    if shape == "pie":
        return _poly_pie(cx, cy, size, size, r_value)
    if shape == "ellipse":
        return _poly_ellipse(cx, cy, size, size)
    return _poly_circle(cx, cy, size, size)


# ---------------------------------------------------------------- 控件


def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    st.markdown("### Data")
    sample_loader_control("mt_use_sample", ["mantel_spec", "mantel_env"], "mt_load_sample_btn")

    if not st.session_state.get("mt_use_sample", True):
        st.radio(
            "Data 1 格式",
            ["自动识别", "文本表（CSV/TSV/TXT）", "XLSX"],
            index=0,
            key="mt_spec_format",
            horizontal=True,
        )
        st.file_uploader("upload Data 1", type=["csv", "tsv", "txt", "xlsx"], key="mt_spec_file")
    st.download_button(
        "Download example data1",
        data=_sample_spec_bytes(),
        file_name="test-data1.csv",
        mime="text/csv",
        width="stretch",
    )

    if not st.session_state.get("mt_use_sample", True):
        st.file_uploader("upload CorrplotData", type=["csv", "tsv", "txt", "xlsx"], key="mt_env_file")
    st.download_button(
        "Download example corrplotdata",
        data=_sample_env_bytes(),
        file_name="test-data2.csv",
        mime="text/csv",
        width="stretch",
    )

    st.selectbox("Method of display", ["circle", "square", "star", "pie", "ellipse"], index=0, key="mt_shape")
    st.selectbox("LayOut of display", ["upper", "lower"], index=0, key="mt_layout")
    with st.expander("可复现性", expanded=False):
        seed_control("mt_seed")

    with st.expander("spec design", expanded=False):
        st.radio("spec design mode", ["Default", "Customize"], horizontal=True, key="mt_spec_mode")
        if st.session_state.get("mt_spec_mode") == "Customize":
            st.color_picker("Label color", value=_theme_hex(theme, "mt_label_color", "#000000"), key="mt_label_color")
            st.slider("Label size", min_value=3, max_value=25, value=5, key="mt_label_size")

    with st.expander("Title / Label details", expanded=False):
        st.text_input("line color Title", value="Mantel's p", key="mt_title1")
        st.text_input("line size Title", value="Mantel's r", key="mt_title2")
        st.text_input("Degree of relevance Title", value="Pearson's r", key="mt_title3")
        st.color_picker("Legend title colour", value=_theme_hex(theme, "mt_legend_title_color", "#000000"), key="mt_legend_title_color")
        st.slider("Legend title size", min_value=10, max_value=40, value=14, key="mt_legend_title_size")
        st.color_picker("Legend text colour", value=_theme_hex(theme, "mt_legend_text_color", "#000000"), key="mt_legend_text_color")
        st.slider("Legend text size", min_value=10, max_value=40, value=14, key="mt_legend_text_size")
        st.text_input("Add Plot Title", value="", key="mt_plot_title")
        st.color_picker("Plot title colour", value=_theme_hex(theme, "mt_plot_title_color", "#000000"), key="mt_plot_title_color")
        st.slider("Plot title size", min_value=10, max_value=60, value=20, key="mt_plot_title_size")
        st.color_picker("X-Axis text colour", value=_theme_hex(theme, "mt_x_text_color", "#000000"), key="mt_x_text_color")
        st.slider("X-Axis text size", min_value=10, max_value=40, value=12, key="mt_x_text_size")
        st.color_picker("Y-Axis text colour", value=_theme_hex(theme, "mt_y_text_color", "#000000"), key="mt_y_text_color")
        st.slider("Y-Axis text size", min_value=10, max_value=40, value=12, key="mt_y_text_size")

    with st.expander("Color Settings", expanded=False):
        # 默认配色：positive = red, weak = white, negative = grey
        st.color_picker("positive correlation", value=_theme_hex(theme, "mt_col_high", "#FF0000"), key="mt_col_high")
        st.color_picker("weak correlation", value=_theme_hex(theme, "mt_col_mid", "#FFFFFF"), key="mt_col_mid")
        st.color_picker("negative correlation", value=_theme_hex(theme, "mt_col_low", "#808080"), key="mt_col_low")
        # 默认连线色：#D95F02 / #1B9E77 / #A2A2A288
        st.color_picker("line < 0.01", value=_theme_hex(theme, "mt_linecol1", "#D95F02"), key="mt_linecol1")
        st.color_picker("line 0.01 - 0.05", value=_theme_hex(theme, "mt_linecol2", "#1B9E77"), key="mt_linecol2")
        st.color_picker("line >= 0.05", value=_theme_hex(theme, "mt_linecol3", "#A2A2A2"), key="mt_linecol3")
        st.radio("Show value", ["Don't show", "Show"], horizontal=True, key="mt_show_value")
        if st.session_state.get("mt_show_value") == "Show":
            st.color_picker("number color", value=_theme_hex(theme, "mt_number_color", "#000000"), key="mt_number_color")
        st.slider("Control line size", min_value=1, max_value=5, value=2, key="mt_linesize")


# ---------------------------------------------------------------- 绘图


def _bezier(p0, p1, p2, steps: int = 26):
    xs, ys = [], []
    for k in range(steps + 1):
        t = k / steps
        u = 1 - t
        xs.append(u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0])
        ys.append(u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])
    return xs, ys


def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    if st.session_state.get("mt_use_sample", True):
        spec_raw, env_raw = _load_sample_tables()
    else:
        spec_mode_map = {"自动识别": "auto", "文本表（CSV/TSV/TXT）": "text", "XLSX": "xlsx"}
        spec_mode = spec_mode_map.get(st.session_state.get("mt_spec_format", "自动识别"), "auto")
        spec_raw, err1 = _read_spec_table(st.session_state.get("mt_spec_file"), mode=spec_mode)
        env_raw, err2 = _read_env_table(st.session_state.get("mt_env_file"))
        if err1:
            return None, None, err1, HELP_TEXT
        if err2:
            return None, None, err2, HELP_TEXT

    try:
        spec, group_map = _parse_spec_data(spec_raw)
    except Exception as exc:
        return None, None, str(exc), HELP_TEXT

    env = env_raw.copy()
    for col in env.columns:
        env[col] = pd.to_numeric(env[col], errors="coerce")
    env = env.dropna(axis=0, how="all").dropna(axis=1, how="all")

    if env.empty or env.shape[1] < 2:
        return None, None, "CorrplotData 至少需要两个数值列。", HELP_TEXT

    common_n = min(len(spec), len(env))
    spec = spec.iloc[:common_n].reset_index(drop=True)
    env = env.iloc[:common_n].reset_index(drop=True)

    env_dist = _pairwise_euclidean(env)

    mantel_rows = []
    for grp, cols in group_map.items():
        sub = spec[cols].copy()
        for col in sub.columns:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
        sub = sub.dropna(axis=1, how="all")
        if sub.empty:
            continue
        spec_dist = _pairwise_euclidean(sub)
        r, p = _mantel_test(
            spec_dist,
            env_dist,
            seed=int(st.session_state.get("mt_seed", 42)),
        )
        mantel_rows.append(
            {
                "group": grp,
                "r": r,
                "p_value": p,
                "rd": _cut_r_category(abs(r) if np.isfinite(r) else 0.0),
                "pd": _cut_p_category(p if np.isfinite(p) else 1.0),
            }
        )

    mantel_df = pd.DataFrame(mantel_rows)
    corr = env.corr(numeric_only=True)
    n = corr.shape[0]
    labels = [str(c) for c in corr.columns]

    shape = st.session_state.get("mt_shape", "circle")
    layout = st.session_state.get("mt_layout", "upper")
    show_number = st.session_state.get("mt_show_value") == "Show"
    number_color = _safe_hex_color(st.session_state.get("mt_number_color"), "#000000")

    col_high = _safe_hex_color(st.session_state.get("mt_col_high"), "#FF0000")
    col_mid = _safe_hex_color(st.session_state.get("mt_col_mid"), "#FFFFFF")
    col_low = _safe_hex_color(st.session_state.get("mt_col_low"), "#808080")

    x_text_color = _safe_hex_color(st.session_state.get("mt_x_text_color"), "#000000")
    x_text_size = st.session_state.get("mt_x_text_size", 12)
    y_text_color = _safe_hex_color(st.session_state.get("mt_y_text_color"), "#000000")
    y_text_size = st.session_state.get("mt_y_text_size", 12)

    legend_title_color = _safe_hex_color(st.session_state.get("mt_legend_title_color"), "#000000")
    legend_text_color = _safe_hex_color(st.session_state.get("mt_legend_text_color"), "#000000")
    legend_text_size = st.session_state.get("mt_legend_text_size", 14)
    legend_title_size = st.session_state.get("mt_legend_title_size", 14)

    label_color = _safe_hex_color(st.session_state.get("mt_label_color"), "#000000")
    label_size = st.session_state.get("mt_label_size", 5)

    line_sizes = _line_size_values(st.session_state.get("mt_linesize", 2))
    size_map = {"< 0.2": line_sizes[0], "0.2 - 0.4": line_sizes[1], ">= 0.4": line_sizes[2]}
    line_color_map = {
        "< 0.01": _safe_hex_color(st.session_state.get("mt_linecol1"), "#D95F02"),
        "0.01 - 0.05": _safe_hex_color(st.session_state.get("mt_linecol2"), "#1B9E77"),
        ">= 0.05": _safe_hex_color(st.session_state.get("mt_linecol3"), "#A2A2A2"),
    }

    fig = go.Figure()

    # ---- 1. Mantel 连线（先画，压在符号下面）
    # 分组连线：每个 spec 分组在矩阵左侧占一个锚点，向 env 的每个变量
    # 在「列（顶部）」和「行（左侧）」各引一条曲线，颜色=pd，粗细=rd。
    anchor_x = -0.60
    group_rows = list(mantel_df.itertuples(index=False))
    n_group = max(1, len(group_rows))
    # 线宽/size 单位按毫米换算成像素约 ×2.8
    px_scale = 2.8

    for k, row in enumerate(group_rows):
        anchor_y = n - (k + 0.5) * n / n_group
        width_px = size_map.get(row.rd, 1.0) * px_scale
        color = line_color_map.get(row.pd, "#A2A2A2")
        for j in range(n):
            # 连线终点取变量自身的对角单元格：该点同时对应行标签与列标签，
            # 因此一条曲线即可表示「分组 ↔ 变量」的对应关系（行列两条 link 的合并）。
            p2 = (j + 1.0, n - j)
            p0 = (anchor_x, anchor_y)
            dist = math.hypot(p2[0] - p0[0], p2[1] - p0[1]) or 1.0
            mx, my = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
            nx, ny = -(p2[1] - p0[1]) / dist, (p2[0] - p0[0]) / dist
            ctrl = (mx + nx * dist * 0.22, my + ny * dist * 0.22)
            xs, ys_line = _bezier(p0, ctrl, p2)
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys_line,
                    mode="lines",
                    line=dict(color=color, width=width_px),
                    opacity=0.8,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
        # 分组标签贴在锚点左侧
        fig.add_trace(
            go.Scatter(
                x=[anchor_x - 0.28],
                y=[anchor_y],
                mode="text",
                text=[str(row.group)],
                textposition="middle right",
                textfont=dict(size=max(11, label_size + 7), color=label_color),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # ---- 2. 相关矩阵符号
    cell_half = 0.44
    for i in range(n):
        for j in range(n):
            if layout == "upper" and j < i:
                continue
            if layout == "lower" and j > i:
                continue
            value = float(corr.iloc[i, j])
            if not np.isfinite(value):
                continue
            cx, cy = float(j + 1), float(n - i)
            size = cell_half * abs(value)
            verts = _glyph(shape, cx, cy, size, value)
            fill = _gradient(col_low, col_mid, col_high, value)
            if verts is None:
                continue
            xs = [p[0] for p in verts] + [verts[0][0]]
            ys = [p[1] for p in verts] + [verts[0][1]]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    fill="toself",
                    fillcolor=fill,
                    line=dict(color=fill, width=0.6),
                    hovertemplate=(
                        f"{labels[i]} × {labels[j]}<br>Pearson's r = {value:.3f}<extra></extra>"
                    ),
                    showlegend=False,
                )
            )

    # ---- 3. 相关系数数字
    if show_number:
        for i in range(n):
            for j in range(n):
                if layout == "upper" and j < i:
                    continue
                if layout == "lower" and j > i:
                    continue
                value = float(corr.iloc[i, j])
                if not np.isfinite(value):
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=[j + 1],
                        y=[n - i],
                        mode="text",
                        text=[f"{value:.2f}"],
                        textfont=dict(size=9, color=number_color),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

    # ---- 4. 图例：Mantel p（颜色）、Mantel 相关系数（线宽）、Pearson 相关系数（色条）
    title_p = st.session_state.get("mt_title1", "Mantel's p")
    title_r = st.session_state.get("mt_title2", "Mantel's r")
    title_fill = st.session_state.get("mt_title3", "Pearson's r")

    for cat, col in line_color_map.items():
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color=col, width=3),
                name=cat,
                legendgroup="p",
                showlegend=True,
            )
        )
    for cat, w in size_map.items():
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="#595959", width=max(1.0, w)),
                name=cat,
                legendgroup="r",
                showlegend=True,
            )
        )
    # 色条载体（不可见散点）
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(
                color=[0, 1],
                cmin=-1,
                cmax=1,
                colorscale=[
                    [0.0, col_low],
                    [0.5, col_mid],
                    [1.0, col_high],
                ],
                showscale=True,
                size=0.1,
                colorbar=dict(
                    title=dict(
                        text=f"<i>{title_fill}</i>",
                        font=dict(size=legend_title_size, color=legend_title_color),
                    ),
                    tickfont=dict(size=legend_text_size - 2, color=legend_text_color),
                    thickness=14,
                    len=0.45,
                    y=0.22,
                    x=1.10,
                    outlinewidth=0,
                ),
            ),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    title_text = st.session_state.get("mt_plot_title", "")
    title_color = _safe_hex_color(st.session_state.get("mt_plot_title_color"), "#000000")
    title_size = st.session_state.get("mt_plot_title_size", 20)

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"<b>{title_text}</b>" if title_text else "",
            font=dict(size=title_size, color=title_color),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(1, n + 1)),
            ticktext=labels,
            tickangle=45,
            tickfont=dict(size=x_text_size, color=x_text_color),
            range=[-1.7, n + 0.6],
            showgrid=False,
            zeroline=False,
            showline=False,
            side="bottom",
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(1, n + 1)),
            ticktext=list(reversed(labels)),
            tickfont=dict(size=y_text_size, color=y_text_color),
            range=[-0.4, n + 0.9],
            showgrid=False,
            zeroline=False,
            showline=False,
        ),
        legend=dict(
            title=dict(
                text=f"<i>{title_p}</i>",
                font=dict(size=legend_title_size, color=legend_title_color),
            ),
            font=dict(size=legend_text_size - 2, color=legend_text_color),
            x=1.02,
            y=1.0,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
        ),
        legend2=dict(
            title=dict(
                text=f"<i>{title_r}</i>",
                font=dict(size=legend_title_size, color=legend_title_color),
            ),
            font=dict(size=legend_text_size - 2, color=legend_text_color),
            x=1.02,
            y=0.62,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
        ),
        plot_bgcolor=theme.get("panel", "#FFFFFF"),
        paper_bgcolor=theme.get("bg", "#FFFFFF"),
        width=1060,
        height=820,
        margin=dict(l=120, r=210, t=80, b=130),
    )

    shared["last_plotly"] = fig
    shared["data"] = {
        "corr_matrix": corr.reset_index().rename(columns={"index": "variable"}),
        "mantel_results": mantel_df,
    }
    shared["status"] = f"Mantel 图已生成：{n} 个环境变量，{len(mantel_df)} 个 spec 分组。"
    shared["help_text"] = HELP_TEXT
    return fig, shared["data"], shared["status"], HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
