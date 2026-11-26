from __future__ import annotations

import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.palettes import SCI_DIST_COLORS
from app.core.theme import THEMES
from app.core.random_seed import rng_for, seed_control

HELP_TEXT = """
Beeswarm Plot (Plotly 交互版本)
输入数据要求：
  - Groups：分组（x轴）
  - Value：数值（y轴）
  - Group2：点颜色分组或颜色值
功能：
  - 支持 swarm / square / hex / center 排列方法
  - 支持 priority: descending / random / density / none
  - 支持 corral: omit / random / wrap / gutter / none
  - 可自定义点大小、形状、朝向、紧凑度
  - 标题、坐标轴标签、字体样式均可调整
  - 帮助、数据预览、下载由主程序统一处理
说明：
  - 使用 Plotly 实现，支持缩放、悬停等交互
  - Python 实现为近似算法，与常见蜂群图视觉风格一致
"""

FONT_CHOICES = ["sans", "serif", "mono", "wqy-microhei", "STKaiti", "simhei"]
FACE_CHOICES = {
    "默认": "normal",
    "粗体": "bold",
    "斜体": "italic",
    "粗斜体": "italic",
}
MARKER_MAP = {
    "圆形": "circle",
    "三角形": "triangle-up",
    "菱形": "diamond",
    "正方形": "square",
}
SIDE_MAP = {"默认": 0, "向右": 1, "向左": -1}
PRIORITY_MAP = {
    "descending": "desc",
    "random": "random",
    "density": "density",
    "none": "none",
}
CORRAL_MAP = {
    "omit": "omit",
    "random": "random",
    "wrap": "wrap",
    "gutter": "gutter",
    "none": "none",
}

def _sample_df() -> pd.DataFrame:
    sample_path = get_sample_path("beeswarm")
    return read_table(sample_path, sample_path.name)

def _sample_download_bytes() -> bytes:
    return sample_bytes("beeswarm")

def _safe_font(name: str) -> str:
    return name if name else "sans-serif"

def _load_current_df():
    use_sample = st.session_state.get("bee_use_sample", True)
    if use_sample:
        return _sample_df().copy(), None
    uploaded = st.session_state.get("bee_file")
    if uploaded is None:
        return None, "请先上传数据文件。"
    try:
        return read_table(uploaded, uploaded.name), None
    except Exception as exc:
        return None, f"文件读取失败：{exc}"

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if not {"Groups", "Value"}.issubset(df.columns):
        raise ValueError("数据必须包含列：Groups、Value。")
    out = df.copy()
    out["Groups"] = out["Groups"].astype(str)
    out["Value"] = pd.to_numeric(out["Value"], errors="coerce")
    if "Group2" not in out.columns:
        out["Group2"] = out["Groups"]
    out["Group2"] = out["Group2"].astype(str)
    out = out.dropna(subset=["Value"]).copy()
    if out.empty:
        raise ValueError("没有可用于绘图的有效数值数据。")
    return out

def _is_color_like_series(values: pd.Series) -> bool:
    vals = values.dropna().astype(str).unique().tolist()
    if not vals:
        return False
    return all(mcolors.is_color_like(v) for v in vals)

def _resolve_colors(df: pd.DataFrame) -> np.ndarray:
    if _is_color_like_series(df["Group2"]):
        return df["Group2"].astype(str).to_numpy()
    cats = pd.unique(df["Group2"]).tolist()
    # 使用 Plotly 默认色板
    plotly_colors = list(SCI_DIST_COLORS)
    cmap = {cat: plotly_colors[i % len(plotly_colors)] for i, cat in enumerate(cats)}
    return df["Group2"].map(cmap).to_numpy()

