"""UpSet Plot — set-intersection visualisation (architecture §3.9).

Three-panel ``make_subplots`` layout:

* (1,2) intersection size bars
* (2,1) per-set totals (horizontal bars)
* (2,2) membership dot matrix (grey background dots + highlighted dots + a
  single ``lines`` trace with ``None`` gaps for the vertical connectors)

Long (``set`` / ``element``) and 0/1 wide tables are both accepted.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
UpSet Plot（集合交集图）

支持输入：
  1. 长表：set（集合名）/ element（元素名）
  2. 0/1 宽表：第 1 列为元素名，其余列名为集合名，单元格 0/1

图形语义（三面板组合）：
  - 上：每个交集组合的元素数量柱状图（默认按大小降序，Top-15）
  - 左：每个集合的元素总数（横向条）
  - 下：成员点阵矩阵，每列一个交集组合，点亮表示该集合参与此交集

可配置项：
  - 数据形态、Top-N、最小交集大小、排序方式
  - 交集柱 / 集合条 / 活跃点 / 非活跃点四色
  - 点大小、柱宽、交集数值显隐、标题

说明：
  - 最小交集大小会过滤掉「只有 1 个元素」之类的噪声组合
  - 三个面板共用同一套交集标签顺序，避免 X 轴错位
"""
LAYOUT_LONG = "长表（set/element）"
LAYOUT_WIDE = "0-1 宽表"
SORT_MODES: tuple[str, ...] = ("按交集大小降序", "按交集大小升序", "按集合组合")
_FALLBACK_COLORS: dict[str, str] = {    "upset_bar": "#3C5488",    "upset_setbar": "#8491B4",    "upset_active": "#E64B35",    "upset_inactive": "#C8CDD4",    "bg": "#f5f7fb",    "text": "#111827",}# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])
def _theme_color(key: str) -> str:
    return _theme().get(key, _FALLBACK_COLORS.get(key, "#4C78A8"))
def _load_frame() -> tuple[pd.DataFrame | None, str]:
    if st.session_state.get("upset_use_sample", True):
        try:
            path = get_sample_path("upset_genesets")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("upset_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""
def _wide_to_long(frame: pd.DataFrame) -> pd.DataFrame:
    """0/1 wide table (first column = element) → long ``set`` / ``element``."""
    if frame.shape[1] < 2:
        return pd.DataFrame(columns=["set", "element"])
    elements = frame.iloc[:, 0].astype(str).str.strip()
    records: list[dict[str, str]] = []
    for column in frame.columns[1:]:
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0)
        for element, value in zip(elements, values):
            if value > 0:
                records.append({"set": str(column).strip(), "element": element})
    return pd.DataFrame(records, columns=["set", "element"])
def _as_long(frame: pd.DataFrame, layout_mode: str) -> pd.DataFrame:
    """Normalise either layout into the long schema."""
    if layout_mode == LAYOUT_WIDE:
        return _wide_to_long(frame)
    lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
    set_col = lowered.get("set") or str(frame.columns[0])
    element_col = lowered.get("element") or str(frame.columns[1])
    work = pd.DataFrame(        {            "set": frame[set_col].astype(str).str.strip(),            "element": frame[element_col].astype(str).str.strip(),        }    )
    return work[(work["set"] != "") & (work["element"] != "")]
