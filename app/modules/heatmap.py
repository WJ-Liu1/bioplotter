"""Heatmap — expression matrix heatmap (architecture §3.8).

Row z-score → optional ``scipy.cluster.hierarchy`` re-ordering (leaves only, no
dendrogram) → a single ``go.Heatmap``; optional row / column group strips are
attached with a 2x2 ``make_subplots`` grid.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from plotly.colors import get_colorscale
from plotly.subplots import make_subplots
from app.core.io_utils import read_table
from app.core.palettes import palette_for
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
Heatmap（表达矩阵热图）

支持输入（宽表 CSV / TSV / TXT / XLSX）：
  - 第 1 列为行名（基因），其余列为数值
  - 可选：行分组列（用下拉框指定），列分组（按列名前缀自动识别）

算法：
  - 按行 z-score（可切换「不处理」/「log2」）
  - 可选行 / 列层次聚类：scipy linkage + leaves_list 只做重排序，不画树
  - 单 go.Heatmap 出图；行列分组条用 2×2 子图贴在侧边

可配置项：
  - 行分组列、列分组前缀、标准化方式
  - 行 / 列聚类开关、聚类方法（average/complete/single/ward）、距离度量
  - 色阶方案或自定义低/中/高配色、色阶中点
  - 行列标签显隐与字号、色标开关、标题

说明：
  - 不做 dendrogram（架构明确 P2）
  - ward 方法只能配合 euclidean 距离，选择其他组合时自动回退到 average
  - log2 模式对 0 与负值按 1e-300 截断，避免 log 出现无穷
"""
NO_GROUP = "(无)"
SCALE_MODES: tuple[str, ...] = ("按行 z-score", "不处理", "log2")
PALETTE_CUSTOM = "自定义（低 / 中 / 高）"
PALETTE_OPTIONS: tuple[str, ...] = (PALETTE_CUSTOM, "RdBu_r", "Viridis", "Plasma", "Cividis")
CLUSTER_METHODS: tuple[str, ...] = ("average", "complete", "single", "ward")
CLUSTER_METRICS: tuple[str, ...] = ("euclidean", "correlation", "cityblock")
MAX_HEATMAP_CELLS = 400_000
_FALLBACK_COLORS: dict[str, str] = {    "heatmap_low": "#4575B4",    "heatmap_mid": "#FFFFBF",    "heatmap_high": "#D73027",    "bg": "#f5f7fb",    "text": "#111827",}# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])
def _theme_color(key: str) -> str:
    return _theme().get(key, _FALLBACK_COLORS.get(key, "#4C78A8"))
def _pick(label: str, options: list[str], key: str, index: int = 0):
    if not options:
        options = ["—"]
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]
    if key in st.session_state:
        return st.selectbox(label, options, key=key)
    return st.selectbox(label, options, index=min(index, len(options) - 1), key=key)
