"""Manhattan Plot — GWAS association scatter (architecture §3.11).

Chromosomes are sorted naturally, positions are accumulated into a single
``cum_pos`` axis, and **one trace per chromosome** keeps the figure at ~24 traces
regardless of SNP count.  Above 20 000 points the traces switch to
``go.Scattergl`` for GPU rendering.
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
Manhattan Plot（曼哈顿图）

支持输入（CSV / TSV / TXT / XLSX）：
  - 必需：snp（SNP ID）、chr（染色体）、pos（数值坐标）、pvalue（0~1）
  - 可选：gene（标注用）

算法：
  - 染色体自然排序（1,2,…,10,X,Y,MT，数字优先）
  - 累积坐标 cum_pos = 本染色体内的 pos + 前面所有染色体的总长 + 间隔
  - Y 轴 = -log10(pvalue)

可配置项：
  - 列映射、标注列
  - 显著阈值（默认 5e-8）与建议阈值（默认 1e-5）
  - 奇数 / 偶数染色体配色、显著点配色
  - 点大小与透明度、Top-N 标注、阈值线与染色体标签开关
  - 标题

说明：
  - 每条染色体一条 trace（不会退化成每个点一条 trace）
  - 点数 > 20000 时自动切换到 go.Scattergl 以保证流畅
  - p 值为 0 时按 1e-300 截断，避免 log10 出现无穷
"""

NONE_LABEL = "(无)"

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "snp": ("snp", "rsid", "snp_id", "id", "marker"),
    "chr": ("chr", "chrom", "chromosome", "#chr"),
    "pos": ("pos", "position", "bp", "basepair"),
    "p": ("pvalue", "p_value", "p.val", "pval", "p"),
    "label": ("gene", "label", "nearest_gene", "symbol"),
}

COLUMN_LABELS: dict[str, str] = {
    "snp": "snp（SNP ID）",
    "chr": "chr（染色体）",
    "pos": "pos（坐标）",
    "p": "pvalue（0~1）",
}

GL_THRESHOLD = 20_000