def _apply_priority(values: np.ndarray, priority: str, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng if rng is not None else np.random.default_rng(42)
    n = len(values)
    if priority == "desc":
        return np.argsort(values)[::-1]
    elif priority == "random":
        return rng.permutation(n)
    elif priority == "density":
        order = np.argsort(values)
        groups = np.array_split(order, max(2, n//10))
        new_order = []
        for g in groups:
            rng.shuffle(g)
            new_order.extend(g)
        return np.array(new_order)
    else:
        return np.arange(n)

def _hex_candidates(step: float, max_ring: int = 80):
    """六边形格点偏移，按环号 + 横向距离排序，作为 beeswarm 的候选位。"""
    s = np.sqrt(3) / 2
    yield 0.0, 0.0
    for ring in range(1, max_ring + 1):
        pts = []
        for q in range(-ring, ring + 1):
            for r in range(-ring, ring + 1):
                if (abs(q) + abs(r) + abs(q + r)) // 2 != ring:
                    continue
                pts.append((step * (q + r / 2), step * s * r))
        pts.sort(key=lambda p: (abs(p[0]), abs(p[1])))
        for p in pts:
            yield p


def _swarm_offsets(values: np.ndarray, priority: str, side: int, corral: str,
                   diameter_px: float, width_px: float,
                   px_per_y: float, height_px: float):
    """像素空间里的圆填充，返回 (dx_px, dy_px)。

    蜂群图避让逻辑：
    按 priority 逐点找最近的空位，保证任意两点间距 >= 点直径。
    """
    n = len(values)
    if n <= 0:
        return np.array([]), np.array([])

    diameter_px = max(float(diameter_px), 1.0)
    vals = np.asarray(values, dtype=float)
    ys = (vals - float(np.nanmin(vals))) * px_per_y
    order = _apply_priority(vals, priority, rng_for("bee_seed"))

    placed: list[tuple[float, float]] = []
    dx_px = np.zeros(n)
    dy_px = np.zeros(n)
    limit = max(float(width_px), diameter_px)

    for idx in order:
        chosen = None
        for cx, cy in _hex_candidates(diameter_px, max_ring=80):
            if side > 0 and cx < 0:
                continue
            if side < 0 and cx > 0:
                continue
            if abs(cx) > limit:
                break
            cy_abs = ys[idx] + cy
            if cy_abs < 0 or cy_abs > height_px:
                continue
            ok = True
            for px_, py_ in placed:
                ddx = cx - px_
                ddy = cy_abs - py_
                if ddx * ddx + ddy * ddy < diameter_px * diameter_px * 0.98:
                    ok = False
                    break
            if ok:
                chosen = (cx, cy)
                break

        if chosen is None:
            if corral == "omit":
                dx_px[idx] = np.nan
                dy_px[idx] = np.nan
                continue
            if corral == "wrap":
                chosen = (limit, 0.0)
            elif corral == "gutter":
                chosen = (limit, 0.0)
            else:
                chosen = (rng_for("bee_seed").uniform(-limit, limit), 0.0)

        dx_px[idx], dy_px[idx] = chosen
        placed.append((chosen[0], ys[idx] + chosen[1]))

    return dx_px, dy_px

def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    sample_loader_control("bee_use_sample", "beeswarm", "bee_load_sample_btn")
    if not st.session_state.get("bee_use_sample", True):
        st.file_uploader(
            "上传数据文件 (txt/tsv/csv)",
            type=["txt", "tsv", "csv"],
            key="bee_file",
        )
    st.download_button(
        "示例数据",
        data=_sample_download_bytes(),
        file_name="beeswarm_example.txt",
        mime="text/tab-separated-values",
        width="stretch",
    )
    st.checkbox("形状设置", value=False, key="bee_shape_on")
    if st.session_state.get("bee_shape_on", False):
        st.slider("点的大小", 0.0, 5.0, 1.5, 0.1, key="bee_point_size")
        st.selectbox("点形状", list(MARKER_MAP.keys()), index=0, key="bee_shape")
    st.checkbox("方向/排列设置", value=False, key="bee_dir_on")
    if st.session_state.get("bee_dir_on", False):
        st.selectbox("朝向", ["默认", "向右", "向左"], index=0, key="bee_side")
        st.selectbox("点的排列方式", ["swarm", "square", "hex", "center"], index=0, key="bee_method")
        st.selectbox("布局方法", ["descending", "random", "density", "none"], index=0, key="bee_priority")
        st.selectbox("corral", ["omit", "random", "wrap", "gutter", "none"], index=0, key="bee_corral")
        st.slider("紧凑度", 0.5, 3.0, 1.0, 0.1, key="bee_cex")
    seed_control("bee_seed")
    st.checkbox("标题设置", value=False, key="bee_title_on")
    if st.session_state.get("bee_title_on", False):
        st.text_input("主标题", value="Beeswarm", key="bee_title")
        st.text_input("X轴标题", value="", key="bee_xlabel")
        st.text_input("Y轴标题", value="", key="bee_ylabel")
    st.checkbox("字体设置", value=False, key="bee_font_on")
    if st.session_state.get("bee_font_on", False):
        st.selectbox("标题字体样式", FONT_CHOICES, index=0, key="bee_title_family")
        st.selectbox("标题字重", list(FACE_CHOICES.keys()), index=0, key="bee_title_face")
        st.slider("标题字号", 1, 40, 30, key="bee_title_size")
        st.selectbox("横坐标字体样式", FONT_CHOICES, index=0, key="bee_xtick_family")
        st.selectbox("横坐标字重", list(FACE_CHOICES.keys()), index=0, key="bee_xtick_face")
        st.slider("横坐标字号", 5, 40, 15, key="bee_xtick_size")
        st.selectbox("纵坐标字体样式", FONT_CHOICES, index=0, key="bee_ytick_family")
        st.selectbox("纵坐标字重", list(FACE_CHOICES.keys()), index=0, key="bee_ytick_face")
        st.slider("纵坐标字号", 5, 40, 15, key="bee_ytick_size")
        st.selectbox("横坐标标题字体样式", FONT_CHOICES, index=0, key="bee_xlabel_family")
        st.selectbox("横坐标标题字重", list(FACE_CHOICES.keys()), index=0, key="bee_xlabel_face")
        st.slider("横坐标标题字号", 1, 40, 20, key="bee_xlabel_size")
        st.selectbox("纵坐标标题字体样式", FONT_CHOICES, index=0, key="bee_ylabel_family")
        st.selectbox("纵坐标标题字重", list(FACE_CHOICES.keys()), index=0, key="bee_ylabel_face")
        st.slider("纵坐标标题字号", 1, 40, 20, key="bee_ylabel_size")
    st.number_input("图形高度（px）", min_value=300, max_value=3000, value=800, step=10, key="bee_h")
    st.number_input("图形宽度（px）", min_value=300, max_value=3000, value=900, step=10, key="bee_w")

def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    raw, err = _load_current_df()
    if err:
        return None, None, err, HELP_TEXT
    try:
        df = _normalize_df(raw)
    except Exception as exc:
        return None, None, str(exc), HELP_TEXT

    shared["data"] = df.copy()

    shape_on = st.session_state.get("bee_shape_on", False)
    point_size = st.session_state.get("bee_point_size", 1.5) if shape_on else 1.5
    marker = MARKER_MAP.get(st.session_state.get("bee_shape", "圆形"), "circle")

    dir_on = st.session_state.get("bee_dir_on", False)
    side = SIDE_MAP.get(st.session_state.get("bee_side", "默认"), 0)
    method = st.session_state.get("bee_method", "swarm") if dir_on else "swarm"
    priority = PRIORITY_MAP.get(st.session_state.get("bee_priority", "descending"), "desc")
    corral = CORRAL_MAP.get(st.session_state.get("bee_corral", "none"), "none")
    cex = st.session_state.get("bee_cex", 1.0) if dir_on else 1.0

    base_width = 0.18 if method == "swarm" else 0.22
    width = base_width * cex

    colors = _resolve_colors(df)
    df = df.copy()
    df["_color"] = colors

    groups = pd.unique(df["Groups"]).tolist()
    x_map = {g: i for i, g in enumerate(groups)}

    # 像素几何：点直径、每单位数据对应的像素，用于真实碰撞排布
    fig_w = st.session_state.get("bee_w", 900)
    fig_h = st.session_state.get("bee_h", 800)
    margin_l, margin_r, margin_t, margin_b = 60, 30, 80, 50
    plot_w_px = max(fig_w - margin_l - margin_r, 200)
    plot_h_px = max(fig_h - margin_t - margin_b, 200)
    px_per_x = plot_w_px / max(len(groups), 1)
    y_lo, y_hi = float(df["Value"].min()), float(df["Value"].max())
    y_span = max(y_hi - y_lo, 1e-9)
    px_per_y = plot_h_px / (y_span * 1.12)
    diameter_px = max(point_size * 3.8, 1.5)
    width_px = 0.45 * px_per_x

    # 创建 Plotly 图形
    fig = go.Figure()

    for g in groups:
        sub = df[df["Groups"] == g].copy().reset_index(drop=True)
        if method == "center":
            off_x = np.zeros(len(sub))
            off_y = np.zeros(len(sub))
        elif method in ("square", "hex"):
            # 规则网格：对应 square/hex 排列
            n = len(sub)
            cols = max(1, int(np.ceil(np.sqrt(n))))
            rows = int(np.ceil(n / cols))
            idx = np.arange(n)
            col = idx % cols - (cols - 1) / 2
            row = idx // cols - (rows - 1) / 2
            if method == "hex":
                col = col + 0.5 * (np.abs(row) % 2)
            off_x = col * diameter_px / px_per_x
            off_y = row * diameter_px * 0.9 / px_per_y
            if side > 0:
                off_x = np.abs(off_x)
            elif side < 0:
                off_x = -np.abs(off_x)
        else:
            dx_px, dy_px = _swarm_offsets(
                sub["Value"].to_numpy(dtype=float),
                priority=priority,
                side=side,
                corral=corral,
                diameter_px=diameter_px,
                width_px=width_px,
                px_per_y=px_per_y,
                height_px=plot_h_px,
            )
            off_x = dx_px / px_per_x
            off_y = dy_px / px_per_y
        valid_mask = ~np.isnan(off_x) & ~np.isnan(off_y)
        x_vals = np.full(len(sub), x_map[g], dtype=float) + off_x
        y_vals = sub["Value"].to_numpy(dtype=float) + off_y
        fig.add_trace(go.Scatter(
            x=x_vals[valid_mask],
            y=y_vals[valid_mask],
            mode='markers',
            marker=dict(
                size=diameter_px,
                color=sub["_color"][valid_mask].tolist(),
                symbol=marker,
                opacity=1.0,
                line=dict(width=0)
            ),
            showlegend=False,
            hoverinfo='y+x',
            name=g
        ))

    # 标题和标签
    title_on = st.session_state.get("bee_title_on", False)
    if title_on:
        title = st.session_state.get("bee_title", "Beeswarm")
        xlabel = st.session_state.get("bee_xlabel", "")
        ylabel = st.session_state.get("bee_ylabel", "")
    else:
        title = ""
        xlabel = ""
        ylabel = ""

    # 字体设置
    font_on = st.session_state.get("bee_font_on", False)
    title_font_size = st.session_state.get("bee_title_size", 30) if font_on else 20
    title_font_family = _safe_font(st.session_state.get("bee_title_family", "sans")) if font_on else "sans"
    title_font_weight = FACE_CHOICES.get(st.session_state.get("bee_title_face", "默认"), "normal") if font_on else "normal"
    xlabel_font_size = st.session_state.get("bee_xlabel_size", 20) if font_on else 15
    ylabel_font_size = st.session_state.get("bee_ylabel_size", 20) if font_on else 15
    xtick_font_size = st.session_state.get("bee_xtick_size", 15) if font_on else 12
    ytick_font_size = st.session_state.get("bee_ytick_size", 15) if font_on else 12
    text_color = theme.get("text", "#000000")

    # theme_grey 的灰底 + 白色网格；深色主题沿用站点面板色
    if st.session_state.theme == "Light":
        panel_bg = "#EBEBEB"
        grid_color = "#FFFFFF"
        tick_color = "#333333"
    else:
        panel_bg = theme.get("panel", "#2d2d3a")
        grid_color = "rgba(255,255,255,0.16)"
        tick_color = theme.get("muted", "#a0a0b0")

    fig.update_layout(
        title=dict(text=title, font=dict(size=title_font_size, family=title_font_family, weight=title_font_weight, color=text_color), x=0.4, xanchor="center"),
        xaxis=dict(
            title=dict(text=xlabel, font=dict(size=xlabel_font_size, color=text_color)),
            tickvals=list(range(len(groups))),
            ticktext=groups,
            tickfont=dict(size=xtick_font_size, color=text_color),
            showgrid=True,
            gridcolor=grid_color,
            griddash="solid",
            zeroline=False,
            showline=False,
            ticks="outside",
            ticklen=6,
            tickcolor=tick_color,
        ),
        yaxis=dict(
            title=dict(text=ylabel, font=dict(size=ylabel_font_size, color=text_color)),
            tickfont=dict(size=ytick_font_size, color=text_color),
            showgrid=True,
            gridcolor=grid_color,
            zeroline=False,
            showline=False,
            ticks="outside",
            ticklen=6,
            tickcolor=tick_color,
        ),
        plot_bgcolor=panel_bg,
        paper_bgcolor=panel_bg,
        width=st.session_state.get("bee_w", 900),
        height=st.session_state.get("bee_h", 800),
        margin=dict(l=60, r=30, t=80, b=50)
    )

    shared["last_plotly"] = fig
    shared["status"] = f"Beeswarm 图已生成，共 {len(df)} 条记录，{len(groups)} 个分组。"
    shared["help_text"] = HELP_TEXT

    return fig, df, shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render
