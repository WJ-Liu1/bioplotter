"""Grouped Matrix Plotting — native Plotly rewrite of the hand-written SVG app.

Implements architecture doc §3.2.

The original app (3823 lines in one Vue component) drew a *categorical matrix dot
plot*: row entities grouped on the Y axis, classification columns on the X axis,
each cell rendered as ``shape + fill + stroke`` for one of three categories
(``Known`` / ``Novel_Annotated`` / ``Novel_Not_Annotated``), with empty cells
allowed.

Rewrite strategy: **one ``go.Scatter`` per category** (never one trace per cell),
``add_shape`` for the group colour bars / grid / outer frame, and ``add_annotation``
for the rotated group names, the row labels and the column headers.

Sample data: ``gmp_matrix.csv`` — 6 groups / 22 viruses / 8 segments = 176 long
rows (architecture §4.2).

Key naming follows §8.2: column mappings are ``gmp_<semantic>_col`` and no
non-colour key contains the ``color/fill/edge/line/bg/reg`` substrings.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from app.core.io_utils import read_table
from app.core.palettes import GMP_GROUP_COLORS
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
Grouped Matrix Plotting（原生分组分类矩阵点阵图）

支持输入：
  1. 长表（推荐）：row / group / column / category 四列
     - row      行实体名（如 Virus 24）
     - group    Y 轴分组（如 Group1..Group6）
     - column   X 轴分类列名（如 Seg1..Seg8）
     - category 单元格类别，可为空
  2. 宽表：第 1 列为行名，其余每列是一个 column，group 统一记为 All

图形语义：
  - Y 轴按 group 分组，左侧绘制分组色条 + 分组名，右侧为行标签
  - X 轴为分类列，每格一个符号，形状与填充色由 category 决定
  - 空类别不画符号，只保留底色

可配置项：
  - 三个类别的形状与颜色、空值底色、边框色
  - 符号大小、字号、分组标签列宽、画布宽高
  - 类别图例 / 分组图例开关、双线外框开关、网格开关
  - 图形标题、X 轴标题、Y 轴标题
  - 图形标题、X 轴标题、Y 轴标题

说明：
  - 每个类别只使用 1 条 trace（176 格不会退化成 176 条 trace）
  - 分组色条颜色按分组序号从内置色板取色
  - 原版 20+ 折叠面板的逐元素取色收敛为「类别色 ×3 + 空值 + 边框」
  - 原版右侧逐格可编辑数据表改为「数据预览 + 示例数据下载」
"""
LAYOUT_LONG = "长表（row/group/column/category）"
LAYOUT_WIDE = "宽表（第 1 列为行名）"
ALIASES: dict[str, tuple[str, ...]] = {    "row": ("row", "virus", "name", "entity", "rowname", "row_name"),    "group": ("group", "ygroup", "y_group", "y_axis_group", "cluster"),    "column": ("column", "col", "seg", "segment", "x"),    "category": ("category", "cat", "type", "value", "annotation", "class"),}
DIMENSION_LABELS: dict[str, str] = {    "row": "行实体列（row）",    "group": "Y 轴分组列（group）",    "column": "X 轴列名列（column）",    "category": "类别列（category）",}
SYMBOL_OPTIONS: tuple[str, ...] = (    "circle",    "square",    "star",    "triangle-up",    "triangle-down",    "diamond",)
SYMBOL_LABELS: dict[str, str] = {    "circle": "圆形",    "square": "方形",    "star": "星形",    "triangle-up": "上三角",    "triangle-down": "下三角",    "diamond": "菱形",}
DEFAULT_CATEGORIES: tuple[str, str, str] = (    "Known",    "Novel_Annotated",    "Novel_Not_Annotated",)
CAT_COLOR_KEYS: tuple[str, str, str] = ("gmp_cat_color_1", "gmp_cat_color_2", "gmp_cat_color_3")
CAT_SYMBOL_KEYS: tuple[str, str, str] = ("gmp_cat_symbol_1", "gmp_cat_symbol_2", "gmp_cat_symbol_3")# 分组色块：低饱和 SCI 六色（来自 palettes.GMP_GROUP_COLORS，超出循环复用）
GROUP_PALETTE: tuple[str, ...] = GMP_GROUP_COLORS
_FALLBACK_COLORS: dict[str, str] = {    "gmp_cat1": "#FFC9F2",    "gmp_cat2": "#B8ECFF",    "gmp_cat3": "#B6FCBF",    "gmp_empty": "#FFFFFF",    "gmp_border": "#D0D7DE",    "bg": "#f5f7fb",    "text": "#111827",}
_EMPTY_TOKENS = {"", "nan", "none", "na", "null", "无"}# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])
def _theme_color(key: str) -> str:
    """Theme colour with a module-local fallback (arch §3.0)."""
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
    if st.session_state.get("gmp_use_sample", True):
        try:
            path = get_sample_path("gmp_matrix")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("gmp_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""
def _detect_columns(frame: pd.DataFrame) -> dict[str, str]:
    lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
    resolved: dict[str, str] = {}
    used: set[str] = set()
    for dimension, aliases in ALIASES.items():
        for alias in aliases:
            candidate = lowered.get(alias)
            if candidate is not None and candidate not in used:
                resolved[dimension] = candidate
                used.add(candidate)
                break
    return resolved
def _contrast_text(hex_color: str) -> str:
    """浅色块用深字、深色块用白字（按相对亮度判断）。"""
    raw = hex_color.lstrip("#")
    try:
        channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    except (ValueError, IndexError):
        return "#111827"
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#111827" if luminance > 0.40 else "#FFFFFF"
def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip().lower() in _EMPTY_TOKENS
def _default_symbol_for(category: str, index: int) -> str:
    """Original app defaults: Known → star, Novel(Annotated) → square, else circle."""
    key = str(category).strip().lower().replace(" ", "_")    # "annotated" itself contains the letters "not", so match the negative form first.
    if "not_annotated" in key or key.endswith("_not"):
        return "circle"
    if "annotated" in key:
        return "square"
    if "known" in key:
        return "star"
    return ("star", "square", "circle")[index % 3]
def _ordered_categories(observed: list[str]) -> list[str]:
    """Canonical order shared by ``controls`` and ``build`` so colour slots line up."""
    ordered = [name for name in DEFAULT_CATEGORIES if name in observed]
    ordered.extend(name for name in observed if name not in ordered)
    return ordered
def _wide_to_long(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert a wide matrix (first column = row name) into the long schema."""
    if frame.shape[1] < 2:
        return pd.DataFrame(columns=["row", "group", "column", "category"])
    row_names = frame.iloc[:, 0].astype(str).str.strip()
    records: list[dict[str, str]] = []
    for column in frame.columns[1:]:
        for row_name, value in zip(row_names, frame[column]):
            text = "" if pd.isna(value) else str(value).strip()
            records.append(                {                    "row": row_name,                    "group": "All",                    "column": str(column).strip(),                    "category": "" if text.lower() in _EMPTY_TOKENS else text,                }            )
    return pd.DataFrame(records)# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("gmp_use_sample", ["gmp_matrix"], "gmp_load_sample_btn")
    if not st.session_state.get("gmp_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="gmp_file_upload",        )
    st.radio("数据形态", [LAYOUT_LONG, LAYOUT_WIDE], index=0, key="gmp_layout_mode", horizontal=True)
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        st.text_input("图形标题", "Grouped Matrix Plot", key="gmp_title")
        return
    layout_mode = st.session_state.get("gmp_layout_mode", LAYOUT_LONG)
    long_frame = _wide_to_long(frame) if layout_mode == LAYOUT_WIDE else frame
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    all_cols = [str(c) for c in long_frame.columns]
    detected = _detect_columns(long_frame)
    st.markdown("### 列映射")
    for dimension in ("row", "group", "column", "category"):
        default = detected.get(dimension, all_cols[0])
        _pick(            DIMENSION_LABELS[dimension],            all_cols,            f"gmp_{dimension}_col",            all_cols.index(default) if default in all_cols else 0,        )
    st.markdown("### 类别形状与颜色")
    observed: list[str] = []
    category_col = st.session_state.get("gmp_category_col")
    if category_col in long_frame.columns:
        observed = [            str(value)            for value in pd.unique(long_frame[category_col].astype(str))            if not _is_empty(value)        ]
    categories = _ordered_categories(observed)[:3] if observed else list(DEFAULT_CATEGORIES)
    for index, label in enumerate(categories):
        symbol_key = CAT_SYMBOL_KEYS[index]
        st.session_state.setdefault(symbol_key, _default_symbol_for(label, index))
        if st.session_state[symbol_key] not in SYMBOL_OPTIONS:
            st.session_state[symbol_key] = _default_symbol_for(label, index)
        st.markdown(f"**{label}**")
        st.selectbox(            "形状",            options=list(SYMBOL_OPTIONS),            format_func=lambda value: SYMBOL_LABELS.get(value, value),            key=symbol_key,        )
        st.color_picker("填充色", value=_theme_color(f"gmp_cat{index + 1}"), key=CAT_COLOR_KEYS[index])
    st.color_picker("空值底色", value=_theme_color("gmp_empty"), key="gmp_empty_color")
    st.color_picker("边框颜色", value=_theme_color("gmp_border"), key="gmp_border_color")
    st.markdown("### 标题")
    st.text_input("图形标题", "Grouped Matrix Plot", key="gmp_title")
    st.text_input("X 轴标题", "Gene Segments", key="gmp_xaxis_title")
    st.text_input("Y 轴标题", "Virus", key="gmp_yaxis_title")
def advanced_controls(shared: dict) -> None:
    """Grouped Matrix 的高级参数：布局与图例开关。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.markdown("### 布局与样式")
    st.slider("符号大小", 6, 22, 11, 1, key="gmp_marker_size")
    st.slider("字号", 8, 18, 11, 1, key="gmp_font_size")
    st.slider("分组标签列宽 (px)", 60, 240, 120, 5, key="gmp_group_col_width")
    st.number_input("画布宽度 (px)", min_value=400, max_value=2000, value=750, step=50, key="gmp_canvas_width")
    st.number_input("画布高度 (px)", min_value=300, max_value=2000, value=620, step=20, key="gmp_canvas_height")
    st.checkbox("双线外框", value=False, key="gmp_double_border")
    st.checkbox("显示网格线", value=True, key="gmp_show_grid")
    st.checkbox("显示类别图例", value=True, key="gmp_show_cat_legend")
    st.checkbox("显示分组图例", value=True, key="gmp_show_group_legend")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    layout_mode = st.session_state.get("gmp_layout_mode", LAYOUT_LONG)
    long_frame = _wide_to_long(frame) if layout_mode == LAYOUT_WIDE else frame
    detected = _detect_columns(long_frame)
    columns: dict[str, str] = {}
    for dimension in ("row", "group", "column", "category"):
        chosen = st.session_state.get(f"gmp_{dimension}_col") or detected.get(dimension)
        if not chosen or chosen not in long_frame.columns:
            return (                None,                None,                f"缺少必需列：{DIMENSION_LABELS[dimension]}。当前列：{', '.join(map(str, long_frame.columns))}",                HELP_TEXT,            )
        columns[dimension] = chosen
    work = long_frame.copy()
    for dimension in ("row", "group", "column"):
        work[columns[dimension]] = work[columns[dimension]].astype(str).str.strip()
    work = work[        (work[columns["row"]] != "")        & (work[columns["group"]] != "")        & (work[columns["column"]] != "")    ]
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT
    work["_gmp_category"] = work[columns["category"]].map(        lambda value: "" if _is_empty(value) else str(value).strip()    )    # ---- ordering ---------------------------------------------------------
    group_order: list[str] = list(pd.unique(work[columns["group"]]))
    column_order: list[str] = list(pd.unique(work[columns["column"]]))
    rows_by_group = {        group: list(pd.unique(work.loc[work[columns["group"]] == group, columns["row"]]))        for group in group_order    }
    row_positions: dict[str, float] = {}
    group_blocks: list[tuple[str, float, float]] = []
    cursor = 0.0
    group_gap = 0.9
    for group in group_order:
        group_start = cursor
        for row_name in rows_by_group[group]:
            row_positions[row_name] = cursor
            cursor -= 1.0
        group_blocks.append((group, group_start + 0.5, cursor + 0.5))
        cursor -= group_gap
    y_top = 1.1
    y_bottom = cursor + group_gap + 0.5 - 0.6
    column_positions = {name: float(index) for index, name in enumerate(column_order)}    # ---- styling ----------------------------------------------------------
    marker_size = int(st.session_state.get("gmp_marker_size", 11))
    font_size = int(st.session_state.get("gmp_font_size", 11))
    label_width = int(st.session_state.get("gmp_group_col_width", 120))
    canvas_width = int(st.session_state.get("gmp_canvas_width", 750))
    canvas_height = int(st.session_state.get("gmp_canvas_height", 620))
    double_border = bool(st.session_state.get("gmp_double_border", False))
    show_grid = bool(st.session_state.get("gmp_show_grid", True))
    show_cat_legend = bool(st.session_state.get("gmp_show_cat_legend", True))
    show_group_legend = bool(st.session_state.get("gmp_show_group_legend", True))
    border_color = st.session_state.get("gmp_border_color") or _theme_color("gmp_border")
    empty_color = st.session_state.get("gmp_empty_color") or _theme_color("gmp_empty")
    text_color = theme.get("text", "#111827")
    observed_categories = [value for value in pd.unique(work["_gmp_category"]) if value]
    category_order = _ordered_categories(observed_categories)
    category_style: dict[str, dict[str, str]] = {}
    for index, name in enumerate(category_order):
        slot = index % 3
        symbol = st.session_state.get(CAT_SYMBOL_KEYS[slot], _default_symbol_for(name, slot))
        if symbol not in SYMBOL_OPTIONS:
            symbol = "circle"
        color = st.session_state.get(CAT_COLOR_KEYS[slot]) or _theme_color(f"gmp_cat{slot + 1}")
        category_style[name] = {"symbol": symbol, "color": color}
    group_colors = {        group: GROUP_PALETTE[index % len(GROUP_PALETTE)] for index, group in enumerate(group_order)    }    # label gutter expressed in data units
    gutter = max(2.2, label_width / 55.0)
    block_x1 = -gutter
    block_x0 = -gutter - 0.75
    row_label_x = -gutter + 0.12
    matrix_left = -0.5
    matrix_right = float(len(column_order)) - 0.5
    fig = go.Figure()    # ---- empty-cell backdrop ---------------------------------------------
    fig.add_shape(        type="rect",        x0=matrix_left,        x1=matrix_right,        y0=y_bottom,        y1=y_top,        line=dict(width=0),        fillcolor=empty_color,        layer="below",    )    # ---- one trace per category (never one per cell) ---------------------
    for category in category_order:
        subset = work[work["_gmp_category"] == category]
        if subset.empty:
            continue
        style = category_style[category]
        fig.add_trace(            go.Scatter(                x=[column_positions[name] for name in subset[columns["column"]]],                y=[row_positions[name] for name in subset[columns["row"]]],                mode="markers",                marker=dict(                    symbol=style["symbol"],                    size=marker_size,                    color=style["color"],                    line=dict(color=text_color, width=1),                ),                name=category,                showlegend=show_cat_legend,                customdata=[                    [row_name, column_name]                    for row_name, column_name in zip(subset[columns["row"]], subset[columns["column"]])                ],                hovertemplate=(                    f"{columns['row']}: %{{customdata[0]}}<br>"                    f"{columns['column']}: %{{customdata[1]}}<br>"                    f"{columns['category']}: {category}<extra></extra>"                ),            )        )    # ---- group colour bars + group names ---------------------------------
    for group, top, bottom in group_blocks:
        fig.add_shape(            type="rect",            x0=block_x0,            x1=block_x1,            y0=bottom,            y1=top,            line=dict(color=border_color, width=1),            fillcolor=group_colors[group],            layer="below",        )
        fig.add_annotation(            x=(block_x0 + block_x1) / 2.0,            y=(top + bottom) / 2.0,            text=str(group),            showarrow=False,            textangle=-90,            font=dict(size=font_size, color=_contrast_text(group_colors[group])),        )    # ---- row labels -------------------------------------------------------
    for row_name, y in row_positions.items():
        fig.add_annotation(            x=row_label_x,            y=y,            text=str(row_name),            showarrow=False,            xanchor="left",            yanchor="middle",            font=dict(size=font_size, color=text_color),        )    # ---- column headers ---------------------------------------------------
    for column_name in column_order:
        fig.add_annotation(            x=column_positions[column_name],            y=y_top + 0.55,            text=str(column_name),            showarrow=False,            xanchor="center",            yanchor="bottom",            font=dict(size=font_size, color=text_color),        )    # ---- grid -------------------------------------------------------------
    if show_grid:
        for column_name in column_order[:-1]:
            x = column_positions[column_name] + 0.5
            fig.add_shape(                type="line",                x0=x,                x1=x,                y0=y_bottom,                y1=y_top,                line=dict(color=border_color, width=0.6, dash="dot"),                layer="below",            )
        for index, group in enumerate(group_order):
            rows_in_group = rows_by_group[group]
            for row_name in rows_in_group[:-1]:
                y = row_positions[row_name] - 0.5
                fig.add_shape(                    type="line",                    x0=matrix_left,                    x1=matrix_right,                    y0=y,                    y1=y,                    line=dict(color=border_color, width=0.6, dash="dot"),                    layer="below",                )
            if index < len(group_order) - 1:
                y = row_positions[rows_in_group[-1]] - 0.5 - group_gap / 2.0
                fig.add_shape(                    type="line",                    x0=block_x0,                    x1=matrix_right,                    y0=y,                    y1=y,                    line=dict(color=border_color, width=1.2),                    layer="below",                )    # ---- outer frame (single or double) ----------------------------------
    offsets = [0.0, 0.12] if double_border else [0.0]
    for offset in offsets:
        fig.add_shape(            type="rect",            x0=block_x0 - offset,            x1=matrix_right + offset,            y0=y_bottom - offset,            y1=y_top + offset,            line=dict(color=border_color, width=1.4 if offset == 0.0 else 0.8),            fillcolor="rgba(0,0,0,0)",            layer="above",        )    # ---- group legend (dummy markers, capped to keep the trace count low) -
    if show_group_legend and len(group_order) <= 8:
        for group in group_order:
            fig.add_trace(                go.Scatter(                    x=[None],                    y=[None],                    mode="markers",                    marker=dict(                        symbol="square",                        size=10,                        color=group_colors[group],                        line=dict(color=border_color, width=1),                    ),                    name=str(group),                    showlegend=True,                    hoverinfo="skip",                )            )
    title_text = st.session_state.get("gmp_title", "Grouped Matrix Plot") or ""
    x_title = st.session_state.get("gmp_xaxis_title", "Gene Segments") or ""
    y_title = st.session_state.get("gmp_yaxis_title", "Virus") or ""
    fig.update_layout(        width=canvas_width,        height=canvas_height,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        margin=dict(l=20, r=20, t=60 if title_text else 30, b=80),        legend=dict(            orientation="h",            y=-0.13,            x=0.5,            xanchor="center",            bgcolor="rgba(0,0,0,0)",            font=dict(size=font_size, color=text_color),            title=dict(text=""),        ),        showlegend=show_cat_legend or show_group_legend,        font=dict(color=text_color, size=font_size),        hovermode="closest",    )
    if title_text:
        fig.update_layout(title=dict(text=title_text, font=dict(size=font_size + 6, color=text_color)))
    fig.update_xaxes(        title_text=x_title,        range=[block_x0 - 0.4, matrix_right + 0.4],        showgrid=False,        zeroline=False,        showticklabels=False,        showline=False,        ticks="",        title_font=dict(size=font_size + 4, color=text_color),    )
    fig.update_yaxes(        title_text=y_title,        range=[y_bottom - 0.4, y_top + 1.25],        showgrid=False,        zeroline=False,        showticklabels=False,        showline=False,        ticks="",        title_font=dict(size=font_size + 4, color=text_color),    )
    preview = work.drop(columns=["_gmp_category"]).reset_index(drop=True)
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"Grouped Matrix Plot 就绪：{len(pd.unique(work[columns['row']]))} 行 × "        f"{len(column_order)} 列；{len(group_order)} 个分组；{len(category_order)} 个类别；"        f"{len(work)} 条长表记录"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render