"""CircularBarPlot — native Plotly implementation.

Implements architecture doc §3.4.

Two views over the same data:

* **环形（极坐标柱）** — rose chart with a hollow centre, group separators, a
  centre group label, outer gene labels and significance stars.
* **条形（分面）** — ``make_subplots(rows=1, cols=n_groups, shared_yaxes=True)``
  with one ``go.Bar`` per group, so the stars can live inside their own facet
  (``px.bar(facet_col=...)`` puts every figure-level annotation in facet 1).

Deviation from §3.4 (documented, PRD-driven): the circular view uses closed
``go.Scatterpolar`` polygons instead of ``go.Barpolar``.  ``Barpolar`` has no
``base``/``r0`` and can only draw from ``r = 0``, so it cannot express the
required hollow centre (``cbar_hole``) *and* negative values pointing inwards at
the same time.  The 4-vertex polygon formula is the one from §3.3.

Key naming follows §8.2 — no non-colour key contains
``color/fill/edge/line/bg/reg``.
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
CircularBarPlot（原生环形柱 / 分面条形）

支持输入（CSV / TSV / TXT / XLSX，列名不区分大小写）：
  - Name      基因名（必需）
  - type      分组（必需）
  - data      响应比值，可正可负，允许 NA（必需）
  - p_value   显著性 p 值（可选）
  - num_stars 星号数量（可选，优先使用）

两个视图：
  - 环形视图：极坐标环形柱，带中心分组文字、外圈基因标签、组间扇区间隔。
    空心半径由「空心圆半径」控制，正值向外长、负值向内缩，NA 单独一色。
  - 条形视图：按 type 分面的普通条形图，正负双向 + 星号标注。

可配置项：
  - 列映射、组内排序（不排序 / 降序 / 升序，NA 恒排组末）
  - 正值 / 负值 / NA / 星号四色
  - 环形参数：起始角度、外层半径上限、空心圆半径、标签距离
  - 条形参数：柱宽、X 轴标签角度
  - 字号：基因标签 / 中心文字 / 星号
  - 星号与基因标签显隐、标题

说明：
  - 星号优先取 num_stars 列，缺失时由 p_value 推算
    （p<0.001→3★，p<0.01→2★，p<0.05→1★，NA→0）
  - 环形柱用 4 顶点闭合多边形实现，可同时表达空心半径与正负方向
  - 原版 10+ 逐元素取色收敛为「正 / 负 / NA / 星号」四色
"""
VIEW_CIRCULAR = "环形图（极坐标柱）"
VIEW_BAR = "条形图（分面）"
SORT_OPTIONS: tuple[str, ...] = ("不排序", "降序", "升序")
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {    "name": ("name", "gene", "id", "label"),    "type": ("type", "group", "category", "class"),    "value": ("data", "value", "log2fc", "rr", "ratio", "estimate"),    "pval": ("p_value", "pvalue", "p.val", "p", "padj", "fdr"),    "star": ("num_stars", "stars", "star", "signif", "significance"),}
COLUMN_LABELS: dict[str, str] = {    "name": "Name（基因名）",    "type": "type（分组）",    "value": "data（数值）",    "pval": "p_value（可选）",    "star": "num_stars（可选）",}
_FALLBACK_COLORS: dict[str, str] = {    "cbar_pos": "#E64B35",    "cbar_neg": "#4DBBD5",    "cbar_na": "#B0B0B0",    "cbar_star": "#111827",    "bg": "#f5f7fb",    "text": "#111827",}# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
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
    if st.session_state.get("cbar_use_sample", True):
        try:
            path = get_sample_path("circularbar_genes")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("cbar_file_upload")
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
    return resolved
def _stars_from_p(p_value) -> int:
    try:
        value = float(p_value)
    except (TypeError, ValueError):
        return 0
    if not np.isfinite(value):
        return 0
    if value < 0.001:
        return 3
    if value < 0.01:
        return 2
    if value < 0.05:
        return 1
    return 0