def _intersection_table(long_frame: pd.DataFrame, min_size: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(combinations, set_sizes)`` sorted by descending intersection size."""
    memberships = long_frame.groupby("element")["set"].apply(frozenset)
    counts = memberships.value_counts()
    set_sizes = (        long_frame.groupby("set")["element"].nunique().sort_values(ascending=False)    )
    records = []
    for combination, size in counts.items():
        if len(combination) < 1 or size < min_size:
            continue
        records.append(            {                "combination": combination,                "label": " & ".join(sorted(combination)),                "size": int(size),                "degree": len(combination),            }        )
    combinations = pd.DataFrame(records, columns=["combination", "label", "size", "degree"])
    return combinations, set_sizes.reset_index().rename(columns={"element": "size"})# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("upset_use_sample", ["upset_genesets"], "upset_load_sample_btn")
    if not st.session_state.get("upset_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="upset_file_upload",        )
    st.radio("数据形态", [LAYOUT_LONG, LAYOUT_WIDE], index=0, key="upset_layout_mode", horizontal=False)
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    st.markdown("### 交集")
    st.slider("Top-N 交集", 5, 30, 15, 1, key="upset_topn")
    st.slider("最小交集大小", 1, 5, 2, 1, key="upset_min_size")
    st.radio("排序", list(SORT_MODES), index=0, key="upset_sort_mode", horizontal=False)
    st.markdown("### 配色与尺寸")
    st.color_picker("交集柱色", value=_theme_color("upset_bar"), key="upset_color_bar")
    st.color_picker("集合总量条色", value=_theme_color("upset_setbar"), key="upset_color_setbar")
    st.color_picker("交集亮点色", value=_theme_color("upset_active"), key="upset_color_active")
    st.color_picker("非活跃点色", value=_theme_color("upset_inactive"), key="upset_color_inactive")
    st.slider("点大小", 5, 20, 11, 1, key="upset_point_size")
    st.slider("柱宽", 0.2, 1.0, 0.6, 0.05, key="upset_bar_width")
    st.checkbox("显示交集数值", value=True, key="upset_show_count")
    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="upset_add_title")
    if st.session_state.get("upset_add_title", False):
        st.text_input("图形标题", "UpSet Plot", key="upset_title")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    layout_mode = st.session_state.get("upset_layout_mode", LAYOUT_LONG)
    long_frame = _as_long(frame, layout_mode)
    if long_frame.empty:
        return None, None, "没有可用的集合/元素数据。", HELP_TEXT
    min_size = int(st.session_state.get("upset_min_size", 2))
    topn = int(st.session_state.get("upset_topn", 15))
    sort_mode = st.session_state.get("upset_sort_mode", SORT_MODES[0])
    combinations, set_sizes = _intersection_table(long_frame, min_size)
    if combinations.empty:
        return None, None, "当前最小交集大小过滤后没有可绘制的交集。", HELP_TEXT
    if sort_mode == "按交集大小升序":
        combinations = combinations.sort_values(["size", "degree"], ascending=[True, True], kind="mergesort")
    elif sort_mode == "按集合组合":
        combinations = combinations.sort_values(["degree", "label"], ascending=[False, True], kind="mergesort")
    else:
        combinations = combinations.sort_values(["size", "degree"], ascending=[False, False], kind="mergesort")
    combinations = combinations.head(topn).reset_index(drop=True)
    combinations["x_index"] = range(len(combinations))
    set_order = [name for name in set_sizes["set"].tolist() if name in set(long_frame["set"])]
    set_order = list(dict.fromkeys(set_order))
    y_positions = {name: index for index, name in enumerate(set_order)}
    bar_color = st.session_state.get("upset_color_bar") or _theme_color("upset_bar")
    setbar_color = st.session_state.get("upset_color_setbar") or _theme_color("upset_setbar")
    active_color = st.session_state.get("upset_color_active") or _theme_color("upset_active")
    inactive_color = st.session_state.get("upset_color_inactive") or _theme_color("upset_inactive")
    point_size = int(st.session_state.get("upset_point_size", 11))
    bar_width = float(st.session_state.get("upset_bar_width", 0.6))
    show_count = bool(st.session_state.get("upset_show_count", True))
    add_title = bool(st.session_state.get("upset_add_title", False))
    title = (st.session_state.get("upset_title") or "UpSet Plot") if add_title else ""
    text_color = theme.get("text", "#111827")
    labels = combinations["label"].tolist()
    fig = make_subplots(        rows=2,        cols=2,        row_heights=[0.62, 0.38],        column_widths=[0.28, 0.72],        shared_xaxes="columns",        shared_yaxes="rows",        vertical_spacing=0.04,        horizontal_spacing=0.04,    )    # ---- (1,2) intersection bars -----------------------------------------
    fig.add_trace(        go.Bar(            x=labels,            y=combinations["size"],            marker=dict(color=bar_color),            width=bar_width,            name="交集大小",            showlegend=False,            text=combinations["size"] if show_count else None,            textposition="outside",            textfont=dict(size=10, color=text_color),            cliponaxis=False,            hovertemplate="%{x}<br>%{y} 个元素<extra></extra>",        ),        row=1,        col=2,    )    # ---- (2,1) per-set totals --------------------------------------------
    set_totals = set_sizes.set_index("set").reindex(set_order).fillna(0)
    fig.add_trace(        go.Bar(            x=set_totals["size"],            y=set_order,            orientation="h",            marker=dict(color=setbar_color),            name="集合总量",            showlegend=False,            hovertemplate="%{y}: %{x} 个元素<extra></extra>",        ),        row=2,        col=1,    )    # ---- (2,2) membership matrix -----------------------------------------
    background_x: list[str] = []
    background_y: list[str] = []
    active_x: list[str] = []
    active_y: list[str] = []
    connector_x: list[float | None] = []
    connector_y: list[str | None] = []
    for _, row in combinations.iterrows():
        label = row["label"]
        members = sorted(row["combination"], key=lambda name: y_positions.get(name, 99))
        member_set = set(members)
        for name in set_order:
            background_x.append(label)
            background_y.append(name)
            if name in member_set:
                active_x.append(label)
                active_y.append(name)
        if len(members) > 1:
            connector_x.extend([label] * len(members) + [None])
            connector_y.extend(members + [None])
    fig.add_trace(        go.Scatter(            x=background_x,            y=background_y,            mode="markers",            marker=dict(size=point_size - 2, color=inactive_color),            name="非活跃",            showlegend=False,            hoverinfo="skip",        ),        row=2,        col=2,    )
    fig.add_trace(        go.Scatter(            x=connector_x,            y=connector_y,            mode="lines",            line=dict(color=active_color, width=max(1.0, point_size / 6.0)),            showlegend=False,            hoverinfo="skip",        ),        row=2,        col=2,    )
    fig.add_trace(        go.Scatter(            x=active_x,            y=active_y,            mode="markers",            marker=dict(size=point_size, color=active_color),            name="活跃集合",            showlegend=False,            hovertemplate="%{x}<br>%{y}<extra></extra>",        ),        row=2,        col=2,    )    # ---- axes -------------------------------------------------------------
    fig.update_xaxes(        categoryorder="array",        categoryarray=labels,        tickangle=-45,        tickfont=dict(size=8, color=text_color),        row=2,        col=2,    )
    fig.update_xaxes(categoryorder="array", categoryarray=labels, showticklabels=False, row=1, col=2)
    fig.update_yaxes(tickfont=dict(size=10, color=text_color), row=2, col=1)
    fig.update_yaxes(        categoryorder="array",        categoryarray=set_order,        autorange="reversed",        tickfont=dict(size=10, color=text_color),        row=2,        col=2,    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=False)
    fig.update_yaxes(title_text="Intersection size", row=1, col=2)
    fig.update_yaxes(title_text="Set size", row=2, col=1)
    fig.update_layout(        height=620,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        font=dict(color=text_color),        margin=dict(l=110, r=30, t=60 if title else 30, b=170),        bargap=1.0 - bar_width,        showlegend=False,    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    membership = long_frame[long_frame["set"].isin(set_order)].reset_index(drop=True)
    data = {"membership": membership, "sets": set_sizes.reset_index(drop=True)}
    shared["last_plotly"] = fig
    shared["data"] = data
    status = (        f"UpSet 就绪：{len(set_order)} 个集合 / {long_frame['element'].nunique()} 个元素；"        f"展示 {len(combinations)} 个交集（最大 {int(combinations['size'].max())} 个元素）"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, data, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render