def _load_frame() -> tuple[pd.DataFrame | None, str]:
    if st.session_state.get("heatmap_use_sample", True):
        try:
            path = get_sample_path("heatmap_expression")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("heatmap_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""
def _split_matrix(frame: pd.DataFrame, row_group_col: str) -> tuple[pd.Series, pd.DataFrame, pd.Series | None]:
    row_names = frame.iloc[:, 0].astype(str).str.strip()
    row_groups = frame[row_group_col].astype(str).str.strip() if row_group_col else None
    excluded = {str(frame.columns[0])}
    if row_group_col:
        excluded.add(str(row_group_col))
    matrix = frame[[c for c in frame.columns if str(c) not in excluded]].copy()
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    matrix = matrix.dropna(axis=1, how="all").fillna(0.0)
    matrix.index = row_names
    return row_names, matrix, row_groups
def _standardise(matrix: pd.DataFrame, scale_mode: str) -> pd.DataFrame:
    if scale_mode == "log2":
        return np.log2(matrix.clip(lower=1e-300))
    if scale_mode == "不处理":
        return matrix
    mean = matrix.mean(axis=1)
    std = matrix.std(axis=1, ddof=1) + 1e-12
    return matrix.sub(mean, axis=0).div(std, axis=0)
def _cluster_order(matrix: pd.DataFrame, method: str, metric: str) -> list[int] | None:
    """Re-order rows/columns with scipy; returns positional indices or ``None``."""
    if matrix.shape[0] < 3:
        return None
    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
    except Exception:
  # pragma: no cover - scipy is a declared dependency
        return None
    if method == "ward" and metric != "euclidean":
        method = "average"
    values = matrix.to_numpy(dtype=float)
    if not np.all(np.isfinite(values)):
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    try:
        link = linkage(values, method=method, metric=metric)
        return [int(index) for index in leaves_list(link)]
    except Exception:
        return None
def _group_codes(groups: pd.Series, order: list[int] | None = None) -> list[int]:
    values = groups.astype(str).tolist()
    if order is not None and len(order) == len(values):
        values = [values[index] for index in order]
    unique = list(dict.fromkeys(values))
    index_map = {value: position for position, value in enumerate(unique)}
    return [index_map[value] for value in values]
def _column_group_prefixes(columns: list[str], prefix: str) -> list[str] | None:
    if not prefix:
        return None
    prefixes = []
    found = False
    for name in columns:
        if prefix in str(name):
            found = True
            prefixes.append(str(name).split(prefix)[0] or str(name))
        else:
            prefixes.append(str(name))
    return prefixes if found else None# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def _tick_step(count: int, budget: int = 30) -> int:
    """刻度抽稀步长：大于 budget 个标签时按倍数跳着显示，避免糊成一片。"""
    if count <= budget:
        return 1
    return max(1, math.ceil(count / budget))
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("heatmap_use_sample", ["heatmap_expression"], "heatmap_load_sample_btn")
    if not st.session_state.get("heatmap_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="heatmap_file_upload",        )
        st.caption("宽表：第 1 列为行名（基因），其余为数值列。")
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    all_cols = [str(c) for c in frame.columns]
    group_options = [NO_GROUP] + all_cols
    lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
    default_group = lowered.get("group", NO_GROUP)
    st.markdown("### 分组与标准化")
    _pick(        "行分组列",        group_options,        "heatmap_row_group_col",        group_options.index(default_group) if default_group in group_options else 0,    )
    st.text_input("列分组前缀（按列名自动识别，留空则不用）", "", key="heatmap_col_group_prefix")
    st.radio("标准化", list(SCALE_MODES), index=0, key="heatmap_scale_mode")
    st.markdown("### 配色")
    st.selectbox("色阶方案", list(PALETTE_OPTIONS), index=0, key="heatmap_palette")
    st.color_picker("低值色", value=_theme_color("heatmap_low"), key="heatmap_color_low")
    st.color_picker("中值色", value=_theme_color("heatmap_mid"), key="heatmap_color_mid")
    st.color_picker("高值色", value=_theme_color("heatmap_high"), key="heatmap_color_high")
    st.number_input("色阶中点 (zmid)", value=0.0, step=0.1, format="%.2f", key="heatmap_zmid")
    st.markdown("### 标签与色标")
    st.checkbox("显示行标签", value=True, key="heatmap_show_rowlabels")
    st.checkbox("显示列标签", value=True, key="heatmap_show_collabels")
    st.slider("标签字号", 5, 14, 10, 1, key="heatmap_label_size")
    st.checkbox("显示色标", value=True, key="heatmap_show_cbar")
    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="heatmap_add_title")
    if st.session_state.get("heatmap_add_title", False):
        st.text_input("图形标题", "Heatmap", key="heatmap_title")
def advanced_controls(shared: dict) -> None:
    """Heatmap 的高级参数：聚类只影响行列顺序，默认折叠。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.markdown("### 聚类")
    st.checkbox("行聚类", value=False, key="heatmap_cluster_rows")
    st.checkbox("列聚类", value=False, key="heatmap_cluster_cols")
    st.selectbox("聚类方法", list(CLUSTER_METHODS), index=0, key="heatmap_cluster_method")
    st.selectbox("距离度量", list(CLUSTER_METRICS), index=0, key="heatmap_cluster_metric")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def _build_colorscale(palette: str, low: str, mid: str, high: str) -> list:
    """Three-stop custom ramp, or one of Plotly's built-in named colours."""
    if palette == PALETTE_CUSTOM:
        return [[0.0, low], [0.5, mid], [1.0, high]]
    try:
        return get_colorscale(palette)
    except Exception:
        return [[0.0, low], [0.5, mid], [1.0, high]]
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    row_group_col = st.session_state.get("heatmap_row_group_col")
    if row_group_col is None:
        # No widget state yet (headless build) → fall back to name detection.
        lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
        row_group_col = lowered.get("group", NO_GROUP)
    if row_group_col == NO_GROUP or row_group_col not in frame.columns:
        row_group_col = ""
    row_names, matrix, row_groups = _split_matrix(frame, row_group_col)
    if matrix.shape[1] == 0:
        return None, None, "没有可用的数值列。", HELP_TEXT
    if matrix.shape[0] < 2:
        return None, None, "行数太少（至少需要 2 行）。", HELP_TEXT
    if matrix.shape[0] * matrix.shape[1] > MAX_HEATMAP_CELLS:
        return (            None,            None,            f"数据量过大（{matrix.shape[0] * matrix.shape[1]:,} 个单元格），"            f"已截取前 200 行以保证响应速度。",            HELP_TEXT,        )
    scale_mode = st.session_state.get("heatmap_scale_mode", SCALE_MODES[0])
    z_matrix = _standardise(matrix, scale_mode)
    cluster_method = st.session_state.get("heatmap_cluster_method", "average")
    cluster_metric = st.session_state.get("heatmap_cluster_metric", "euclidean")
    row_order = (        _cluster_order(z_matrix, cluster_method, cluster_metric)        if st.session_state.get("heatmap_cluster_rows", False)        else None    )
    col_order = (        _cluster_order(z_matrix.T, cluster_method, cluster_metric)        if st.session_state.get("heatmap_cluster_cols", False)        else None    )
    if row_order is not None:
        z_matrix = z_matrix.iloc[row_order]
        row_names = row_names.iloc[row_order]
        if row_groups is not None:
            row_groups = row_groups.iloc[row_order]
    if col_order is not None:
        z_matrix = z_matrix.iloc[:, col_order]
    columns = [str(c) for c in z_matrix.columns]
    rows = [str(value) for value in z_matrix.index]
    palette = st.session_state.get("heatmap_palette", PALETTE_CUSTOM)
    low = st.session_state.get("heatmap_color_low") or _theme_color("heatmap_low")
    mid = st.session_state.get("heatmap_color_mid") or _theme_color("heatmap_mid")
    high = st.session_state.get("heatmap_color_high") or _theme_color("heatmap_high")
    colorscale = _build_colorscale(palette, low, mid, high)
    zmid = float(st.session_state.get("heatmap_zmid", 0.0))
    label_size = int(st.session_state.get("heatmap_label_size", 10))
    show_row_labels = bool(st.session_state.get("heatmap_show_rowlabels", True))
    show_col_labels = bool(st.session_state.get("heatmap_show_collabels", True))
    show_colorbar = bool(st.session_state.get("heatmap_show_cbar", True))
    add_title = bool(st.session_state.get("heatmap_add_title", False))
    title = (st.session_state.get("heatmap_title") or "Heatmap") if add_title else ""
    text_color = theme.get("text", "#111827")
    col_prefix = st.session_state.get("heatmap_col_group_prefix", "") or ""
    col_group_labels = _column_group_prefixes(columns, col_prefix)
    heatmap_kwargs = dict(        z=z_matrix.to_numpy(dtype=float),        x=columns,        y=rows,        colorscale=colorscale,        zmid=zmid,        hovertemplate="%{y} / %{x}<br>value: %{z:.3f}<extra></extra>",        colorbar=dict(title=dict(text="z-score"), thickness=12) if show_colorbar else None,        showscale=show_colorbar,    )
    x_dtick = _tick_step(len(columns))
    y_dtick = _tick_step(len(rows), 36)
    has_row_strip = row_groups is not None
    has_col_strip = col_group_labels is not None
    if not has_row_strip and not has_col_strip:
        fig = go.Figure(go.Heatmap(**heatmap_kwargs))
        fig.update_layout(            height=max(360, min(900, 22 * len(rows) + 120)),            plot_bgcolor=theme.get("bg", "#f5f7fb"),            paper_bgcolor=theme.get("bg", "#f5f7fb"),            font=dict(color=text_color),            margin=dict(l=90, r=40, t=60 if title else 30, b=60),        )
        fig.update_xaxes(            showticklabels=show_col_labels,            tickfont=dict(size=label_size),            ticks="",            showgrid=False,            dtick=x_dtick,        )
        fig.update_yaxes(            showticklabels=show_row_labels,            tickfont=dict(size=label_size),            ticks="",            autorange="reversed",            showgrid=False,            dtick=y_dtick,        )
    else:
        row_heights = [0.02, 0.98] if has_col_strip else [1.0]
        col_widths = [0.98, 0.02] if has_row_strip else [1.0]
        fig = make_subplots(            rows=len(row_heights),            cols=len(col_widths),            row_heights=row_heights,            column_widths=col_widths,            horizontal_spacing=0.01,            vertical_spacing=0.01,        )
        main_row = len(row_heights)
        main_col = 1
        fig.add_trace(go.Heatmap(**heatmap_kwargs), row=main_row, col=main_col)
        fig.update_xaxes(            showticklabels=show_col_labels,            tickfont=dict(size=label_size),            ticks="",            showgrid=False,            dtick=x_dtick,            row=main_row,            col=main_col,        )
        fig.update_yaxes(            showticklabels=show_row_labels,            tickfont=dict(size=label_size),            ticks="",            autorange="reversed",            showgrid=False,            dtick=y_dtick,            row=main_row,            col=main_col,        )
        if has_col_strip and col_group_labels:
            col_codes = _group_codes(pd.Series(col_group_labels))
            strip_colors = list(palette_for("Heatmap"))
            fig.add_trace(                go.Heatmap(                    z=[col_codes],                    x=columns,                    y=[""],                    colorscale=_category_colorscale(len(set(col_codes)), strip_colors),                    showscale=False,                    hoverinfo="skip",                ),                row=1,                col=1,            )
            fig.update_xaxes(showticklabels=False, row=1, col=1)
            fig.update_yaxes(showticklabels=False, row=1, col=1)
        if has_row_strip and row_groups is not None:
            row_codes = _group_codes(row_groups)
            strip_colors = list(palette_for("Heatmap"))
            fig.add_trace(                go.Heatmap(                    z=[[value] for value in row_codes],                    x=[""],                    y=rows,                    colorscale=_category_colorscale(len(set(row_codes)), strip_colors),                    showscale=False,                    hoverinfo="skip",                ),                row=main_row,                col=2,            )
            fig.update_xaxes(showticklabels=False, row=main_row, col=2)
            fig.update_yaxes(showticklabels=False, autorange="reversed", row=main_row, col=2)        # 分组细条语义说明：放矩阵下方左侧，远离右侧 z-score 色标
        strip_notes: list[str] = []
        if has_row_strip and row_groups is not None:
            row_levels = [str(value) for value in pd.unique(row_groups)]
            strip_notes.append("右侧细条 = 行分组：" + " / ".join(row_levels[:6]))
        if has_col_strip and col_group_labels:
            col_levels = list(dict.fromkeys(str(value) for value in col_group_labels))
            strip_notes.append("顶部细条 = 列分组：" + " / ".join(col_levels[:6]))
        if strip_notes:
            fig.add_annotation(                text="　·　".join(strip_notes),                x=0.0,                y=-0.08 if show_col_labels else -0.045,                xref="paper",                yref="paper",                xanchor="left",                yanchor="top",                showarrow=False,                font=dict(size=9, color=theme.get("muted", "#6b7280")),            )
        fig.update_layout(            height=max(420, min(900, 22 * len(rows) + 160)),            plot_bgcolor=theme.get("bg", "#f5f7fb"),            paper_bgcolor=theme.get("bg", "#f5f7fb"),            font=dict(color=text_color),            margin=dict(l=90, r=40, t=60 if title else 30, b=88 if strip_notes else 60),        )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    preview = z_matrix.reset_index()
    preview = preview.rename(columns={preview.columns[0]: "row"})
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"Heatmap 就绪：{z_matrix.shape[0]} 行 × {z_matrix.shape[1]} 列；{scale_mode}；"        f"行聚类 {'开' if row_order is not None else '关'} / "        f"列聚类 {'开' if col_order is not None else '关'}"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, shared["data"], status, HELP_TEXT
def _category_colorscale(count: int, palette: list[str]) -> list:
    """Discrete colours → a stepped colorscale usable by a one-row Heatmap."""
    if count <= 0:
        return [[0.0, "#cccccc"], [1.0, "#cccccc"]]
    stops = []
    for index in range(count):
        color = palette[index % len(palette)]
        stops.append([index / count, color])
        stops.append([(index + 1) / count, color])
    return stops
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render