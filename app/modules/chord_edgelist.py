from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.colors import sequential, hex_to_rgb

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.palettes import SCI_NETWORK_COLORS
from app.core.theme import THEMES

# 默认连线色取网络类 SCI 主色（原先硬编码 #5B9BD5）
SCI_NETWORK_PRIMARY = SCI_NETWORK_COLORS[0]

HELP_TEXT = """
Chord Diagram (Plotly 交互版本)

支持输入：
  1. 边表数据 - 必须包含列：from, to, value
  2. 矩阵数据 - 行为节点，列为节点，单元格为连接权重
功能：
  - 自动识别边表/矩阵
  - 扇区排序、按权重缩放、viridis 扇区配色
  - 实心飘带（ribbon）+ 源色着色 + 透明度
  - 外圈刻度与数字、扇区外侧旋转标签
   - 单向方向箭头（源→目标，可选反向；detail = Arrows）
说明：
  - 本模块使用 Plotly 实现，采用经典弦图布局：
    起始角 90°、扇区间隔 4°、飘带透明度 0.25、单向箭头、最大连线置顶
"""

# -----------------------------
# 数据清洗 / 格式识别（与原版相同，此处省略以节省篇幅）
# -----------------------------
# 为保持代码可读性，以下函数与原版完全一致，不再重复注释
def _clean_text(x) -> str:
    return str(x).replace("\ufeff", "").strip()

def _is_probably_numeric_series(s: pd.Series, threshold: float = 0.8) -> bool:
    if s is None or len(s) == 0:
        return False
    test = pd.to_numeric(s, errors="coerce")
    return bool(test.notna().mean() >= threshold)

def _normalize_chord_edgelist(df: pd.DataFrame, default_color: str = SCI_NETWORK_PRIMARY) -> pd.DataFrame:
    work = df.copy()
    work.columns = [_clean_text(c).lower() for c in work.columns]
    rename_map = {}
    for c in work.columns:
        if c in {"from", "source", "src", "start"}:
            rename_map[c] = "from"
        elif c in {"to", "target", "dst", "end"}:
            rename_map[c] = "to"
        elif c in {"value", "weight", "weights", "score"}:
            rename_map[c] = "value"
        elif c in {"color", "colour", "col"}:
            rename_map[c] = "color"
    if rename_map:
        work = work.rename(columns=rename_map)
    if {"from", "to", "value"}.issubset(set(work.columns)):
        cols = ["from", "to", "value"]
        if "color" in work.columns:
            cols.append("color")
        out = work[cols].copy()
        if "color" not in out.columns:
            out["color"] = default_color
    else:
        if work.shape[1] < 3:
            raise ValueError("边表至少需要 3 列：from, to, value；color 可选。")
        out = work.iloc[:, : min(work.shape[1], 4)].copy()
        if out.shape[1] == 3:
            out.columns = ["from", "to", "value"]
            out["color"] = default_color
        else:
            out.columns = ["from", "to", "value", "color"]
    out["from"] = out["from"].astype(str).map(_clean_text)
    out["to"] = out["to"].astype(str).map(_clean_text)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["color"] = out["color"].astype(str).map(_clean_text)
    out = out.dropna(subset=["value"])
    out = out[(out["value"] > 0) & (out["from"] != "") & (out["to"] != "")]
    out = out[out["from"] != out["to"]].copy()
    out.loc[out["color"].eq("") | out["color"].isna(), "color"] = default_color
    if out.empty:
        raise ValueError("没有有效连接可用于绘图。")
    return out.reset_index(drop=True)