_FALLBACK_COLORS: dict[str, str] = {
    "manhattan_odd": "#3C5488",
    "manhattan_even": "#8491B4",
    "manhattan_sig": "#E64B35",
    "bg": "#f5f7fb",
    "text": "#111827",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
    if st.session_state.get("manhattan_use_sample", True):
        try:
            path = get_sample_path("manhattan_gwas")
            return read_table(path, path.name), ""
        except Exception as exc:  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"

    uploaded = st.session_state.get("manhattan_file_upload")
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


def _natural_chr_key(value: str) -> tuple[int, float, str]:
    """Numeric chromosomes first (numerically), then X/Y/MT, then the rest."""
    text = str(value).strip()
    try:
        return (0, float(text), "")
    except ValueError:
        upper = text.upper()
        order = {"X": 1, "Y": 2, "M": 3, "MT": 3}
        return (order.get(upper, 9), 0.0, upper)


def _add_cumulative_position(work: pd.DataFrame, chr_col: str, pos_col: str) -> tuple[pd.DataFrame, list[str], dict[str, float]]:
    """Sort by chromosome/position, add ``cum_pos``, return ``(df, chr_order, midpoints)``."""
    chr_order = sorted(pd.unique(work[chr_col].astype(str)), key=_natural_chr_key)
    rank = {chromosome: index for index, chromosome in enumerate(chr_order)}

    ordered = work.assign(_chr_rank=work[chr_col].astype(str).map(rank))
    ordered = ordered.sort_values(["_chr_rank", pos_col], kind="mergesort").drop(columns=["_chr_rank"])
    ordered = ordered.reset_index(drop=True)

    total_span = float(ordered[pos_col].max() - ordered[pos_col].min()) or 1.0
    gap = total_span * 0.005

    cum_pos = np.zeros(len(ordered), dtype=float)
    midpoints: dict[str, float] = {}
    offset = 0.0
    for chromosome in chr_order:
        mask = (ordered[chr_col].astype(str) == chromosome).to_numpy()
        positions = ordered.loc[mask, pos_col].to_numpy(dtype=float)
        cum_pos[mask] = positions + offset
        length = float(positions.max() - positions.min()) if positions.size else 0.0
        midpoints[chromosome] = offset + length / 2.0
        offset += length + gap

    ordered["cum_pos"] = cum_pos
    return ordered, chr_order, midpoints


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()

    st.markdown("### 数据")
    sample_loader_control("manhattan_use_sample", ["manhattan_gwas"], "manhattan_load_sample_btn")
    if not st.session_state.get("manhattan_use_sample", True):
        st.file_uploader(
            "上传数据文件（CSV / TSV / TXT / XLSX）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="manhattan_file_upload",
        )

    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        return

    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    detected = _detect_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    label_options = [NONE_LABEL] + all_cols

    st.markdown("### 列映射")
    for dimension in ("snp", "chr", "pos", "p"):
        default = detected.get(dimension, all_cols[0])
        _pick(
            COLUMN_LABELS[dimension],
            all_cols,
            f"manhattan_col_{dimension}",
            all_cols.index(default) if default in all_cols else 0,
        )
    default_label = detected.get("label", NONE_LABEL)
    _pick(
        "标注列（可选）",
        label_options,
        "manhattan_col_label",
        label_options.index(default_label) if default_label in label_options else 0,
    )

    st.markdown("### 阈值")
    st.number_input(
        "显著阈值",
        min_value=1e-15,
        max_value=1.0,
        value=5e-8,
        step=1e-8,
        format="%.3g",
        key="manhattan_sig_thr",
    )
    st.number_input(
        "建议阈值",
        min_value=1e-15,
        max_value=1.0,
        value=1e-5,
        step=1e-6,
        format="%.3g",
        key="manhattan_sug_thr",
    )

    st.markdown("### 外观")
    st.color_picker("奇数染色体颜色", value=_theme_color("manhattan_odd"), key="manhattan_color_odd")
    st.color_picker("偶数染色体颜色", value=_theme_color("manhattan_even"), key="manhattan_color_even")
    st.color_picker("显著点颜色", value=_theme_color("manhattan_sig"), key="manhattan_color_sig")
    st.slider("点大小", 2, 12, 5, 1, key="manhattan_point_size")
    st.slider("透明度", 0.1, 1.0, 0.8, 0.05, key="manhattan_opacity")

    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="manhattan_add_title")
    if st.session_state.get("manhattan_add_title", False):
        st.text_input("图形标题", "Manhattan Plot", key="manhattan_title")


