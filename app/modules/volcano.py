"""Volcano Plot — differential-expression scatter (architecture §3.6).

Three ``go.Scatter`` traces (up / down / not significant) so the legend is
clickable, ``-log10(p)`` pre-computed into a ``neg_log10_p`` column (never a
reversed log axis), threshold reference lines, and a separate ``mode="text"``
trace for the Top-N gene labels.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
Volcano Plot（火山图）

支持输入（CSV / TSV / TXT / XLSX）：
  - 必需：gene（基因名）、log2FC（数值）、pvalue（0~1）
  - 可选：padj、label（是否标注）、group（上调/下调/不显著）
  - 缺 group 时按阈值自动推断：
    log2FC > 阈值 且 p < 阈值 → 上调；log2FC < -阈值 且 p < 阈值 → 下调；其余不显著

图形语义：
  - X 轴 = log2 Fold Change，Y 轴 = -log10(p)
  - 上调 / 下调 / 不显著三色，图例可点选隐藏
  - 阈值参考线：水平线 = -log10(p 阈值)，两条竖线 = ±log2FC 阈值
  - Top-N 最显著基因标注（按 p 升序取），正 FC 标在右上、负 FC 标在左上

可配置项：
  - 列映射、log2FC 阈值、p 阈值
  - 三色配色、点大小与透明度
  - Top-N 标注数量与字号、阈值线开关
  - 标题、X / Y 轴标题

说明：
  - Y 轴为预计算的 -log10(pvalue) 列，不使用反向 log 轴
  - p 值为 0 时按 1e-300 截断，避免 log10 出现无穷
"""
_GROUP_UP = "上调"
_GROUP_DOWN = "下调"
_GROUP_NS = "不显著"
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {    "gene": ("gene", "gene_id", "id", "name", "symbol"),    "fc": ("log2fc", "log2_fc", "logfc", "fc", "foldchange", "fold_change"),    "p": ("pvalue", "p_value", "p.val", "pval", "p"),    "group": ("group", "class", "type", "direction", "status"),}
COLUMN_LABELS: dict[str, str] = {    "gene": "gene（基因名）",    "fc": "log2FC（数值）",    "p": "pvalue（0~1）",    "group": "group（可选）",}
AUTO_GROUP = "(自动推断)"
_FALLBACK_COLORS: dict[str, str] = {    "volcano_up": "#E64B35",    "volcano_down": "#4DBBD5",    "volcano_ns": "#B0B0B0",    "volcano_thr": "#6b7280",    "bg": "#f5f7fb",    "text": "#111827",}# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
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
    if st.session_state.get("volcano_use_sample", True):
        try:
            path = get_sample_path("volcano_degs")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("volcano_file_upload")
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
    for dimension, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            candidate = lowered.get(alias)
            if candidate is not None and candidate not in used:
                resolved[dimension] = candidate
                used.add(candidate)
                break
    return resolved# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("volcano_use_sample", ["volcano_degs"], "volcano_load_sample_btn")
    if not st.session_state.get("volcano_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="volcano_file_upload",        )
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        st.checkbox("添加图形标题", value=False, key="volcano_add_title")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    detected = _detect_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    group_options = [AUTO_GROUP] + all_cols
    st.markdown("### 列映射")
    for dimension in ("gene", "fc", "p"):
        default = detected.get(dimension, all_cols[0])
        _pick(            COLUMN_LABELS[dimension],            all_cols,            f"volcano_col_{dimension}",            all_cols.index(default) if default in all_cols else 0,        )
    default_group = detected.get("group", AUTO_GROUP)
    _pick(        COLUMN_LABELS["group"],        group_options,        "volcano_col_group",        group_options.index(default_group) if default_group in group_options else 0,    )
    st.markdown("### 阈值")
    st.slider("log2FC 阈值", 0.0, 5.0, 1.0, 0.1, key="volcano_fc_thr")
    st.number_input(        "p 阈值",        min_value=1e-15,        max_value=1.0,        value=0.05,        step=0.01,        format="%.4f",        key="volcano_p_thr",    )
    st.checkbox("显示阈值线", value=True, key="volcano_show_thr")
    st.markdown("### 外观")
    st.color_picker("上调颜色", value=_theme_color("volcano_up"), key="volcano_color_up")
    st.color_picker("下调颜色", value=_theme_color("volcano_down"), key="volcano_color_down")
    st.color_picker("不显著颜色", value=_theme_color("volcano_ns"), key="volcano_color_ns")
    st.slider("点大小", 2, 16, 6, 1, key="volcano_point_size")
    st.slider("点透明度", 0.1, 1.0, 0.7, 0.05, key="volcano_opacity")
    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="volcano_add_title")
    if st.session_state.get("volcano_add_title", False):
        st.text_input("图形标题", "Volcano Plot", key="volcano_title")
    st.text_input("X 轴标题", "log2 Fold Change", key="volcano_x_title")
    st.text_input("Y 轴标题", "-log10(p)", key="volcano_y_title")
