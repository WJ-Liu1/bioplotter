"""CircleViz — native Plotly implementation.

Implements architecture doc §3.3 (highest-risk module).

Figure semantics (all layers inside **one** ``polar`` subplot):

===================  ==========================  ==================================
layer                r band (default)            rendering
===================  ==========================  ==================================
centre node          ``[0.00, 0.06]``            marker + group text
centre ↔ node links  ``[0.06, 0.52]``            one ``lines`` trace, ``None`` gaps
inner ring            ``[0.55, 0.63]``  (data1)   closed 4-vertex polygons per category
middle ring           ``[0.65, 0.73]``  (data2)   closed polygons + 3-stop colour ramp
outer ring            ``[0.75, 0.83]``  (data3)   closed polygons + 3-stop colour ramp
4th ring              ``[0.85, 0.85+h]`` (data4)  radial bars (closed polygons)
===================  ==========================  ==================================

Critical implementation notes
-----------------------------
* **No ``go.Barpolar``**: it has no ``base``/``r0`` property and can only draw from
  ``r = 0``, so it cannot render a hollow ring segment (architecture D1 / §3.3).
  Every annular segment is a closed polygon::

      theta = [t0, t1, t1, t0, t0]
      r     = [ra, ra, rb, rb, ra]

* θ is always passed in **degrees** (``np.degrees``); ``thetaunit="radians"`` is
  avoided because its ``fill="toself"`` behaviour differs across Plotly versions.
* Segments that share a colour are merged into one trace with ``None`` separators,
  keeping ``len(fig.data) <= 32`` even for a few hundred entities.

Key naming follows §8.2 — ``circle_link_width`` / ``circle_link_alpha`` instead of
``*_edge_*`` (``edge`` is a ``reset_module_colors()`` filter substring).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.colors import sample_colorscale
import streamlit as st
from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
CircleViz（原生三层同心环 + 环形网络）

支持输入（固定 6 列，按列顺序解析，列名忽略）：
  1. id      序号（整数）
  2. name    实体名，格式 "分组-编号"（如 Cis-1 / Ctrl-3），前缀即分组
  3. data1   分类字符（可空），用于内环类别配色
  4. data2   数值（中环 low/mid/high 三色渐变）
  5. data3   数值（外环 low/mid/high 三色渐变）
  6. data4   数值 0~20（最外第 4 环的径向柱高度）

图形语义（单个 polar 子图）：
  - 中心节点：name 前缀（Cis / Ctrl）作为中心节点，中心写分组名
  - 连线：中心节点 ↔ 每个圆周节点
  - 内环：data1 分类色环段
  - 中环 / 外环：data2 / data3 数值三色渐变环段
  - 第 4 环：data4 径向柱

可配置项：
  - 三环高度、第 4 环柱高倍率、环间留白
  - 中环 / 外环各 low / mid / high 三色；内环类别配色（最多 8 类）
  - 连线颜色 / 宽度 / 透明度，中心与圆周节点大小与形状
  - 中心文字开关、图例开关、排序方式、标题

说明：
  - 环段全部用「4 顶点闭合多边形」实现，可精确控制内外半径（Barpolar 无 base，做不到）
  - 同色环段合并进一条 trace，trace 总数控制在 32 条以内
  - 连续数值环按 6 个色阶量化后再合并，视觉上与连续渐变基本一致
  - 原版独立柱状图改为最外第 4 环径向柱，避免单图过载
"""
RING_LABELS: dict[str, str] = {    "inner": "内环（data1 分类）",    "mid": "中环（data2 数值）",    "outer": "外环（data3）",    "bar": "第 4 环（data4 柱）",}
NODE_SHAPE_OPTIONS: dict[str, str] = {    "圆形 (circle)": "circle",    "方形 (square)": "square",    "菱形 (lozenge)": "diamond",    "上三角 (triangle-up)": "triangle-up",    "下三角 (triangle-down)": "triangle-down",}
CAT_COLOR_KEYS: tuple[str, ...] = (    "circle_cat_color_1",    "circle_cat_color_2",    "circle_cat_color_3",    "circle_cat_color_4",    "circle_cat_color_5",    "circle_cat_color_6",    "circle_cat_color_7",    "circle_cat_color_8",)
MID_COLOR_KEYS: tuple[str, str, str] = ("circle_mid_low_color", "circle_mid_mid_color", "circle_mid_high_color")
OUT_COLOR_KEYS: tuple[str, str, str] = ("circle_out_low_color", "circle_out_mid_color", "circle_out_high_color")
RING_CENTRES: tuple[str, float] = (("inner", 0.59), ("mid", 0.69), ("outer", 0.79))
BAR_BASE = 0.85
LINK_INNER = 0.06
LINK_OUTER = 0.52
COLOUR_BINS = 6
MAX_TRACES = 32
EXPECTED_COLUMNS = ("id", "name", "data1", "data2", "data3", "data4")
_FALLBACK_COLORS: dict[str, str] = {    "circle_cat1": "#8DD3C7",    "circle_cat2": "#FFFFB3",    "circle_cat3": "#BEBADA",    "circle_cat4": "#FB8072",    "circle_cat5": "#80B1D3",    "circle_mid_low": "#4575B4",    "circle_mid_mid": "#FFFFBF",    "circle_mid_high": "#D73027",    "circle_out_low": "#FFFFFF",    "circle_out_mid": "#80B1D3",    "circle_out_high": "#2166AC",    "circle_link": "#B0B0B0",    "circle_center": "#E45756",    "bg": "#f5f7fb",    "text": "#111827",    "muted": "#6b7280",}# ---------------------------------------------------------------------------# Colour helpers# ---------------------------------------------------------------------------
def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])
def _theme_color(key: str) -> str:
    return _theme().get(key, _FALLBACK_COLORS.get(key, "#4C78A8"))