def advanced_controls(shared: dict) -> None:
    """Manhattan 的高级参数：标注与阈值线。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.slider("Top-N 标注", 0, 20, 5, 1, key="manhattan_topn")
    st.checkbox("显示阈值线", value=True, key="manhattan_show_thr")
    st.checkbox("显示染色体标签", value=True, key="manhattan_show_chr_label")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT

    detected = _detect_columns(frame)
    columns: dict[str, str] = {}
    for dimension in ("snp", "chr", "pos", "p"):
        chosen = st.session_state.get(f"manhattan_col_{dimension}") or detected.get(dimension)
        if not chosen or chosen not in frame.columns:
            return (
                None,
                None,
                f"缺少必需列：{COLUMN_LABELS[dimension]}。当前列：{', '.join(map(str, frame.columns))}",
                HELP_TEXT,
            )
        columns[dimension] = chosen

    label_col = st.session_state.get("manhattan_col_label", NONE_LABEL)
    if label_col == NONE_LABEL or label_col not in frame.columns:
        label_col = ""

    work = pd.DataFrame(
        {
            "snp": frame[columns["snp"]].astype(str).str.strip(),
            "chr": frame[columns["chr"]].astype(str).str.strip(),
            "pos": pd.to_numeric(frame[columns["pos"]], errors="coerce"),
            "pvalue": pd.to_numeric(frame[columns["p"]], errors="coerce"),
        }
    )
    if label_col:
        work["label"] = frame[label_col].astype(str).str.strip()
    else:
        work["label"] = work["snp"]

    work = work.dropna(subset=["pos", "pvalue"])
    work = work[(work["chr"] != "") & (work["snp"] != "")]
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT

    work["pvalue"] = work["pvalue"].clip(1e-300, 1.0)
    work["neg_log10_p"] = -np.log10(work["pvalue"])
    work, chr_order, midpoints = _add_cumulative_position(work, "chr", "pos")

    sig_thr = float(st.session_state.get("manhattan_sig_thr", 5e-8))
    sug_thr = float(st.session_state.get("manhattan_sug_thr", 1e-5))
    odd_color = st.session_state.get("manhattan_color_odd") or _theme_color("manhattan_odd")
    even_color = st.session_state.get("manhattan_color_even") or _theme_color("manhattan_even")
    sig_color = st.session_state.get("manhattan_color_sig") or _theme_color("manhattan_sig")
    point_size = int(st.session_state.get("manhattan_point_size", 5))
    opacity = float(st.session_state.get("manhattan_opacity", 0.8))
    topn = int(st.session_state.get("manhattan_topn", 5))
    show_thr = bool(st.session_state.get("manhattan_show_thr", True))
    show_chr_label = bool(st.session_state.get("manhattan_show_chr_label", True))
    add_title = bool(st.session_state.get("manhattan_add_title", False))
    title = (st.session_state.get("manhattan_title") or "Manhattan Plot") if add_title else ""
    text_color = theme.get("text", "#111827")

    use_gl = len(work) > GL_THRESHOLD
    scatter_cls = go.Scattergl if use_gl else go.Scatter

    fig = go.Figure()
    for index, chromosome in enumerate(chr_order):
        subset = work[work["chr"] == chromosome]
        if subset.empty:
            continue
        is_significant = (subset["pvalue"] < sig_thr).to_numpy()
        colors = np.where(is_significant, sig_color, odd_color if index % 2 == 0 else even_color)
        fig.add_trace(
            scatter_cls(
                x=subset["cum_pos"],
                y=subset["neg_log10_p"],
                mode="markers",
                name=f"chr{chromosome}",
                marker=dict(size=point_size, color=colors, opacity=opacity, line=dict(width=0)),
                customdata=np.stack([subset["snp"], subset["chr"], subset["pos"], subset["pvalue"]], axis=-1),
                hovertemplate=(
                    "%{customdata[0]}<br>chr%{customdata[1]}:%{customdata[2]}<br>"
                    "p: %{customdata[3]:.3g}<extra></extra>"
                ),
            )
        )

    if show_thr:
        fig.add_hline(
            y=float(-np.log10(sig_thr)),
            line_dash="dash",
            line_color=sig_color,
            line_width=1,
            annotation_text=f"p = {sig_thr:g}",
            annotation_position="top left",
            annotation_font_color=sig_color,
        )
        fig.add_hline(
            y=float(-np.log10(sug_thr)),
            line_dash="dot",
            line_color=_theme_color("manhattan_even"),
            line_width=1,
        )

    if topn > 0:
        top = work.nsmallest(topn, "pvalue")
        if not top.empty:
            fig.add_trace(
                go.Scatter(
                    x=top["cum_pos"],
                    y=top["neg_log10_p"],
                    mode="text",
                    text=top["label"],
                    textposition="top center",
                    textfont=dict(size=9, color=text_color),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

    tick_values = [midpoints[chromosome] for chromosome in chr_order]
    fig.update_layout(
        height=560,
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        font=dict(color=text_color),
        margin=dict(l=70, r=30, t=60 if title else 30, b=70),
        hovermode="closest",
        showlegend=False,
    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    fig.update_xaxes(
        title_text="Chromosome",
        tickmode="array",
        tickvals=tick_values,
        ticktext=[str(chromosome) for chromosome in chr_order] if show_chr_label else [],
        showticklabels=show_chr_label,
        gridcolor="rgba(128,128,128,0.12)",
        gridwidth=0.6,
        zeroline=False,
    )
    fig.update_yaxes(
        title_text="-log10(p)",
        gridcolor="rgba(128,128,128,0.12)",
        gridwidth=0.6,
        zeroline=False,
        rangemode="tozero",
    )

    preview = work[["snp", "chr", "pos", "pvalue", "label", "cum_pos", "neg_log10_p"]].reset_index(drop=True)
    significant = int((work["pvalue"] < sig_thr).sum())
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (
        f"Manhattan 就绪：{len(work):,} SNP × {len(chr_order)} 染色体；"
        f"显著点 {significant} 个（p < {sig_thr:g}）"
    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