def advanced_controls(shared: dict) -> None:
    """Volcano 的高级参数：基因标注数量与字号。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.markdown("### 标注")
    st.slider("Top-N 标注", 0, 50, 6, 1, key="volcano_topn")
    st.slider("标注字号", 6, 16, 9, 1, key="volcano_label_size")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    detected = _detect_columns(frame)
    columns: dict[str, str] = {}
    for dimension in ("gene", "fc", "p"):
        chosen = st.session_state.get(f"volcano_col_{dimension}") or detected.get(dimension)
        if not chosen or chosen not in frame.columns:
            return (                None,                None,                f"缺少必需列：{COLUMN_LABELS[dimension]}。当前列：{', '.join(map(str, frame.columns))}",                HELP_TEXT,            )
        columns[dimension] = chosen
    group_col = st.session_state.get("volcano_col_group", AUTO_GROUP)
    if group_col == AUTO_GROUP or group_col not in frame.columns:
        group_col = ""
    fc_thr = float(st.session_state.get("volcano_fc_thr", 1.0))
    p_thr = float(st.session_state.get("volcano_p_thr", 0.05))
    if p_thr <= 0:
        p_thr = 1e-15
    work = pd.DataFrame(        {            "gene": frame[columns["gene"]].astype(str).str.strip(),            "log2FC": pd.to_numeric(frame[columns["fc"]], errors="coerce"),            "pvalue": pd.to_numeric(frame[columns["p"]], errors="coerce"),        }    )
    work = work.dropna(subset=["log2FC", "pvalue"])
    work = work[work["gene"] != ""]
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT    # arch §8.4: never let 0 into log10
    work["pvalue"] = work["pvalue"].clip(1e-300, 1.0)
    work["neg_log10_p"] = -np.log10(work["pvalue"])
    if group_col:
        raw_groups = frame.loc[work.index, group_col].astype(str).str.strip()
        work["group"] = raw_groups.to_numpy()
        normalised = work["group"].str.lower()
        work["_bucket"] = np.select(            [                normalised.isin({"up", "upregulated", "上调", "up_regulated"}),                normalised.isin({"down", "downregulated", "下调", "down_regulated"}),            ],            [_GROUP_UP, _GROUP_DOWN],            default=_GROUP_NS,        )
    else:
        work["group"] = np.select(            [                (work["log2FC"] > fc_thr) & (work["pvalue"] < p_thr),                (work["log2FC"] < -fc_thr) & (work["pvalue"] < p_thr),            ],            [_GROUP_UP, _GROUP_DOWN],            default=_GROUP_NS,        )
        work["_bucket"] = work["group"]
    point_size = int(st.session_state.get("volcano_point_size", 6))
    opacity = float(st.session_state.get("volcano_opacity", 0.7))
    topn = int(st.session_state.get("volcano_topn", 6))
    label_size = int(st.session_state.get("volcano_label_size", 9))
    show_thr = bool(st.session_state.get("volcano_show_thr", True))
    add_title = bool(st.session_state.get("volcano_add_title", False))
    title = (st.session_state.get("volcano_title") or "Volcano Plot") if add_title else ""
    x_title = st.session_state.get("volcano_x_title", "log2 Fold Change") or ""
    y_title = st.session_state.get("volcano_y_title", "-log10(p)") or ""
    text_color = theme.get("text", "#111827")    # 绘制顺序即堆叠顺序：不显著垫底，上/下调在上层，避免灰点盖住显著点
    bucket_styles = (        (_GROUP_NS, st.session_state.get("volcano_color_ns") or _theme_color("volcano_ns")),        (_GROUP_UP, st.session_state.get("volcano_color_up") or _theme_color("volcano_up")),        (_GROUP_DOWN, st.session_state.get("volcano_color_down") or _theme_color("volcano_down")),    )
    fig = go.Figure()
    for label, color in bucket_styles:
        subset = work[work["_bucket"] == label]
        if subset.empty:
            continue
        fig.add_trace(            go.Scatter(                x=subset["log2FC"],                y=subset["neg_log10_p"],                mode="markers",                name=f"{label} ({len(subset)})",                marker=dict(size=point_size, color=color, opacity=opacity, line=dict(width=0)),                customdata=np.stack([subset["gene"], subset["pvalue"]], axis=-1),                hovertemplate=(                    "%{customdata[0]}<br>log2FC: %{x:.3g}<br>p: %{customdata[1]:.3g}<extra></extra>"                ),            )        )    # X 轴对称：以最大 |log2FC| 为半径，左右等长便于判读倍数方向
    fc_span = float(np.nanmax(np.abs(work["log2FC"].to_numpy(dtype=float)))) if len(work) else 1.0
    fc_span = max(fc_span, float(fc_thr) * 1.15, 0.5) * 1.10
    if show_thr:
        thr_color = _theme_color("volcano_thr")
        fig.add_hline(            y=float(-np.log10(p_thr)),            line_dash="dash",            line_color=thr_color,            line_width=1,            annotation_text=f"p = {p_thr:g}",            annotation_position="right",            annotation_font_color=thr_color,        )
        for value in (fc_thr, -fc_thr):
            if abs(value) > 0:
                fig.add_vline(x=float(value), line_dash="dash", line_color=thr_color, line_width=1)
    y_max = float(work["neg_log10_p"].max()) if len(work) else 1.0
    if topn > 0:
        # 按 |log2FC| 取 Top-N（最外侧的差异基因），再按位置排序做近距离错位
        top = work.assign(_absfc=work["log2FC"].abs()).sort_values(            ["_absfc", "neg_log10_p"], ascending=[False, False], kind="mergesort"        ).head(topn)
        if not top.empty:
            labels = top[["gene", "log2FC", "neg_log10_p"]].copy()
            labels = labels.sort_values("neg_log10_p", ascending=False, kind="mergesort")            # 13px 在 560px 图高 / y 上限约 7.8 单位下 ≈ 0.18 个 y 单位
            step_y = max(0.12, (y_max * 1.12) / 560.0 * 13.0)            # 右/左对齐的文字会横向延伸约 0.6 个 x 单位，碰撞判断要按文字宽度算，            # 只比 0.15 会漏掉「x 差 0.25 但文字互相盖住」的情况
            label_span_x = 0.62
            placed: list[tuple[float, float]] = []
            for _, row in labels.iterrows():
                x_value = float(row["log2FC"])
                y_value = float(row["neg_log10_p"])
                depth = 0
                while depth < 4 and any(                    abs(x_value - other_x) < label_span_x                    and abs((y_value - depth * step_y) - other_y) < step_y                    for other_x, other_y in placed                ):
                    depth += 1
                placed.append((x_value, y_value - depth * step_y))
                positive = x_value >= 0
                fig.add_annotation(                    x=x_value,                    y=y_value,                    text=str(row["gene"]),                    showarrow=False,                    # 标签朝绘图区内侧展开：右半区的点把文字放左边，左半区反过来
                    xanchor="right" if positive else "left",                    yanchor="bottom",                    xshift=-6 if positive else 6,                    # 与已有标签在 x/y 上都过近时，按 y 降序逐层下移，避免叠字
                    yshift=-13 * depth,                    font=dict(size=label_size, color=text_color),                    bgcolor="rgba(0,0,0,0)",                    borderpad=1,                )
    fig.update_layout(        height=560,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        font=dict(color=text_color),        margin=dict(l=70, r=100, t=64 if title else 46, b=60),        hovermode="closest",        legend=dict(            orientation="h",            bgcolor="rgba(0,0,0,0)",            x=1.0,            xanchor="right",            y=1.015,            yanchor="bottom",            font=dict(size=10),        ),    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    fig.update_xaxes(        title_text=x_title,        range=[-fc_span, fc_span],        gridcolor="rgba(128,128,128,0.12)",        gridwidth=0.6,        zeroline=True,        zerolinecolor="rgba(128,128,128,0.45)",        zerolinewidth=0.8,    )
    fig.update_yaxes(        title_text=y_title,        range=[0, y_max * 1.12],        gridcolor="rgba(128,128,128,0.12)",        gridwidth=0.6,        zeroline=False,    )
    preview = work.drop(columns=["_bucket"]).reset_index(drop=True)
    counts = preview["group"].value_counts()
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"Volcano 就绪：{len(preview):,} 行；"        f"上调 {int(counts.get(_GROUP_UP, 0)):,} / 下调 {int(counts.get(_GROUP_DOWN, 0)):,} / "        f"不显著 {int(counts.get(_GROUP_NS, 0)):,}"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render