def _matrix_to_chord_edgelist(raw_df: pd.DataFrame, default_color: str = SCI_NETWORK_PRIMARY) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = raw_df.copy()
    work.columns = [_clean_text(c) for c in work.columns]
    if work.shape[0] == 0 or work.shape[1] < 2:
        raise ValueError("矩阵格式至少需要 2 列（第 1 列通常为行名，其余为节点列）。")
    first_col = work.columns[0]
    first_series = work[first_col]
    first_col_name = _clean_text(first_col).lower()
    first_col_is_label = (
        first_col_name in {"", "unnamed: 0", "unnamed", "name", "node", "nodes", "id", "label"}
        or (not _is_probably_numeric_series(first_series))
    )
    if first_col_is_label:
        work = work.set_index(first_col)
    else:
        if isinstance(work.index, pd.RangeIndex):
            raise ValueError("矩阵格式建议第一列为节点名（行名），当前未识别到有效行名列。")
    work.index = [_clean_text(x) for x in work.index]
    work.columns = [_clean_text(c) for c in work.columns]
    row_mask = [x != "" and x.lower() != "nan" for x in work.index]
    col_mask = [x != "" and x.lower() != "nan" for x in work.columns]
    work = work.loc[row_mask, col_mask]
    if work.empty:
        raise ValueError("矩阵在清洗后为空。")
    for col in work.columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(axis=0, how="all").dropna(axis=1, how="all").fillna(0)
    if work.empty:
        raise ValueError("矩阵中没有可用数值。")
    edges = work.stack().reset_index()
    edges.columns = ["from", "to", "value"]
    edges["from"] = edges["from"].astype(str).map(_clean_text)
    edges["to"] = edges["to"].astype(str).map(_clean_text)
    edges["value"] = pd.to_numeric(edges["value"], errors="coerce")
    edges = edges.dropna(subset=["value"])
    edges = edges[(edges["value"] > 0) & (edges["from"] != "") & (edges["to"] != "")]
    edges = edges[edges["from"] != edges["to"]].copy()
    if edges.empty:
        raise ValueError("矩阵转换后没有有效连接（要求值 > 0，且排除自连接）。")
    is_symmetric = False
    try:
        if set(work.index) == set(work.columns) and len(work.index) == len(work.columns):
            common = sorted(set(work.index))
            aligned = work.reindex(index=common, columns=common)
            vals = aligned.values.astype(float)
            is_symmetric = np.allclose(vals, vals.T, equal_nan=True)
    except Exception:
        is_symmetric = False
    if is_symmetric:
        edges["pair"] = edges.apply(lambda r: tuple(sorted([str(r["from"]), str(r["to"])])), axis=1)
        edges = edges.drop_duplicates("pair").drop(columns="pair")
    edges["color"] = default_color
    return edges.reset_index(drop=True), work