def _star_text(count: int) -> str:
    return "★" * max(0, min(3, int(count)))
def _prepare_frame(frame: pd.DataFrame, columns: dict[str, str]) -> tuple[pd.DataFrame | None, str]:
    name_col, type_col, value_col = columns.get("name"), columns.get("type"), columns.get("value")
    missing = [        label        for label, col in (("Name", name_col), ("type", type_col), ("data", value_col))        if not col or col not in frame.columns    ]
    if missing:
        return None, f"缺少必需列：{', '.join(missing)}。当前列：{', '.join(map(str, frame.columns))}"
    work = pd.DataFrame(        {            "Name": frame[name_col].astype(str).str.strip(),            "type": frame[type_col].astype(str).str.strip(),            "data": pd.to_numeric(frame[value_col], errors="coerce"),        }    )
    work = work[(work["Name"] != "") & (work["type"] != "")]
    if work.empty:
        return None, "当前筛选无数据可绘制。"
    pval_col = columns.get("pval")
    star_col = columns.get("star")
    work["p_value"] = (        pd.to_numeric(frame[pval_col], errors="coerce") if pval_col and pval_col in frame.columns else np.nan    )
    if star_col and star_col in frame.columns:
        work["num_stars"] = (            pd.to_numeric(frame[star_col], errors="coerce").fillna(0).astype(int).clip(0, 3)        )
    else:
        work["num_stars"] = work["p_value"].map(_stars_from_p).astype(int)
    return work.reset_index(drop=True), ""