def _binned_colors(scale: list[str], values: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Quantise a 0..1 series into ``COLOUR_BINS`` colours of a 3-stop ramp."""
    stops = [(index + 0.5) / COLOUR_BINS for index in range(COLOUR_BINS)]
    colours = sample_colorscale(scale, stops)
    bins = np.clip((np.asarray(values, dtype=float) * COLOUR_BINS).astype(int), 0, COLOUR_BINS - 1)
    return bins, colours
def _normalise(series: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    finite = numeric[np.isfinite(numeric)]
    if finite.empty:
        return np.full(len(numeric), 0.5)
    low, high = float(finite.min()), float(finite.max())
    if np.isclose(low, high):
        return np.full(len(numeric), 0.5)
    return ((numeric - low) / (high - low)).fillna(0.0).to_numpy(dtype=float)# ---------------------------------------------------------------------------# Data helpers# ---------------------------------------------------------------------------
def _load_frame() -> tuple[pd.DataFrame | None, str]:
    if st.session_state.get("circle_use_sample", True):
        try:
            path = get_sample_path("circleviz_cis_ctrl")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("circle_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""
def _parse_fixed_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    """Parse the six positional columns; header names are ignored."""
    if frame.shape[1] < 6:
        return None, (            f"CircleViz 需要固定 6 列（id / name / data1 / data2 / data3 / data4），"            f"当前仅 {frame.shape[1]} 列。"        )
    work = pd.DataFrame(        {            "id": pd.to_numeric(frame.iloc[:, 0], errors="coerce"),            "name": frame.iloc[:, 1].astype(str).str.strip(),            "data1": frame.iloc[:, 2].astype(str).str.strip(),            "data2": pd.to_numeric(frame.iloc[:, 3], errors="coerce"),            "data3": pd.to_numeric(frame.iloc[:, 4], errors="coerce"),            "data4": pd.to_numeric(frame.iloc[:, 5], errors="coerce"),        }    )
    work = work[work["name"] != ""]
    work = work[~work["name"].str.lower().isin({"nan", "none"})]
    if work.empty:
        return None, "name 列没有有效实体名。"
    work["data2"] = work["data2"].fillna(0.0)
    work["data3"] = work["data3"].fillna(0.0)
    work["data4"] = work["data4"].fillna(0.0)
    work["data1"] = work["data1"].replace({"nan": "", "None": "", "none": ""})
    work["data1"] = work["data1"].map(lambda value: str(value).strip() if str(value).strip() else "无")
    return work.reset_index(drop=True), ""
def _type_of(value: str) -> str:
    """``Cis-1`` → ``Cis``; a name without a separator is its own type."""
    text = str(value)
    for separator in ("-", "_", "."):
        if separator in text:
            return text.split(separator)[0].strip()
    return text.strip()# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("circle_use_sample", ["circleviz_cis_ctrl"], "circle_load_sample_btn")
    if not st.session_state.get("circle_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="circle_file_upload",        )
        st.caption("固定 6 列顺序：id / name / data1 / data2 / data3 / data4（列名忽略）。")
    if frame is not None and frame.shape[1] >= 2:
        raw_names = [str(c) for c in frame.columns]
        if st.session_state.get("circle_type_col") not in raw_names:
            st.session_state["circle_type_col"] = raw_names[1]
        st.selectbox(            "分组前缀来源列",            options=raw_names,            key="circle_type_col",            help="从该列的“前缀”提取分组（如 Cis-1 → Cis）。默认取第 2 列 name。",        )
    st.markdown("### 环高度与留白")
    st.slider("内环高度", 0.02, 0.20, 0.08, 0.01, key="circle_h_inner")
    st.slider("中环高度", 0.02, 0.20, 0.08, 0.01, key="circle_h_mid")
    st.slider("外环高度", 0.02, 0.20, 0.08, 0.01, key="circle_h_outer")
    st.slider("第 4 环柱高倍率", 0.2, 3.0, 1.0, 0.1, key="circle_h_bar")
    st.slider("环间留白", 0.0, 0.05, 0.01, 0.005, key="circle_gap")
    st.markdown("### 环配色")
    st.color_picker("中环 low", value=_theme_color("circle_mid_low"), key="circle_mid_low_color")
    st.color_picker("中环 mid", value=_theme_color("circle_mid_mid"), key="circle_mid_mid_color")
    st.color_picker("中环 high", value=_theme_color("circle_mid_high"), key="circle_mid_high_color")
    st.color_picker("外环 low", value=_theme_color("circle_out_low"), key="circle_out_low_color")
    st.color_picker("外环 mid", value=_theme_color("circle_out_mid"), key="circle_out_mid_color")
    st.color_picker("外环 high", value=_theme_color("circle_out_high"), key="circle_out_high_color")
    parsed: pd.DataFrame | None = None
    if frame is not None:
        parsed, _ = _parse_fixed_columns(frame)
    with st.expander("内环类别配色（最多 8 类）", expanded=False):
        categories: list[str] = []
        if parsed is not None:
            categories = [value for value in pd.unique(parsed["data1"]) if str(value).strip()]
        if categories:
            for index, category in enumerate(categories[:8]):
                st.color_picker(                    f"类别 {category}",                    value=_theme_color(f"circle_cat{index + 1}") if index < 5 else px.colors.qualitative.Plotly[index % 10],                    key=CAT_COLOR_KEYS[index],                )
        else:
            st.caption("当前数据没有可用类别（data1 全为空）。")
    st.markdown("### 网络与节点")
    st.slider("中心节点大小", 8, 40, 22, 1, key="circle_center_size")
    st.slider("圆周节点大小", 4, 24, 10, 1, key="circle_normal_size")
    st.slider("连线宽度", 0.2, 5.0, 1.2, 0.1, key="circle_link_width")
    st.slider("连线透明度", 0.05, 1.0, 0.80, 0.05, key="circle_link_alpha")
    st.selectbox("节点形状", list(NODE_SHAPE_OPTIONS.keys()), index=0, key="circle_node_shape")
    st.color_picker("连线颜色", value=_theme_color("circle_link"), key="circle_link_color")
    st.color_picker("中心节点颜色", value=_theme_color("circle_center"), key="circle_center_color")
    st.markdown("### 排序与图例")
    st.radio(        "排序方式",        ["按 data4 升序", "按分组名升序"],        index=0,        key="circle_sort_mode",        horizontal=False,    )
    st.checkbox("显示中心文字", value=True, key="circle_show_center_text")
    st.checkbox("显示图例", value=True, key="circle_show_legend")
    st.markdown("### 标题")
    st.text_input("图形标题", "CircleViz", key="circle_title")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    work, parse_error = _parse_fixed_columns(frame)
    if work is None:
        return None, None, parse_error, HELP_TEXT
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT    # ---- group / type extraction -----------------------------------------
    type_col = st.session_state.get("circle_type_col")
    if type_col and type_col in frame.columns and frame.shape[1] >= 6:
        raw_values = frame[type_col].astype(str).str.strip().reset_index(drop=True)
        if len(raw_values) == len(work):
            work["type"] = raw_values.map(_type_of)
        else:
            work["type"] = work["name"].map(_type_of)
    else:
        work["type"] = work["name"].map(_type_of)    # ---- ordering ---------------------------------------------------------
    if st.session_state.get("circle_sort_mode", "按 data4 升序") == "按分组名升序":
        work = work.sort_values(["type", "name"], kind="mergesort").reset_index(drop=True)
    else:
        work = work.sort_values(["data4", "name"], ascending=[True, True], kind="mergesort").reset_index(drop=True)
    n_items = len(work)
    if n_items < 2:
        return None, None, "至少需要 2 行数据才能绘制环形图。", HELP_TEXT    # ---- geometry ---------------------------------------------------------
    slice_width = 360.0 / n_items
    theta_centres = [index * slice_width + slice_width / 2.0 for index in range(n_items)]
    angular_pad = slice_width * 0.05
    theta_starts = [centre - slice_width / 2.0 + angular_pad for centre in theta_centres]
    theta_ends = [centre + slice_width / 2.0 - angular_pad for centre in theta_centres]
    gap = float(st.session_state.get("circle_gap", 0.01))
    heights = {        "inner": float(st.session_state.get("circle_h_inner", 0.08)),        "mid": float(st.session_state.get("circle_h_mid", 0.08)),        "outer": float(st.session_state.get("circle_h_outer", 0.08)),    }
    bands: dict[str, tuple[float, float]] = {}
    for name, centre in RING_CENTRES:
        half = heights[name] / 2.0
        bands[name] = (max(0.0, centre - half + gap), centre + half - gap)
    bar_h = float(st.session_state.get("circle_h_bar", 1.0))
    data4_norm = _normalise(work["data4"])
    bar_tops = [BAR_BASE + float(value) * 0.35 * bar_h for value in data4_norm]
    r_max = max(bar_tops) if bar_tops else BAR_BASE + 0.35
    bar_color = _theme_color("circle_bar")
    show_legend = bool(st.session_state.get("circle_show_legend", True))
    fig = go.Figure()
    def _add_polygons(        segments: list[tuple[float, float, float, float, str]],        legend_name: str,        show_in_legend: bool = False,        legend_labels: dict[str, str] | None = None,    ) -> int:
        """Draw ``(ra, rb, t0, t1, colour)`` polygons, merged per colour."""
        grouped: dict[str, list[tuple[float, float, float, float]]] = {}
        for ra, rb, t0, t1, color in segments:
            grouped.setdefault(color, []).append((ra, rb, t0, t1))
        for order, (color, boxes) in enumerate(grouped.items()):
            r_values: list[float | None] = []
            theta_values: list[float | None] = []
            for ra, rb, t0, t1 in boxes:
                r_values.extend([ra, rb, rb, ra, ra, None])
                theta_values.extend([t0, t0, t1, t1, t0, None])
            if legend_labels and color in legend_labels:
                trace_name = legend_labels[color]
            else:
                trace_name = legend_name if order == 0 else f"{legend_name} · {color}"
            fig.add_trace(                go.Scatterpolar(                    r=r_values,                    theta=theta_values,                    mode="lines",                    fill="toself",                    fillcolor=color,                    line=dict(color=color, width=0.4),                    name=trace_name,                    showlegend=show_in_legend,                    hoverinfo="skip",                )            )
        return len(grouped)
    trace_budget_used = 0    # ---- inner ring (categorical) ----------------------------------------
    inner_categories = [value for value in pd.unique(work["data1"]) if str(value).strip()]
    palette: dict[str, str] = {}
    for index, category in enumerate(inner_categories[:8]):
        key = CAT_COLOR_KEYS[index]
        fallback = (            _theme_color(f"circle_cat{index + 1}")            if index < 5            else px.colors.qualitative.Plotly[index % len(px.colors.qualitative.Plotly)]        )
        palette[category] = st.session_state.get(key) or fallback
    inner_segments = [        (bands["inner"][0], bands["inner"][1], theta_starts[index], theta_ends[index],         palette.get(str(work["data1"].iloc[index]), _FALLBACK_COLORS["circle_cat1"]))        for index in range(n_items)    ]
    inner_legend = {color: f"data1 = {category}" for category, color in palette.items()}
    trace_budget_used += _add_polygons(        inner_segments,        RING_LABELS["inner"],        show_in_legend=show_legend,        legend_labels=inner_legend,    )    # ---- middle + outer rings (continuous, quantised into 6 bins) --------
    mid_scale = [        st.session_state.get(MID_COLOR_KEYS[0]) or _theme_color("circle_mid_low"),        st.session_state.get(MID_COLOR_KEYS[1]) or _theme_color("circle_mid_mid"),        st.session_state.get(MID_COLOR_KEYS[2]) or _theme_color("circle_mid_high"),    ]
    out_scale = [        st.session_state.get(OUT_COLOR_KEYS[0]) or _theme_color("circle_out_low"),        st.session_state.get(OUT_COLOR_KEYS[1]) or _theme_color("circle_out_mid"),        st.session_state.get(OUT_COLOR_KEYS[2]) or _theme_color("circle_out_high"),    ]
    for ring, values, scale, label in (        ("mid", _normalise(work["data2"]), mid_scale, RING_LABELS["mid"]),        ("outer", _normalise(work["data3"]), out_scale, RING_LABELS["outer"]),    ):
        bins, colors = _binned_colors(scale, values)
        segments = [            (bands[ring][0], bands[ring][1], theta_starts[index], theta_ends[index], colors[bins[index]])            for index in range(n_items)        ]
        trace_budget_used += _add_polygons(segments, label)    # ---- 4th ring: radial bars from data4 --------------------------------
    bar_segments = [        (BAR_BASE, bar_tops[index], theta_starts[index], theta_ends[index], bar_color)        for index in range(n_items)        if not np.isclose(bar_tops[index], BAR_BASE)    ]
    if bar_segments:
        trace_budget_used += _add_polygons(bar_segments, RING_LABELS["bar"])    # ---- ring-network links：每个分组一个中心节点 + 向组内节点的对角曲线 ----    # 环形网络：中心节点半径 0.5、外围节点半径 2，    # 边的颜色按 source_type（即分组）着色。
    link_color = st.session_state.get("circle_link_color") or _theme_color("circle_link")
    link_width = float(st.session_state.get("circle_link_width", 1.2))
    link_alpha = float(st.session_state.get("circle_link_alpha", 0.80))
    types = [str(value) for value in work["type"]]
    type_colors: dict[str, str] = {}
    for index, value in enumerate(pd.unique(pd.Series(types))):
        fallback = (            _theme_color(f"circle_cat{index + 1}")            if index < 5            else px.colors.qualitative.Plotly[index % len(px.colors.qualitative.Plotly)]        )
        type_colors[str(value)] = st.session_state.get(CAT_COLOR_KEYS[index]) or fallback
    def _mean_angle(values: list[float]) -> float:
        """角度向量平均，避免 0/360 断层。"""
        xs = np.mean([np.cos(np.deg2rad(value)) for value in values])
        ys = np.mean([np.sin(np.deg2rad(value)) for value in values])
        return float(np.rad2deg(np.arctan2(ys, xs)) % 360)
    centre_thetas: dict[str, float] = {}
    for name in type_colors:
        values = [theta for theta, kind in zip(theta_centres, types) if kind == name]
        if values:
            centre_thetas[name] = _mean_angle(values)
    for name, centre_theta in centre_thetas.items():
        color = type_colors.get(name, link_color)
        link_r: list[float | None] = []
        link_theta: list[float | None] = []
        for theta, kind in zip(theta_centres, types):
            if kind != name:
                continue            # 走最短角度差，避免连线绕远半圈
            delta = (float(theta) - centre_theta + 180.0) % 360.0 - 180.0
            steps = 18
            for step in range(steps + 1):
                frac = step / steps
                link_r.append(LINK_INNER + (LINK_OUTER - LINK_INNER) * frac)                # 角度滞后于半径，形成向内收拢再外展的“对角”曲线
                link_theta.append(centre_theta + delta * (frac ** 1.55))
            link_r.append(None)
            link_theta.append(None)
        fig.add_trace(            go.Scatterpolar(                r=link_r,                theta=link_theta,                mode="lines",                line=dict(color=color, width=link_width),                opacity=max(0.05, link_alpha),                showlegend=False,                hoverinfo="skip",            )        )    # ---- nodes ------------------------------------------------------------
    shape_label = st.session_state.get("circle_node_shape", list(NODE_SHAPE_OPTIONS.keys())[0])
    node_symbol = NODE_SHAPE_OPTIONS.get(shape_label, "circle")
    centre_size = int(st.session_state.get("circle_center_size", 22))
    normal_size = int(st.session_state.get("circle_normal_size", 10))
    text_color = theme.get("text", "#111827")
    for name in type_colors:
        mark_theta = [theta for theta, kind in zip(theta_centres, types) if kind == name]
        if not mark_theta:
            continue
        fig.add_trace(            go.Scatterpolar(                r=[LINK_OUTER] * len(mark_theta),                theta=mark_theta,                mode="markers",                marker=dict(                    size=normal_size,                    color=type_colors[name],                    symbol=node_symbol,                    opacity=0.85,                    line=dict(color=text_color, width=0.6),                ),                name=str(name),                showlegend=False,                hoverinfo="skip",            )        )    # 中心节点（每个分组一个，位于各自子节点的平均角度上）
    if centre_thetas:
        names = list(centre_thetas)
        fig.add_trace(            go.Scatterpolar(                r=[LINK_INNER] * len(names),                theta=[centre_thetas[name] for name in names],                mode="markers+text",                marker=dict(                    size=centre_size,                    color=[type_colors.get(name, link_color) for name in names],                    symbol="circle",                    opacity=0.75,                    line=dict(color=text_color, width=0.8),                ),                text=names,                textposition="middle center",                textfont=dict(size=max(9, min(16, int(centre_size / 2))), color="#000000", ),                showlegend=False,                hovertemplate="%{text}<extra></extra>",            )        )    # ---- legend entries for the three numeric layers ---------------------
    if show_legend:
        for label, color in (            (RING_LABELS["mid"], mid_scale[1]),            (RING_LABELS["outer"], out_scale[1]),            (RING_LABELS["bar"], bar_color),        ):
            fig.add_trace(                go.Scatterpolar(                    r=[None],                    theta=[None],                    mode="markers",                    marker=dict(size=10, symbol="square", color=color),                    name=label,                    showlegend=True,                    hoverinfo="skip",                )            )
            trace_budget_used += 1
    title_text = st.session_state.get("circle_title", "CircleViz") or ""
    fig.update_layout(        width=780,        height=780,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        margin=dict(l=40, r=40, t=60 if title_text else 30, b=40),        font=dict(color=text_color),        showlegend=show_legend,        legend=dict(            orientation="v",            x=1.02,            xanchor="left",            y=1,            bgcolor="rgba(0,0,0,0)",            font=dict(size=11, color=text_color),        ),        polar=dict(            bgcolor=theme.get("bg", "#f5f7fb"),            radialaxis=dict(visible=False, range=[0.0, r_max * 1.08]),            angularaxis=dict(visible=False, direction="clockwise", rotation=90),        ),    )
    if title_text:
        fig.update_layout(title=dict(text=title_text, font=dict(size=17, color=text_color)))
    preview = work[list(EXPECTED_COLUMNS) + ["type"]].copy()
    group_counts = work["type"].value_counts()
    breakdown = " / ".join(f"{name} {count}" for name, count in group_counts.items())
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"CircleViz 就绪：{n_items} 行；{len(group_counts)} 个中心（{breakdown}）；"        f"{len(inner_categories)} 个内环类别；4 层环 + 网络（{len(fig.data)} 条 trace）"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render