def _read_chord_data(uploaded, data_mode: str = "auto", default_color: str = SCI_NETWORK_PRIMARY) -> dict:
    raw = read_table(uploaded, uploaded.name)
    if raw is None or raw.empty:
        raise ValueError("读取到的文件为空。")
    if data_mode == "edge":
        edges_df = _normalize_chord_edgelist(raw, default_color=default_color)
        nodes = sorted(pd.unique(pd.concat([edges_df["from"], edges_df["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for _, row in edges_df.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        return {"type": "edgelist", "edges": edges_df, "matrix_df": matrix_df}
    if data_mode == "matrix":
        edges_df, matrix_df = _matrix_to_chord_edgelist(raw, default_color=default_color)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df}
    try:
        edges_df = _normalize_chord_edgelist(raw, default_color=default_color)
        nodes = sorted(pd.unique(pd.concat([edges_df["from"], edges_df["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes, columns=nodes)
        for _, row in edges_df.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        return {"type": "edgelist", "edges": edges_df, "matrix_df": matrix_df}
    except Exception:
        edges_df, matrix_df = _matrix_to_chord_edgelist(raw, default_color=default_color)
        return {"type": "matrix", "edges": edges_df, "matrix_df": matrix_df}

def _sample_df(default_color: str = SCI_NETWORK_PRIMARY) -> pd.DataFrame:
    sample_path = get_sample_path("chord")
    raw = read_table(sample_path, sample_path.name)
    return _normalize_chord_edgelist(raw, default_color=default_color)

def _sample_download_bytes() -> bytes:
    return sample_bytes("chord")

# -----------------------------
# 绘图辅助函数（改进版）
# -----------------------------
def _parse_grid_colors(text: str, nodes: list[str]) -> dict[str, str]:
    raw = [x.strip() for x in str(text).split(",") if x.strip()]
    if not raw:
        raw = ["#CCCCCC"]
    if len(raw) == 1:
        return {n: raw[0] for n in nodes}
    if len(raw) < len(nodes):
        times = (len(nodes) // len(raw)) + 1
        raw = (raw * times)[: len(nodes)]
    return {n: raw[i] for i, n in enumerate(nodes)}

def _node_weights(df: pd.DataFrame, nodes: list[str]) -> dict[str, float]:
    weights = {}
    for n in nodes:
        weights[n] = float(df.loc[df["from"].eq(n), "value"].sum() + df.loc[df["to"].eq(n), "value"].sum())
        if weights[n] <= 0:
            weights[n] = 1.0
    return weights

def _sort_nodes(nodes: list[str], weights: dict[str, float], do_sort: bool, decreasing: bool) -> list[str]:
    if not do_sort:
        return nodes
    return sorted(nodes, key=lambda x: weights.get(x, 0), reverse=decreasing)

def _layout_sectors(nodes: list[str], weights: dict[str, float], start_degree: float, big_gap: float, small_gap: float, scale_mode: bool):
    n = len(nodes)
    if n == 0:
        return {}
    total_gap = big_gap + small_gap * max(n - 1, 0)
    usable = max(360.0 - total_gap, 1.0)
    if scale_mode:
        total_weight = sum(weights[n] for n in nodes)
        spans = {n: usable * weights[n] / total_weight for n in nodes}
    else:
        equal = usable / n
        spans = {n: equal for n in nodes}
    sectors = {}
    cur = float(start_degree)
    for i, node in enumerate(nodes):
        span = spans[node]
        start = cur
        end = cur - span
        sectors[node] = {"start": start, "end": end, "span": span}
        cur = end - (big_gap if i == n - 1 else small_gap)
    return sectors

def _angle_to_xy(deg: float, r: float = 1.0):
    rad = np.deg2rad(deg)
    return np.cos(rad) * r, np.sin(rad) * r


def _viridis_colors(n: int) -> list[str]:
    """viridis 色板的等距采样。"""
    if n <= 0:
        return []
    if n == 1:
        return [sequential.Viridis[len(sequential.Viridis) // 2]]
    step = (len(sequential.Viridis) - 1) / (n - 1)
    return [sequential.Viridis[int(round(i * step))] for i in range(n)]


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转成带透明度的 rgba()，供飘带填充使用。"""
    try:
        r, g, b = hex_to_rgb(hex_color)
    except Exception:
        r, g, b = 200, 200, 200
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha)):.3f})"


def _arc_xy(a0: float, a1: float, r: float, n: int = 18):
    """顺时针角度区间 a0 -> a1 的圆弧采样点。"""
    theta = np.linspace(a0, a1, n)
    rad = np.deg2rad(theta)
    return np.cos(rad) * r, np.sin(rad) * r


def _ribbon_points(src, tgt, pull: float = 0.18, n: int = 20):
    """构造经典弦图风格的实心飘带多边形。

    路径：源扇区圆弧 -> 向圆心收拢的三次贝塞尔 -> 目标扇区圆弧 -> 回到起点。
    """
    s_a0, s_a1 = src
    t_a0, t_a1 = tgt
    r = 0.955
    xs0, ys0 = _arc_xy(s_a0, s_a1, r, n)
    xs1, ys1 = _arc_xy(t_a0, t_a1, r, n)

    p_exit = np.array([xs0[-1], ys0[-1]])
    p_enter = np.array([xs1[0], ys1[0]])
    p_back = np.array([xs1[-1], ys1[-1]])
    p_start = np.array([xs0[0], ys0[0]])

    t = np.linspace(0, 1, n)
    # 出口 -> 目标入口（控制点朝圆心收拢，形成弧线飘带）
    c1 = p_exit * pull
    c2 = p_enter * pull
    bx = (1 - t) ** 3 * p_exit[0] + 3 * (1 - t) ** 2 * t * c1[0] + 3 * (1 - t) * t ** 2 * c2[0] + t ** 3 * p_enter[0]
    by = (1 - t) ** 3 * p_exit[1] + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t ** 2 * c2[1] + t ** 3 * p_enter[1]

    # 目标出口 -> 源起点（回程）
    c3 = p_back * pull
    c4 = p_start * pull
    cx = (1 - t) ** 3 * p_back[0] + 3 * (1 - t) ** 2 * t * c3[0] + 3 * (1 - t) * t ** 2 * c4[0] + t ** 3 * p_start[0]
    cy = (1 - t) ** 3 * p_back[1] + 3 * (1 - t) ** 2 * t * c3[1] + 3 * (1 - t) * t ** 2 * c4[1] + t ** 3 * p_start[1]

    x = np.concatenate([xs0, bx, xs1, cx])
    y = np.concatenate([ys0, by, ys1, cy])
    return x, y


def _chord_centerline(
    src_deg: float,
    tgt_deg: float,
    r: float = 0.968,
    pull: float = 0.18,
    n: int = 32,
):
    """连接两个扇区中点的弦中心线，用于绘制单向箭头。

    起点与终点都落在扇区圆环内缘（r≈0.968，环带由 18px 线宽形成），
    因此每一条箭头都完整包含
    “起点 -> 弧线 -> 终点箭头”，不会出现双向箭头。
    """
    p0 = np.array(_angle_to_xy(src_deg, r), dtype=float)
    p3 = np.array(_angle_to_xy(tgt_deg, r), dtype=float)
    c1 = p0 * pull
    c2 = p3 * pull
    t = np.linspace(0.0, 1.0, n)
    x = (
        (1 - t) ** 3 * p0[0]
        + 3 * (1 - t) ** 2 * t * c1[0]
        + 3 * (1 - t) * t**2 * c2[0]
        + t**3 * p3[0]
    )
    y = (
        (1 - t) ** 3 * p0[1]
        + 3 * (1 - t) ** 2 * t * c1[1]
        + 3 * (1 - t) * t**2 * c2[1]
        + t**3 * p3[1]
    )
    return x, y


def _allocate_positions(df: pd.DataFrame, nodes: list[str], sectors: dict[str, dict], weights: dict[str, float],
                        do_sort: bool, decreasing: bool) -> list[dict]:
    """为每条连接分配源/目标扇区内的圆弧区间（角度均顺时针递减）。

    返回顺序与 ``df`` 行顺序一致，故可直接按位置取用。
    """
    used_src = {n: 0.0 for n in nodes}
    used_tgt = {n: 0.0 for n in nodes}
    out: list[dict | None] = [None] * len(df)

    order: list[int] = []
    for src in nodes:
        idxs = df.index[df["from"].eq(src)].tolist()
        if do_sort:
            idxs = sorted(idxs, key=lambda i: float(df.at[i, "value"]), reverse=decreasing)
        order.extend(idxs)

    for i in order:
        row = df.loc[i]
        src, tgt, val = str(row["from"]), str(row["to"]), float(row["value"])
        if src not in sectors or tgt not in sectors:
            continue
        s_sec, t_sec = sectors[src], sectors[tgt]
        w_s = max(weights.get(src, 0.0), 1e-9)
        w_t = max(weights.get(tgt, 0.0), 1e-9)

        s0 = used_src[src]
        s1 = s0 + val
        used_src[src] = s1
        t0 = used_tgt[tgt]
        t1 = t0 + val
        used_tgt[tgt] = t1

        out[i] = {
            "src0": s_sec["start"] - s_sec["span"] * (s0 / w_s),
            "src1": s_sec["start"] - s_sec["span"] * (s1 / w_s),
            "tgt0": t_sec["start"] - t_sec["span"] * (t0 / w_t),
            "tgt1": t_sec["start"] - t_sec["span"] * (t1 / w_t),
            "mid": (s_sec["start"] - s_sec["span"] * ((s0 + s1) / 2) / w_s),
            "tmid": (t_sec["start"] - t_sec["span"] * ((t0 + t1) / 2) / w_t),
            "value": val,
        }
    return [r for r in out if r is not None]

def _make_bezier_curve(x1, y1, x2, y2, rad=0.22, n_points=50):
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    dx = x2 - x1
    dy = y2 - y1
    length = np.hypot(dx, dy)
    if length == 0:
        return [x1], [y1]
    perp_x = -dy / length
    perp_y = dx / length
    offset = rad * length
    cx = mx + offset * perp_x
    cy = my + offset * perp_y
    t = np.linspace(0, 1, n_points)
    x_curve = (1-t)**2 * x1 + 2*(1-t)*t * cx + t**2 * x2
    y_curve = (1-t)**2 * y1 + 2*(1-t)*t * cy + t**2 * y2
    return x_curve, y_curve

def _lty_to_dash(lty: int) -> str:
    """将线型编号 (0-6) 映射到 Plotly 支持的 dash 样式"""
    mapping = {
        0: "none",   # 无边框
        1: "solid",
        2: "dash",
        3: "dot",
        4: "dashdot",
        5: "dash",
        6: "dashdot"
    }
    return mapping.get(lty, "solid")

# -----------------------------
# Sidebar 控件（与原版相同，保留所有参数）
# -----------------------------
def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]
    # 兼容旧项目包里的排序参数值
    if st.session_state.get("ch_sort") in {"default", "true"}:
        st.session_state["ch_sort"] = "按权重排序" if st.session_state["ch_sort"] == "true" else "默认"
    if st.session_state.get("ch_decreasing") in {"TRUE", "FALSE"}:
        st.session_state["ch_decreasing"] = "降序" if st.session_state["ch_decreasing"] == "TRUE" else "升序"

    sample_loader_control("ch_use_sample", "chord", "ch_load_sample_btn")
    if not st.session_state.get("ch_use_sample", True):
        st.radio(
            "输入数据格式",
            options=["自动识别", "边表（from/to/value）", "矩阵"],
            index=0,
            key="ch_input_format",
            help="自动识别会优先按边表解析，失败后自动按矩阵解析。",
        )
        st.file_uploader(
            "上传 chord 数据文件（CSV / TSV / TXT / XLSX）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="ch_file",
        )

    st.download_button(
        "下载示例数据（Chord）",
        data=_sample_download_bytes(),
        file_name="chord_example.csv",
        mime="text/csv",
        width="stretch",
    )

    st.markdown("### 排序与布局")
    st.selectbox("排序方式", ["默认", "按权重排序"], index=0, key="ch_sort")
    if st.session_state.get("ch_sort") == "按权重排序":
        st.selectbox("排序方向", ["降序", "升序"], index=0, key="ch_decreasing")

    st.slider("起始角度", min_value=0, max_value=360, value=90, key="ch_start_degree")
    st.checkbox("按权重缩放扇区", value=True, key="ch_scale")
    st.slider("Big gap", min_value=0, max_value=100, value=4, key="ch_big_gap")
    st.slider("Small gap", min_value=0, max_value=15, value=4, key="ch_small_gap")
    st.checkbox("显示外圈刻度", value=True, key="ch_show_ticks")
    st.checkbox("显示方向箭头", value=True, key="ch_show_arrows")

    st.markdown("### 细节模式")
    st.radio("Add more details", ["Color", "Border", "Arrows"], horizontal=True, key="ch_detail")

    if st.session_state.get("ch_detail") == "Color":
        st.markdown("### 颜色设置")
        st.selectbox("扇区配色", ["viridis", "自定义"], index=0, key="ch_grid_mode")
        if st.session_state.get("ch_grid_mode") == "自定义":
            st.text_input("Grid.color（逗号分隔）", value=theme.get("grid_color", "#CCCCCC"), key="ch_grid_color")
        st.slider("Transparency", min_value=0.0, max_value=0.9, value=0.25, step=0.05, key="ch_transparency")
        st.color_picker("Label color", value=theme.get("text", "#111827"), key="ch_label_color")

    if st.session_state.get("ch_detail") == "Border":
        st.markdown("### 边框设置")
        st.number_input("Link.type (lty)", min_value=0, max_value=6, value=0, step=1, key="ch_link_type")
        st.text_input("Link.color", value=theme.get("link_color", "#000000"), key="ch_link_color")
        st.slider("Link.width (lwd)", min_value=1, max_value=5, value=1, step=1, key="ch_link_width")

    if st.session_state.get("ch_detail") == "Arrows":
        st.markdown("### 箭头设置")
        if st.session_state.get("ch_direction") not in (-1, 1):
            st.session_state["ch_direction"] = 1
        st.number_input(
            "Direction（1=源→目标，-1=目标→源）",
            min_value=-1,
            max_value=1,
            value=1,
            step=2,
            key="ch_direction",
        )
        st.slider("Link.arrows.size", min_value=0.0, max_value=1.0, value=0.5, step=0.05, key="ch_arr_size")
        st.slider("Link.arrows.width", min_value=1, max_value=10, value=1, step=1, key="ch_arr_width")
        st.text_input("Link.arrows.color", value=theme.get("arrow_color", "#000000"), key="ch_arr_color")
        st.number_input("Link.arrows.type (arr.type)", min_value=1, max_value=6, value=1, step=1, key="ch_arr_type")
        st.radio("Arrows.shape (arr.shape)", ["circle", "ellipse", "curved"], horizontal=True, key="ch_arr_shape")

# -----------------------------
# 主构建逻辑（改进版，支持排序和线型映射）
# -----------------------------
def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    default_link_color = theme.get("primary", "#5B9BD5")
    use_sample = st.session_state.get("ch_use_sample", True)

    if use_sample:
        df = _sample_df(default_color=default_link_color).copy()
        nodes_for_status = sorted(pd.unique(pd.concat([df["from"], df["to"]], ignore_index=True)).tolist())
        matrix_df = pd.DataFrame(0.0, index=nodes_for_status, columns=nodes_for_status)
        for _, row in df.iterrows():
            matrix_df.loc[row["from"], row["to"]] += float(row["value"])
        source_type = "edgelist"
    else:
        uploaded = st.session_state.get("ch_file")
        if uploaded is None:
            return None, None, "请先上传 chord 数据文件。", HELP_TEXT
        mode_label = st.session_state.get("ch_input_format", "自动识别")
        mode_map = {"自动识别": "auto", "边表（from/to/value）": "edge", "矩阵": "matrix"}
        data_mode = mode_map.get(mode_label, "auto")
        try:
            obj = _read_chord_data(uploaded, data_mode=data_mode, default_color=default_link_color)
        except Exception as exc:
            return None, None, f"文件读取失败：{exc}", HELP_TEXT
        df = obj["edges"].copy()
        matrix_df = obj["matrix_df"].copy()
        source_type = obj["type"]

    try:
        df = _normalize_chord_edgelist(df, default_color=default_link_color)
    except Exception as exc:
        return None, None, str(exc), HELP_TEXT

    nodes = pd.unique(pd.concat([df["from"], df["to"]], ignore_index=True)).tolist()
    weights = _node_weights(df, nodes)

    do_sort = st.session_state.get("ch_sort") == "按权重排序"
    decreasing = st.session_state.get("ch_decreasing", "降序") == "降序"
    nodes = _sort_nodes(nodes, weights, do_sort, decreasing)

    sectors = _layout_sectors(
        nodes=nodes,
        weights=weights,
        start_degree=float(st.session_state.get("ch_start_degree", 0)),
        big_gap=float(st.session_state.get("ch_big_gap", 10)),
        small_gap=float(st.session_state.get("ch_small_gap", 1)),
        scale_mode=bool(st.session_state.get("ch_scale", False)),
    )

    pos_pairs = _allocate_positions(df, nodes, sectors, weights, do_sort, decreasing)
    detail = st.session_state.get("ch_detail", "Color")

    grid_color_default = st.session_state.get("ch_grid_color", theme.get("grid_color", "#CCCCCC"))
    label_color = st.session_state.get("ch_label_color", theme.get("text", "#111827"))
    link_color_default = st.session_state.get("ch_link_color", theme.get("link_color", "#000000"))
    arrow_color_default = st.session_state.get("ch_arr_color", theme.get("arrow_color", "#000000"))
    tick_color = theme.get("tick_color", "#000000")
    alpha = float(st.session_state.get("ch_transparency", 0.5))

    # 解析扇区颜色：默认按 viridis 色板给每个节点上色
    if st.session_state.get("ch_grid_mode", "viridis") == "自定义":
        grid_colors = _parse_grid_colors(
            st.session_state.get("ch_grid_color", theme.get("grid_color", "#CCCCCC")), nodes
        )
    else:
        viridis = _viridis_colors(len(nodes))
        grid_colors = {node: viridis[i] for i, node in enumerate(nodes)}

    vals = df["value"].to_numpy(dtype=float)
    if len(vals) == 0:
        return None, None, "没有有效连接可用于绘图。", HELP_TEXT

    # ========== Plotly 绘图 ==========
    fig = go.Figure()

    # 1. 扇区圆环（宽度对应环带高度）
    for node in nodes:
        sec = sectors[node]
        xs, ys = _arc_xy(sec["start"], sec["end"], 1.0, 60)
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="lines",
            line=dict(color=grid_colors.get(node, "#CCCCCC"), width=18),
            showlegend=False,
            hoverinfo="none",
        ))

    # 2. 外圈刻度（主刻度 + 沿切线方向的小数字）
    if st.session_state.get("ch_show_ticks", True):
        tick_x, tick_y = [], []
        for node in nodes:
            sec = sectors[node]
            weight = max(weights.get(node, 0.0), 1e-9)
            step = 5 if weight > 50 else (2 if weight > 10 else 1)
            for v in np.arange(0, weight + 1e-9, step):
                frac = v / weight
                ang = sec["start"] - sec["span"] * frac
                x1, y1 = _angle_to_xy(ang, 1.0)
                x2, y2 = _angle_to_xy(ang, 1.04)
                tick_x += [x1, x2, None]
                tick_y += [y1, y2, None]
                lx, ly = _angle_to_xy(ang, 1.06)
                tang = ang - 90
                while tang > 180:
                    tang -= 360
                while tang < -180:
                    tang += 360
                if tang > 90 or tang < -90:
                    tang += 180
                fig.add_annotation(
                    x=lx, y=ly,
                    text=f"{int(v)}",
                    showarrow=False,
                    font=dict(size=6, color=tick_color),
                    textangle=tang,
                    xanchor="center",
                    yanchor="middle",
                )
        if tick_x:
            fig.add_trace(go.Scatter(
                x=tick_x, y=tick_y, mode="lines",
                line=dict(color=tick_color, width=0.6),
                showlegend=False, hoverinfo="none",
            ))

    # 3. 节点标签（扇区外侧、沿切线方向排布）
    for node in nodes:
        sec = sectors[node]
        mid = (sec["start"] + sec["end"]) / 2
        tx, ty = _angle_to_xy(mid, 1.17)
        # 沿圆周切线方向排布；切向超过 ±90° 时翻转 180°，避免文字倒置
        angle = mid - 90
        while angle > 180:
            angle -= 360
        while angle < -180:
            angle += 360
        if angle > 90 or angle < -90:
            angle += 180
        fig.add_annotation(
            x=tx, y=ty,
            text=node,
            showarrow=False,
            font=dict(size=11, color=label_color),
            textangle=angle,
            xanchor="center",
            yanchor="middle",
        )

    # 4. 飘带（实心 ribbon；透明度 = 1 - transparency）
    ribbon_alpha = max(0.03, 1.0 - alpha)
    draw_order = sorted(range(len(pos_pairs)), key=lambda i: float(df.iloc[i]["value"]))

    for i in draw_order:
        rng = pos_pairs[i]
        src_color = grid_colors.get(str(df.iloc[i]["from"]), link_color_default)
        x, y = _ribbon_points(
            (rng["src0"], rng["src1"]),
            (rng["tgt0"], rng["tgt1"]),
            pull=0.18,
        )
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines",
            fill="toself",
            fillcolor=_rgba(src_color, ribbon_alpha),
            line=dict(color=src_color, width=0.6),
            showlegend=False,
            hoverinfo="none",
        ))

    # 5. 单向方向箭头：每条连接一条“源扇区 -> 目标扇区”的曲线箭头，
    #    包含起点、完整弧线和终点箭头，不会出现双向箭头。
    if st.session_state.get("ch_show_arrows", True):
        direction = int(st.session_state.get("ch_direction", 1) or 1)
        reverse = direction == -1
        arr_size = max(
            0.0, min(1.0, float(st.session_state.get("ch_arr_size", 0.5)))
        )
        arrow_width = max(
            0.8, float(st.session_state.get("ch_arr_width", 1))
        )
        head_len = 0.030 + 0.055 * arr_size
        head_half = 0.016 + 0.028 * arr_size

        shafts: dict[str, tuple[list[float], list[float]]] = {}
        heads: dict[str, tuple[list[float], list[float]]] = {}
        for i, rng in enumerate(pos_pairs):
            src_ang = rng["tmid"] if reverse else rng["mid"]
            tgt_ang = rng["mid"] if reverse else rng["tmid"]
            color_node = str(
                df.iloc[i]["to"] if reverse else df.iloc[i]["from"]
            )
            color = grid_colors.get(color_node, arrow_color_default)
            xs, ys = _chord_centerline(src_ang, tgt_ang)
            if len(xs) < 3:
                continue

            # 起点 -> 终点：完整中心线作为箭杆，保证起止点可见
            sx, sy = shafts.setdefault(color, ([], []))
            sx.extend(xs.tolist())
            sx.append(None)
            sy.extend(ys.tolist())
            sy.append(None)

            # 终点箭头：沿末端切线方向绘制 V 形箭头
            tip = np.array([xs[-1], ys[-1]], dtype=float)
            prev = np.array([xs[-3], ys[-3]], dtype=float)
            tangent = tip - prev
            tangent_len = float(np.hypot(tangent[0], tangent[1]))
            if tangent_len < 1e-12:
                continue
            tangent /= tangent_len
            normal = np.array([-tangent[1], tangent[0]])
            curve_len = float(np.hypot(np.diff(xs), np.diff(ys)).sum())
            head_len_i = min(head_len, 0.45 * curve_len)
            head_half_i = min(head_half, 0.35 * curve_len)
            base = tip - tangent * head_len_i
            left = base + normal * head_half_i
            right = base - normal * head_half_i

            hx, hy = heads.setdefault(color, ([], []))
            hx.extend([left[0], tip[0], right[0], None])
            hy.extend([left[1], tip[1], right[1], None])

        for color, (sx, sy) in shafts.items():
            fig.add_trace(go.Scatter(
                x=sx, y=sy,
                mode="lines",
                line=dict(color=color, width=arrow_width),
                opacity=0.65,
                showlegend=False, hoverinfo="none",
            ))
        for color, (hx, hy) in heads.items():
            fig.add_trace(go.Scatter(
                x=hx, y=hy,
                mode="lines",
                line=dict(color=color, width=max(1.2, arrow_width)),
                showlegend=False, hoverinfo="none",
            ))

    # 6. 边框模式：为每条飘带描边
    if detail == "Border":
        border_color = link_color_default
        border_lw = float(st.session_state.get("ch_link_width", 1))
        border_lty = int(st.session_state.get("ch_link_type", 0))
        border_dash = _lty_to_dash(border_lty) if border_lty > 0 else "solid"
        for rng in pos_pairs:
            x, y = _ribbon_points(
                (rng["src0"], rng["src1"]),
                (rng["tgt0"], rng["tgt1"]),
                pull=0.18,
            )
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines",
                line=dict(color=border_color, width=border_lw, dash=border_dash),
                showlegend=False, hoverinfo="none",
            ))

    # 7. 布局设置
    title_text = ""
    fig.update_layout(
        xaxis=dict(visible=False, range=[-1.38, 1.38], constrain="domain"),
        yaxis=dict(
            visible=False,
            range=[-1.38, 1.38],
            scaleanchor="x",
            scaleratio=1,
            constrain="domain",
        ),
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        width=800,
        height=800,
        margin=dict(l=20, r=20, t=20, b=20),
        hovermode=False
    )

    shared["last_plotly"] = fig
    shared["data"] = df
    shared["status"] = (
        f"Chord 图已生成。识别类型：{source_type}；"
        f"矩阵维度：{matrix_df.shape[0]} x {matrix_df.shape[1]}；"
        f"共 {len(nodes)} 个节点，{len(df)} 条连接。"
    )
    shared["help_text"] = HELP_TEXT

    return fig, df, shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render