def _sort_within_groups(work: pd.DataFrame, sort_mode: str) -> pd.DataFrame:
    if sort_mode not in ("降序", "升序"):
        return work.reset_index(drop=True)
    frames: list[pd.DataFrame] = []
    for group in pd.unique(work["type"]):
        subset = work[work["type"] == group].copy()
        subset["_na_flag"] = subset["data"].isna().astype(int)
        subset = subset.sort_values(            ["_na_flag", "data"],            ascending=[True, sort_mode == "升序"],            kind="mergesort",        )
        frames.append(subset.drop(columns=["_na_flag"]))
    return pd.concat(frames, ignore_index=True) if frames else work# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("cbar_use_sample", ["circularbar_genes"], "cbar_load_sample_btn")
    if not st.session_state.get("cbar_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="cbar_file_upload",        )
    st.radio("视图", [VIEW_CIRCULAR, VIEW_BAR], index=0, key="cbar_view_mode", horizontal=False)
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        st.text_input("图形标题", "Circular Bar Plot", key="cbar_title")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    detected = _detect_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    optional_cols = ["无"] + all_cols
    st.markdown("### 列映射")
    for dimension in ("name", "type", "value"):
        default = detected.get(dimension, all_cols[0])
        _pick(            COLUMN_LABELS[dimension],            all_cols,            f"cbar_{dimension}_col",            all_cols.index(default) if default in all_cols else 0,        )
    for dimension in ("pval", "star"):
        default = detected.get(dimension, "无")
        _pick(            COLUMN_LABELS[dimension],            optional_cols,            f"cbar_{dimension}_col",            optional_cols.index(default) if default in optional_cols else 0,        )
    st.markdown("### 排序与配色")
    st.radio("组内排序", list(SORT_OPTIONS), index=0, key="cbar_sort_mode", horizontal=True)
    st.color_picker("正值颜色（data ≥ 0）", value=_theme_color("cbar_pos"), key="cbar_pos_color")
    st.color_picker("负值颜色（data < 0）", value=_theme_color("cbar_neg"), key="cbar_neg_color")
    st.color_picker("NA 颜色", value=_theme_color("cbar_na"), key="cbar_na_color")
    st.color_picker("星号颜色", value=_theme_color("cbar_star"), key="cbar_star_color")
    st.markdown("### 环形参数")
    st.slider("起始角度", 0, 360, 270, 5, key="cbar_start_angle")
    st.slider("外层圆半径（y轴上限）", 0.5, 2.0, 1.0, 0.05, key="cbar_r_max")
    st.slider("空心圆半径（y轴下限）", -1.0, -0.1, -0.5, 0.05, key="cbar_hole")
    st.slider("标签距外圈距离", 0.0, 0.5, 0.10, 0.01, key="cbar_label_dist")
    st.markdown("### 条形参数")
    st.slider("柱宽", 0.3, 1.0, 0.7, 0.05, key="cbar_bar_width")
    st.slider("X 轴标签角度", 0, 90, 45, 5, key="cbar_tick_angle")
    st.markdown("### 字号与显隐")
    st.checkbox("显示基因标签", value=True, key="cbar_show_gene_label")
    st.checkbox("显示星号", value=True, key="cbar_show_star")
    st.slider("基因标签字号", 3, 24, 8, 1, key="cbar_gene_size")
    st.slider("中心文字字号", 3, 28, 12, 1, key="cbar_center_size")
    st.slider("星号字号", 6, 20, 11, 1, key="cbar_star_size")
    st.markdown("### 标题")
    st.text_input("图形标题", "Circular Bar Plot", key="cbar_title")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    detected = _detect_columns(frame)
    columns: dict[str, str] = {}
    for dimension in ("name", "type", "value", "pval", "star"):
        chosen = st.session_state.get(f"cbar_{dimension}_col")
        if chosen is None:
            chosen = detected.get(dimension)
        if chosen == "无":
            chosen = None
        columns[dimension] = chosen or ""
    work, prepare_error = _prepare_frame(frame, columns)
    if work is None:
        return None, None, prepare_error, HELP_TEXT
    sort_mode = st.session_state.get("cbar_sort_mode", "不排序")
    work = _sort_within_groups(work, sort_mode)
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT
    pos_color = st.session_state.get("cbar_pos_color") or _theme_color("cbar_pos")
    neg_color = st.session_state.get("cbar_neg_color") or _theme_color("cbar_neg")
    na_color = st.session_state.get("cbar_na_color") or _theme_color("cbar_na")
    star_color = st.session_state.get("cbar_star_color") or _theme_color("cbar_star")
    show_star = bool(st.session_state.get("cbar_show_star", True))
    show_gene = bool(st.session_state.get("cbar_show_gene_label", True))
    gene_size = int(st.session_state.get("cbar_gene_size", 9))
    center_size = int(st.session_state.get("cbar_center_size", 14))
    star_size = int(st.session_state.get("cbar_star_size", 11))
    bar_width = float(st.session_state.get("cbar_bar_width", 0.7))
    tick_angle = int(st.session_state.get("cbar_tick_angle", 45))
    title_text = st.session_state.get("cbar_title", "Circular Bar Plot") or ""
    work["_value"] = work["data"].fillna(0.0)
    work["_bucket"] = np.where(work["data"].isna(), "NA", np.where(work["_value"] >= 0, "positive", "negative"))
    bucket_color = {"positive": pos_color, "negative": neg_color, "NA": na_color}
    bucket_label = {"positive": "data ≥ 0", "negative": "data < 0", "NA": "NA"}
    group_order = list(pd.unique(work["type"]))
    preview = work.drop(columns=["_value", "_bucket"]).reset_index(drop=True)    # ==================================================================    # Faceted bar view    # ==================================================================
    if st.session_state.get("cbar_view_mode", VIEW_CIRCULAR) == VIEW_BAR:
        n_groups = len(group_order)
        fig = make_subplots(            rows=1,            cols=n_groups,            shared_yaxes=True,            subplot_titles=[str(group) for group in group_order],            horizontal_spacing=min(0.08, 0.4 / max(1, n_groups)),        )
        for index, group in enumerate(group_order, start=1):
            subset = work[work["type"] == group]
            for bucket in ("positive", "negative", "NA"):
                part = subset[subset["_bucket"] == bucket]
                if part.empty:
                    continue
                fig.add_trace(                    go.Bar(                        x=part["Name"],                        y=part["_value"],                        name=bucket_label[bucket],                        marker=dict(color=bucket_color[bucket], line=dict(width=0)),                        width=bar_width,                        showlegend=(index == 1),                        legendgroup=bucket,                        hovertemplate=(                            f"{group}<br>%{{x}}<br>data: %{{customdata[0]}}<extra></extra>"                        ),                        customdata=part["data"].to_numpy(),                    ),                    row=1,                    col=index,                )
            if show_star:
                stars = subset[subset["num_stars"] > 0]
                if not stars.empty:
                    fig.add_trace(                        go.Scatter(                            x=stars["Name"],                            y=stars["_value"],                            mode="text",                            text=[_star_text(value) for value in stars["num_stars"]],                            textposition="top center",                            textfont=dict(size=star_size, color=star_color),                            showlegend=False,                            hoverinfo="skip",                        ),                        row=1,                        col=index,                    )
        fig.update_xaxes(tickangle=-tick_angle, tickfont=dict(size=gene_size))
        fig.update_yaxes(zeroline=True, zerolinecolor="rgba(128,128,128,0.6)", gridcolor="rgba(128,128,128,0.2)")
        fig.update_layout(            height=560,            plot_bgcolor=theme.get("bg", "#f5f7fb"),            paper_bgcolor=theme.get("bg", "#f5f7fb"),            font=dict(color=theme.get("text", "#111827")),            margin=dict(l=60, r=30, t=70, b=80),            legend=dict(title=dict(text=""), orientation="h", y=-0.18, x=0.5, xanchor="center"),            bargap=1.0 - bar_width,        )
        if title_text:
            fig.update_layout(title=dict(text=title_text, font=dict(size=17, color=theme.get("text", "#111827"))))
        shared["last_plotly"] = fig
        shared["data"] = preview
        status = (            f"CircularBarPlot 就绪：{len(work)} 行 × 5 列；{n_groups} 组"            f"（{'/'.join(str(group) for group in group_order)}）；"            f"NA {int(work['data'].isna().sum())} 个；视图=分面条形"        )
        shared["status"] = status
        shared["help_text"] = HELP_TEXT
        return fig, preview, status, HELP_TEXT    # ==================================================================    # Circular (polar) view — 环形柱状图    # y 轴范围 = (inner_radius, y_upper)，柱子从 y=0 向外生长到 |data|，    # 中心留白用于放分组文字，末端预留一个扇区放刻度数字。    # ==================================================================
    start_angle = float(st.session_state.get("cbar_start_angle", 270))
    outer = float(st.session_state.get("cbar_r_max", 1.0))
    inner = float(st.session_state.get("cbar_hole", -0.5))
    label_dist = float(st.session_state.get("cbar_label_dist", 0.10))
    if inner >= 0:
        return None, None, "空心圆半径（y 轴下限）必须小于 0，才能留出中心区域。", HELP_TEXT
    n_items = len(work)
    n_groups = len(group_order)
    max_val = float(work["_value"].abs().max() or 0.0)    # y_upper = max(max_val, outer_radius) + gene_label_distance + 0.2
    y_upper = max(max_val, outer) + label_dist + 0.2
    r_span = y_upper - inner
    def _r(y: float) -> float:
        """把数据坐标 y 映射为极坐标半径（0–1）。"""
        return float(np.clip((y - inner) / r_span, 0.0, 1.0))
    r_zero = _r(0.0)
    r_outer = _r(outer)
    r_label = _r(outer + label_dist + 0.05)
    r_center = max(0.02, _r(-0.35))    # 末尾多留一个扇区放刻度
    total_slots = n_items + 1
    slot = 360.0 / total_slots
    type_palette = ["#fb9a99", "#74a9cf", "#99d8c9", "#fdb462", "#b3de69", "#fccde5", "#8dd3c7", "#bc80bd"]
    type_colors = {group: type_palette[i % len(type_palette)] for i, group in enumerate(sorted(group_order, key=str))}
    segments: dict[str, list[tuple[float, float, float, float]]] = {"positive": [], "negative": [], "NA": []}
    gene_theta: list[float] = []
    gene_text: list[str] = []
    gene_colors: list[str] = []
    star_theta: list[float] = []
    star_texts: list[str] = []
    star_radius: list[float] = []
    centre_theta: list[float] = []
    centre_texts: list[str] = []
    centre_colors: list[str] = []
    separators: list[float] = []
    cursor = start_angle
    for group in group_order:
        subset = work[work["type"] == group]
        group_start = cursor
        for _, row in subset.iterrows():
            theta0 = cursor + slot * (1.0 - bar_width) / 2.0
            theta1 = theta0 + slot * bar_width
            top = max(r_zero + 1e-3, _r(abs(float(row["_value"]))))
            segments.setdefault(str(row["_bucket"]), []).append((r_zero, top, theta0, theta1))
            mid_theta = (theta0 + theta1) / 2.0
            if show_gene:
                gene_theta.append(mid_theta)
                gene_text.append(str(row["Name"]))
                gene_colors.append(type_colors.get(str(group), theme.get("text", "#111827")))
            stars = int(row["num_stars"])
            if show_star and stars > 0:
                value_abs = abs(float(row["_value"]))                # 条形足够高就把星号压在柱顶内部，否则放到柱顶外侧
                if value_abs >= 0.2 and (value_abs - 0.1) >= stars * 0.06:
                    base_y = value_abs - 0.05
                    step = -0.06
                else:
                    base_y = value_abs + 0.05
                    step = 0.06
                star_theta.append(mid_theta)
                star_texts.append(_star_text(stars))
                star_radius.append(_r(base_y + (stars - 1) * step))
            cursor += slot
        separators.append(group_start)
        centre_theta.append((group_start + cursor) / 2.0)
        centre_texts.append(str(group))
        centre_colors.append(type_colors.get(str(group), theme.get("text", "#111827")))
        cursor += 0.0
    separators.append(cursor)
    scale_theta = cursor + slot / 2.0
    fig = go.Figure()    # 1) 柱子：同色分桶后合并为一条 trace，减少 trace 数量
    for bucket in ("positive", "negative", "NA"):
        boxes = segments.get(bucket) or []
        if not boxes:
            continue
        r_values: list[float | None] = []
        theta_values: list[float | None] = []
        for ra, rb, t0, t1 in boxes:
            r_values.extend([ra, rb, rb, ra, ra, None])
            theta_values.extend([t0, t0, t1, t1, t0, None])
        fig.add_trace(            go.Scatterpolar(                r=r_values,                theta=theta_values,                mode="lines",                fill="toself",                fillcolor=bucket_color[bucket],                line=dict(color=bucket_color[bucket], width=0.5),                name=bucket_label[bucket],                showlegend=True,                hoverinfo="skip",                legendgroup="fill",            )        )    # 2) 刻度虚线圆 + 外圈实线圆
    circle_theta = np.linspace(0, 360, 361)
    tick = 0.0
    ticks: list[float] = []
    while tick <= max_val + 1e-9:
        ticks.append(round(tick, 6))
        tick += 0.2
    if not ticks:
        ticks = [0.0]
    # 刻度虚线圆合并为一条 trace（None 分段），避免每个刻度各建一条 trace。
    tick_r: list[float | None] = []
    tick_t: list[float | None] = []
    for value in ticks:
        if abs(value - outer) < 1e-9:
            continue
        radius = _r(value)
        tick_r.extend([radius] * len(circle_theta))
        tick_r.append(None)
        tick_t.extend(circle_theta.tolist())
        tick_t.append(None)
    if tick_r:
        fig.add_trace(go.Scatterpolar(
            r=tick_r, theta=tick_t, mode="lines",
            line=dict(color="#999999", width=1, dash="dash"),
            hoverinfo="skip", showlegend=False,
        ))
    fig.add_trace(go.Scatterpolar(
        r=[r_outer] * len(circle_theta), theta=circle_theta.tolist(),
        mode="lines", line=dict(color="#000000", width=1.2),
        hoverinfo="skip", showlegend=False,
    ))
    # 3) 分组分隔径向虚线：同样合并为一条 trace
    sep_r: list[float | None] = []
    sep_t: list[float | None] = []
    for sep in separators:
        sep_r.extend([0.0, 1.0, None])
        sep_t.extend([sep, sep, None])
    if sep_r:
        fig.add_trace(go.Scatterpolar(
            r=sep_r, theta=sep_t, mode="lines",
            line=dict(color="#999999", width=1, dash="dash"),
            hoverinfo="skip", showlegend=False,
        ))
    # 4) 末端扇区的刻度数字
    scale_values = [value for value in ticks if value <= outer + 1e-9]
    if scale_values:
        fig.add_trace(            go.Scatterpolar(                r=[_r(value) for value in scale_values],                theta=[scale_theta] * len(scale_values),                mode="text",                text=[f"{value:g}" for value in scale_values],                textfont=dict(size=max(8, gene_size - 1), color=theme.get("text", "#111827")),                hoverinfo="skip",                showlegend=False,            )        )
    if show_gene and gene_theta:
        fig.add_trace(            go.Scatterpolar(                r=[r_label] * len(gene_theta),                theta=gene_theta,                mode="text",                text=gene_text,                textfont=dict(size=gene_size, color=gene_colors),                hoverinfo="skip",                showlegend=False,            )        )
    if show_star and star_theta:
        fig.add_trace(            go.Scatterpolar(                r=star_radius,                theta=star_theta,                mode="text",                text=star_texts,                textfont=dict(size=star_size, color=star_color),                hoverinfo="skip",                showlegend=False,            )        )
    if centre_theta:
        fig.add_trace(            go.Scatterpolar(                r=[r_center] * len(centre_theta),                theta=centre_theta,                mode="text",                text=centre_texts,                textfont=dict(size=center_size, color=centre_colors),                hoverinfo="skip",                showlegend=False,            )        )    # 5) type 颜色图例
    for group in group_order:
        fig.add_trace(            go.Scatterpolar(                r=[None],                theta=[None],                mode="lines",                line=dict(color=type_colors.get(str(group), "#999999"), width=2),                name=str(group),                legendgroup="type",                showlegend=True,            )        )
    fig.update_layout(        width=780,        height=780,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        margin=dict(l=40, r=40, t=70 if title_text else 40, b=50),        font=dict(color=theme.get("text", "#111827")),        legend=dict(            # 图例位置
            orientation="v",            x=0.01,            y=0.99,            xanchor="left",            yanchor="top",            bgcolor="rgba(0,0,0,0)",            title=dict(text=""),            tracegroupgap=6,        ),        polar=dict(            bgcolor=theme.get("bg", "#f5f7fb"),            radialaxis=dict(visible=False, range=[0.0, 1.0]),            angularaxis=dict(visible=False, direction="clockwise", rotation=start_angle),        ),    )
    if title_text:
        fig.update_layout(title=dict(text=title_text, font=dict(size=17, color=theme.get("text", "#111827"))))
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"CircularBarPlot 就绪：{n_items} 行 × 5 列；{n_groups} 组"        f"（{'/'.join(str(group) for group in group_order)}）；"        f"NA {int(work['data'].isna().sum())} 个；视图=环形"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render
