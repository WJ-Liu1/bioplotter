from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
GO Enrichment Plot (Plotly 交互版本)
支持三种图形：
  1. 柱状图
  2. 棒状图
  3. 气泡图
输入数据要求：
  柱状图 / 棒状图：
    - GO_Term / term / description
    - GO_Class / class / category / ontology
    - number_of_out / count / gene_count
  气泡图：
    - Richfactor / rich_factor
    - GO_desc / description / term
    - Corrected_P / padj / pvalue / fdr
    - Expressed_GO / count / gene_count
说明：
  - 自动识别常见列名别名
  - 左侧参数根据图形样式动态变化
  - 帮助、数据预览、下载由主程序统一处理
"""

FONT_CHOICES = ["sans", "serif", "mono", "wqy-microhei", "STKaiti", "simhei"]
FACE_CHOICES = {
    "默认": "normal",
    "粗体": "bold",
    "斜体": "italic",
    "粗斜体": "italic",
}

GO_TITLE_KEYS = {
    "柱状图": "go_bar_title_text",
    "棒状图": "go_lolli_title_text",
    "气泡图": "go_bubble_title_text",
}


def _sample_bar_df() -> pd.DataFrame:
    """柱状图/棒状图示例数据（若不存在则返回模拟数据）"""
    try:
        sample_path = get_sample_path("go_bar")
        if sample_path.exists():
            return read_table(sample_path, sample_path.name)
    except Exception:
        pass
    # 内置模拟数据（确保示例可用）
    return pd.DataFrame({
        "GO_Term": ["GO:000001", "GO:000002", "GO:000003", "GO:000004", "GO:000005"],
        "GO_Class": ["BP", "CC", "MF", "BP", "CC"],
        "number_of_out": [25, 18, 30, 12, 22]
    })


def _sample_bubble_df() -> pd.DataFrame:
    """气泡图示例数据（若不存在则返回模拟数据）"""
    try:
        sample_path = get_sample_path("go_bubble")
        if sample_path.exists():
            return read_table(sample_path, sample_path.name)
    except Exception:
        pass
    # 内置模拟数据
    return pd.DataFrame({
        "Richfactor": [0.45, 0.32, 0.58, 0.21, 0.67],
        "GO_desc": ["regulation of transcription", "signal transduction", "apoptotic process",
                    "cell adhesion", "protein phosphorylation"],
        "Corrected_P": [0.001, 0.005, 0.002, 0.01, 0.003],
        "Expressed_GO": [15, 8, 20, 5, 12]
    })


def _sample_bar_bytes() -> bytes:
    try:
        return sample_bytes("go_bar")
    except Exception:
        df = _sample_bar_df()
        return df.to_csv(sep="\t", index=False).encode()


def _sample_bubble_bytes() -> bytes:
    try:
        return sample_bytes("go_bubble")
    except Exception:
        df = _sample_bubble_df()
        return df.to_csv(sep="\t", index=False).encode()


def _load_current_df():
    style = st.session_state.get("go_style", "柱状图")
    use_sample = st.session_state.get("go_use_sample", True)
    if use_sample:
        if style in {"柱状图", "棒状图"}:
            return _sample_bar_df().copy(), None
        return _sample_bubble_df().copy(), None
    uploaded = st.session_state.get("go_file")
    if uploaded is None:
        return None, "请先上传数据文件。"
    try:
        return read_table(uploaded, uploaded.name), None
    except Exception as exc:
        return None, f"文件读取失败：{exc}"


def _safe_font(name: str) -> str:
    return name if name else "sans-serif"


def _wrap_labels(values, width=40):
    return ["<br>".join(textwrap.wrap(str(v), width=width)) for v in values]


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).replace("﻿", "").strip() for c in out.columns]
    return out


def _rename_by_alias(df: pd.DataFrame, alias_map: dict[str, list[str]]) -> pd.DataFrame:
    out = _clean_columns(df)
    lower_map = {str(c).strip().lower(): c for c in out.columns}
    ren = {}
    for target, aliases in alias_map.items():
        for alias in aliases:
            if alias.lower() in lower_map:
                ren[lower_map[alias.lower()]] = target
                break
    return out.rename(columns=ren)


def _normalize_bar_df(df: pd.DataFrame) -> pd.DataFrame:
    alias_map = {
        "GO_Term": ["GO_Term", "go_term", "term", "description", "go_desc"],
        "GO_Class": ["GO_Class", "go_class", "class", "category", "ontology"],
        "number_of_out": ["number_of_out", "count", "counts", "gene_count", "expressed_go", "number"],
    }
    work = _rename_by_alias(df, alias_map)
    need = {"GO_Term", "GO_Class", "number_of_out"}
    if not need.issubset(work.columns):
        missing = need - set(work.columns)
        raise ValueError(f"柱状图/棒状图数据缺少必要列：{missing}。支持的列名别名见帮助。")
    out = work[["GO_Term", "GO_Class", "number_of_out"]].copy()
    out["GO_Term"] = out["GO_Term"].astype(str)
    out["GO_Class"] = out["GO_Class"].astype(str)
    out["number_of_out"] = pd.to_numeric(out["number_of_out"], errors="coerce")
    out = out.dropna(subset=["number_of_out"]).copy()
    out = out.sort_values(["GO_Class", "number_of_out"], ascending=[True, False]).reset_index(drop=True)
    if out.empty:
        raise ValueError("柱状图/棒状图数据为空。")
    return out


def _normalize_bubble_df(df: pd.DataFrame) -> pd.DataFrame:
    alias_map = {
        "Richfactor": ["Richfactor", "richfactor", "rich_factor"],
        "GO_desc": ["GO_desc", "go_desc", "description", "term", "go_term"],
        "Corrected_P": ["Corrected_P", "corrected_p", "padj", "pvalue", "p_value", "fdr"],
        "Expressed_GO": ["Expressed_GO", "expressed_go", "count", "gene_count", "number_of_out"],
    }
    work = _rename_by_alias(df, alias_map)
    need = {"Richfactor", "GO_desc", "Corrected_P", "Expressed_GO"}
    if not need.issubset(work.columns):
        missing = need - set(work.columns)
        raise ValueError(f"气泡图数据缺少必要列：{missing}。支持的列名别名见帮助。")
    out = work[["Richfactor", "GO_desc", "Corrected_P", "Expressed_GO"]].copy()
    out["Richfactor"] = pd.to_numeric(out["Richfactor"], errors="coerce")
    out["Corrected_P"] = pd.to_numeric(out["Corrected_P"], errors="coerce")
    out["Expressed_GO"] = pd.to_numeric(out["Expressed_GO"], errors="coerce")
    out["GO_desc"] = out["GO_desc"].astype(str)
    out = out.dropna(subset=["Richfactor", "Corrected_P", "Expressed_GO"]).copy()
    out = out.sort_values("Corrected_P", ascending=True).reset_index(drop=True)
    if out.empty:
        raise ValueError("气泡图数据为空。")
    return out


def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    # 检测样式变化，清除旧图
    prev_style = st.session_state.get("_prev_go_style")
    current_style = st.session_state.get("go_style", "柱状图")
    if prev_style != current_style:
        st.session_state["last_fig"] = None
        st.session_state["last_plotly"] = None
        st.session_state["_prev_go_style"] = current_style

    st.selectbox(
        "图形样式",
        ["柱状图", "棒状图", "气泡图"],
        index=0,
        key="go_style",
    )
    sample_loader_control("go_use_sample", ["go_bar", "go_bubble"], "go_load_sample_btn")
    if not st.session_state.get("go_use_sample", True):
        st.file_uploader(
            "选择文件",
            type=["txt", "tsv", "csv", "xlsx"],
            key="go_file",
        )
        st.caption("支持自动识别常见列名别名：term/class/count、rich_factor/padj/gene_count 等。")
    if st.session_state.get("go_style", "柱状图") in {"柱状图", "棒状图"}:
        st.download_button(
            "示例数据",
            data=_sample_bar_bytes(),
            file_name="柱形图棒状图示例数据.txt",
            mime="text/tab-separated-values",
            width="stretch",
        )
    else:
        st.download_button(
            "示例数据",
            data=_sample_bubble_bytes(),
            file_name="气泡图示例数据.txt",
            mime="text/tab-separated-values",
            width="stretch",
        )
    style = st.session_state.get("go_style", "柱状图")
    st.text_input("标题", value=style, key=GO_TITLE_KEYS[style])

    if st.session_state.get("go_style", "柱状图") == "柱状图":
        with st.expander("字体", expanded=False):
            st.selectbox("标题字体样式", FONT_CHOICES, index=0, key="go_bar_title_family")
            st.selectbox("标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_title_face")
            st.slider("标题字号", 1, 40, 15, key="go_bar_title_size")
            st.selectbox("横坐标字体样式", FONT_CHOICES, index=0, key="go_bar_x_family")
            st.selectbox("横坐标字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_x_face")
            st.slider("横坐标字体大小", 5, 40, 10, key="go_bar_x_size")
            st.selectbox("纵坐标字体样式", FONT_CHOICES, index=0, key="go_bar_y_family")
            st.selectbox("纵坐标字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_y_face")
            st.slider("纵坐标字体大小", 5, 40, 10, key="go_bar_y_size")
            st.selectbox("图例字体样式", FONT_CHOICES, index=0, key="go_bar_legend_family")
            st.selectbox("图例字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_legend_face")
            st.slider("图例字体大小", 10, 40, 12, key="go_bar_legend_size")
            st.selectbox("标签字体样式", FONT_CHOICES, index=0, key="go_bar_label_family")
            st.selectbox("标签字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_label_face")
            st.slider("标签字体大小", 1, 20, 5, key="go_bar_label_size")
            st.selectbox("Y轴标题字体样式", FONT_CHOICES, index=0, key="go_bar_ylabel_family")
            st.selectbox("Y轴标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bar_ylabel_face")
            st.slider("Y轴标题字体大小", 1, 40, 10, key="go_bar_ylabel_size")
        with st.expander("颜色", expanded=False):
            st.color_picker("BP", value="#239BEB", key="go_bar_color1")
            st.color_picker("CC", value="#16F7EC", key="go_bar_color2")
            st.color_picker("MF", value="#6CF213", key="go_bar_color3")
        with st.expander("其他", expanded=False):
            st.slider("坐标轴字体倾斜度", -60, 90, 90, 5, key="go_bar_angle")
            st.slider("图例距离", 0.0, 1.0, 0.1, 0.1, key="go_bar_legend_gap")

    elif st.session_state.get("go_style") == "棒状图":
        with st.expander("字体", expanded=False):
            st.selectbox("标题字体样式", FONT_CHOICES, index=0, key="go_lolli_title_family")
            st.selectbox("标题字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_title_face")
            st.slider("标题字体大小", 10, 30, 14, key="go_lolli_title_size")
            st.selectbox("横坐标字体样式", FONT_CHOICES, index=0, key="go_lolli_x_family")
            st.selectbox("横坐标字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_x_face")
            st.slider("横坐标字体大小", 10, 30, 12, key="go_lolli_x_size")
            st.selectbox("纵坐标字体样式", FONT_CHOICES, index=0, key="go_lolli_y_family")
            st.selectbox("纵坐标字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_y_face")
            st.slider("纵坐标字体大小", 5, 25, 10, key="go_lolli_y_size")
            st.selectbox("图例字体样式", FONT_CHOICES, index=0, key="go_lolli_legend_family")
            st.selectbox("图例字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_legend_face")
            st.slider("图例字体大小", 10, 30, 12, key="go_lolli_legend_size")
            st.selectbox("标签字体样式", FONT_CHOICES, index=0, key="go_lolli_label_family")
            st.selectbox("标签字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_label_face")
            st.slider("标签字体大小", 10, 30, 15, key="go_lolli_label_size")
            st.selectbox("Y轴标题字体样式", FONT_CHOICES, index=0, key="go_lolli_ylabel_family")
            st.selectbox("Y轴标题字重", list(FACE_CHOICES.keys()), index=0, key="go_lolli_ylabel_face")
            st.slider("Y轴标题字体大小", 10, 30, 15, key="go_lolli_ylabel_size")
        with st.expander("颜色", expanded=False):
            st.color_picker("BP", value=theme.get("sci_go_1", "#5BA790"), key="go_lolli_color1")
            st.color_picker("CC", value=theme.get("sci_go_2", "#EBCB97"), key="go_lolli_color2")
            st.color_picker("MF", value=theme.get("sci_go_3", "#D96C4F"), key="go_lolli_color3")
        with st.expander("其他", expanded=False):
            st.slider("棒球大小", 1, 20, 6, key="go_lolli_dot_size")
            st.slider("棒棍大小", 1, 5, 1, key="go_lolli_line_size")
            st.slider("坐标轴字体倾斜度", 45, 90, 90, 1, key="go_lolli_angle")

    else:  # 气泡图
        with st.expander("字体", expanded=False):
            st.selectbox("标题字体样式", FONT_CHOICES, index=0, key="go_bub_title_family")
            st.selectbox("标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_title_face")
            st.slider("标题字体大小", 10, 40, 14, key="go_bub_title_size")
            st.selectbox("横坐标轴标题字体样式", FONT_CHOICES, index=0, key="go_bub_xlab_family")
            st.selectbox("横坐标轴标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_xlab_face")
            st.slider("横坐标轴标题字体大小", 10, 40, 14, key="go_bub_xlab_size")
            st.selectbox("横坐标字体样式", FONT_CHOICES, index=0, key="go_bub_xtick_family")
            st.selectbox("横坐标字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_xtick_face")
            st.slider("横坐标字体大小", 10, 40, 14, key="go_bub_xtick_size")
            st.selectbox("纵坐标标题字体样式", FONT_CHOICES, index=0, key="go_bub_ylab_family")
            st.selectbox("纵坐标标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_ylab_face")
            st.slider("纵坐标标题字体大小", 10, 40, 10, key="go_bub_ylab_size")
            st.selectbox("图例标题字体样式", FONT_CHOICES, index=0, key="go_bub_legend_title_family")
            st.selectbox("图例标题字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_legend_title_face")
            st.slider("图例标题字体大小", 10, 40, 14, key="go_bub_legend_title_size")
            st.selectbox("图例数字字体样式", FONT_CHOICES, index=0, key="go_bub_legend_text_family")
            st.selectbox("图例数字字重", list(FACE_CHOICES.keys()), index=0, key="go_bub_legend_text_face")
            st.slider("图例数字大小", 5, 25, 10, key="go_bub_legend_text_size")
        with st.expander("颜色", expanded=False):
            st.color_picker("low", value=theme.get("sci_go_low", "#669DBC"), key="go_bub_low")
            st.color_picker("mid", value=theme.get("sci_go_mid", "#F9EEE4"), key="go_bub_mid")
        st.number_input("图形高度（px）", min_value=300, max_value=3000, value=800, step=10, key="go_h")
        st.number_input("图形宽度（px）", min_value=300, max_value=3000, value=900, step=10, key="go_w")


# ========== Plotly 绘图函数 ==========
MAX_TERM_CHARS = 38


def _left_room(df: pd.DataFrame, font_size: int = 9) -> int:
    """横向布局下 y 轴 term 标签需要的左边距（180–240）。"""
    col = "GO_Term" if "GO_Term" in df.columns else ("GO_desc" if "GO_desc" in df.columns else None)
    longest = 0
    if col and len(df):
        longest = int(df[col].astype(str).str.len().max())
    estimate = int(min(60, longest) * font_size * 0.66 + 45)
    return max(200, min(470, estimate))


def _short_term(term) -> str:
    """长 GO term 截断显示，完整文本仍通过 hover 提供。"""
    text = str(term)
    return text if len(text) <= MAX_TERM_CHARS else text[: MAX_TERM_CHARS - 3] + "…"


def _xaxis_room(df: pd.DataFrame, font_size: int) -> int:
    """90° 旋转的 GO term 标签需要按最长条目留底部空间，否则会被裁掉。"""
    longest = 0
    if "GO_Term" in df.columns and len(df):
        longest = int(df["GO_Term"].astype(str).str.len().max())
    return int(min(300, max(110, longest * font_size * 0.62 + 20)))


def _build_bar_plot_plotly(df: pd.DataFrame, shared: dict, theme: dict) -> go.Figure:
    """柱状图（竖向，等价 ggpubr::ggbarplot + sort.val="desc"）。"""
    color1 = st.session_state.get("go_bar_color1", "#239BEB")
    color2 = st.session_state.get("go_bar_color2", "#16F7EC")
    color3 = st.session_state.get("go_bar_color3", "#6CF213")
    def _class_color(label) -> str:
        """GO_Class 可能是 BP/CC/MF，也可能是全称，两种都要能命中。"""
        key = str(label).strip().upper()
        if key.startswith("BP") or "BIOLOGICAL" in key:
            return color1
        if key.startswith("CC") or "CELLULAR" in key:
            return color2
        if key.startswith("MF") or "MOLECULAR" in key:
            return color3
        return theme.get("sci_network_primary", "#3AA2B6")

    # 先按 GO_Class 分组、组内按 number_of_out 降序，类顺序按首次出现
    order_index = list(dict.fromkeys(df["GO_Class"].tolist()))
    df = df.copy()
    df["GO_Class"] = pd.Categorical(df["GO_Class"], categories=order_index, ordered=True)
    df = df.sort_values(["GO_Class", "number_of_out"], ascending=[True, False]).reset_index(drop=True)
    categories = order_index

    fig = go.Figure()
    tick_colors = []
    tick_text = []
    for cat in categories:
        subset = df[df["GO_Class"] == cat]
        fig.add_trace(go.Bar(
            orientation="v",
            x=subset["GO_Term"],
            y=subset["number_of_out"],
            name=str(cat),
            customdata=subset["GO_Term"].astype(str).tolist(),
            marker=dict(
                color=_class_color(cat),
                line=dict(color="black", width=0.8),
            ),
            text=subset["number_of_out"],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(
                size=st.session_state.get("go_bar_label_size", 5) * 2.8,
                family=_safe_font(st.session_state.get("go_bar_label_family", "sans")),
                weight=FACE_CHOICES.get(st.session_state.get("go_bar_label_face", "默认"), "normal")
            ),
            hovertemplate='%{customdata}<br>Count: %{y}<extra></extra>'
        ))
        tick_text.extend(subset["GO_Term"].astype(str).tolist())
        tick_colors.extend([_class_color(cat)] * len(subset))

    title_font_size = st.session_state.get("go_bar_title_size", 15)
    title_font_family = _safe_font(st.session_state.get("go_bar_title_family", "sans"))
    title_font_weight = FACE_CHOICES.get(st.session_state.get("go_bar_title_face", "默认"), "normal")
    x_tick_font_size = st.session_state.get("go_bar_x_size", 10)
    x_tick_font_family = _safe_font(st.session_state.get("go_bar_x_family", "sans"))
    x_tick_font_weight = FACE_CHOICES.get(st.session_state.get("go_bar_x_face", "默认"), "normal")
    y_tick_font_size = st.session_state.get("go_bar_y_size", 10)
    y_tick_font_family = _safe_font(st.session_state.get("go_bar_y_family", "sans"))
    y_tick_font_weight = FACE_CHOICES.get(st.session_state.get("go_bar_y_face", "默认"), "normal")
    y_label_font_size = st.session_state.get("go_bar_ylabel_size", 10)
    y_label_font_family = _safe_font(st.session_state.get("go_bar_ylabel_family", "sans"))
    y_label_font_weight = FACE_CHOICES.get(st.session_state.get("go_bar_ylabel_face", "默认"), "normal")
    legend_font_size = st.session_state.get("go_bar_legend_size", 12)
    legend_font_family = _safe_font(st.session_state.get("go_bar_legend_family", "sans"))
    legend_font_weight = FACE_CHOICES.get(st.session_state.get("go_bar_legend_face", "默认"), "normal")

    tick_angle = st.session_state.get("go_bar_angle", 90)
    text_color = theme.get("text", "#000000")
    fig.update_layout(
        title=dict(
            text=st.session_state.get(GO_TITLE_KEYS["柱状图"], "柱状图"),
            font=dict(size=title_font_size, family=title_font_family, weight=title_font_weight, color=text_color),
            x=0.5
        ),
        xaxis=dict(
            title=dict(text="", font=dict(size=y_label_font_size, color=text_color)),
            tickangle=tick_angle,
            tickvals=list(range(len(df))),
            ticktext=[""] * len(df),
            tickfont=dict(
                size=x_tick_font_size,
                family=x_tick_font_family,
                weight=x_tick_font_weight,
                color=text_color,
            ),
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="outside",
            ticklen=6,
            tickcolor="rgba(80,80,80,1)",
        ),
        yaxis=dict(
            title=dict(text="Gene Number", font=dict(size=y_label_font_size, family=y_label_font_family, weight=y_label_font_weight, color=text_color)),
            tickangle=0,
            tickfont=dict(size=y_tick_font_size, family=y_tick_font_family, weight=y_tick_font_weight, color=text_color),
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="outside",
            ticklen=6,
            tickcolor="rgba(80,80,80,1)",
        ),
        legend=dict(
            title=dict(text="GO_Class", font=dict(size=legend_font_size, color=text_color)),
            font=dict(size=legend_font_size, family=legend_font_family, weight=legend_font_weight, color=text_color),
            x=1.02, y=1,
            xanchor='left',
            yanchor='top',
            bgcolor='rgba(0,0,0,0)',
        ),
        bargap=0.15,
        plot_bgcolor=theme.get("panel", "#ffffff"),
        paper_bgcolor=theme.get("panel", "#ffffff"),
        width=st.session_state.get("go_w", 900),
        height=st.session_state.get("go_h", 800),
        margin=dict(l=70, r=170, t=60, b=_xaxis_room(df, x_tick_font_size))
    )
    # x 轴刻度文字按 GO_Class 上色，Plotly 不支持彩色 tickfont
    for i, (term, col) in enumerate(zip(df["GO_Term"].astype(str), tick_colors)):
        fig.add_annotation(
            x=i, y=-0.012,
            xref="x", yref="paper",
            text=term,
            showarrow=False,
            textangle=-90,
            xanchor="center", yanchor="top",
            font=dict(size=x_tick_font_size, family=x_tick_font_family, weight=x_tick_font_weight, color=col),
        )
    return fig


def _build_lollipop_plot_plotly(df: pd.DataFrame, shared: dict, theme: dict) -> go.Figure:
    """棒状图（Plotly）"""
    color1 = st.session_state.get("go_lolli_color1", theme.get("sci_go_1", "#5BA790"))
    color2 = st.session_state.get("go_lolli_color2", theme.get("sci_go_2", "#EBCB97"))
    color3 = st.session_state.get("go_lolli_color3", theme.get("sci_go_3", "#D96C4F"))
    def _class_color(label) -> str:
        """GO_Class 可能是 BP/CC/MF，也可能是全称，两种都要能命中。"""
        key = str(label).strip().upper()
        if key.startswith("BP") or "BIOLOGICAL" in key:
            return color1
        if key.startswith("CC") or "CELLULAR" in key:
            return color2
        if key.startswith("MF") or "MOLECULAR" in key:
            return color3
        return theme.get("sci_network_primary", "#3AA2B6")

    categories = df["GO_Class"].unique()
    fig = go.Figure()
    for cat in categories:
        subset = df[df["GO_Class"] == cat]
        # 添加水平线（棒）
        for _, row in subset.iterrows():
            fig.add_trace(go.Scatter(
                x=[0, row["number_of_out"]],
                y=[row["GO_Term"], row["GO_Term"]],
                mode='lines',
                line=dict(color=_class_color(cat), width=st.session_state.get("go_lolli_line_size", 1)),
                showlegend=False,
                hoverinfo='none'
            ))
        # 添加点（球）
        fig.add_trace(go.Scatter(
            x=subset["number_of_out"],
            y=[_short_term(term) for term in subset["GO_Term"]],
            customdata=subset["GO_Term"].astype(str).tolist(),
            mode='markers+text',
            marker=dict(
                size=st.session_state.get("go_lolli_dot_size", 6) * 2,
                color=_class_color(cat),
                line=dict(color='black', width=0.5)
            ),
            text=subset["number_of_out"],
            textposition='middle right',
            textfont=dict(
                size=st.session_state.get("go_lolli_label_size", 15) - 3,
                family=_safe_font(st.session_state.get("go_lolli_label_family", "sans")),
                weight=FACE_CHOICES.get(st.session_state.get("go_lolli_label_face", "默认"), "normal"),
                color='white'
            ),
            name=cat,
            hovertemplate='%{y}<br>Count: %{x}<extra></extra>'
        ))

    title_font_size = st.session_state.get("go_lolli_title_size", 14)
    title_font_family = _safe_font(st.session_state.get("go_lolli_title_family", "sans"))
    title_font_weight = FACE_CHOICES.get(st.session_state.get("go_lolli_title_face", "默认"), "normal")
    y_tick_font_size = st.session_state.get("go_lolli_y_size", 10)
    y_tick_font_family = _safe_font(st.session_state.get("go_lolli_y_family", "sans"))
    y_tick_font_weight = FACE_CHOICES.get(st.session_state.get("go_lolli_y_face", "默认"), "normal")
    x_tick_font_size = st.session_state.get("go_lolli_x_size", 12)
    x_tick_font_family = _safe_font(st.session_state.get("go_lolli_x_family", "sans"))
    x_tick_font_weight = FACE_CHOICES.get(st.session_state.get("go_lolli_x_face", "默认"), "normal")
    y_label_font_size = st.session_state.get("go_lolli_ylabel_size", 15)
    y_label_font_family = _safe_font(st.session_state.get("go_lolli_ylabel_family", "sans"))
    y_label_font_weight = FACE_CHOICES.get(st.session_state.get("go_lolli_ylabel_face", "默认"), "normal")
    legend_font_size = st.session_state.get("go_lolli_legend_size", 12)
    legend_font_family = _safe_font(st.session_state.get("go_lolli_legend_family", "sans"))
    legend_font_weight = FACE_CHOICES.get(st.session_state.get("go_lolli_legend_face", "默认"), "normal")

    text_color = theme.get("text", "#000000")
    fig.update_layout(
        title=dict(
            text=st.session_state.get(GO_TITLE_KEYS["棒状图"], "棒状图"),
            font=dict(size=title_font_size, family=title_font_family, weight=title_font_weight, color=text_color),
            x=0.5
        ),
        xaxis=dict(
            title="Gene Number",
            tickangle=0,
            tickfont=dict(size=min(int(x_tick_font_size), 10), family=x_tick_font_family, weight=x_tick_font_weight, color=text_color),
            gridcolor="rgba(128,128,128,0.12)",
            zeroline=False,
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=min(int(y_tick_font_size), 9), family=y_tick_font_family, weight=y_tick_font_weight, color=text_color),
            categoryorder='total ascending',
            autorange='reversed'
        ),
        legend=dict(
            title="",
            font=dict(size=legend_font_size, family=legend_font_family, weight=legend_font_weight, color=text_color),
            x=1.02, y=1,
            xanchor='left',
            yanchor='top',
            bgcolor='rgba(255,255,255,0.7)'
        ),
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        width=st.session_state.get("go_w", 900),
        height=st.session_state.get("go_h", 800),
        margin=dict(l=_left_room(df, 9), r=150, t=60, b=50)
    )
    return fig


def _build_bubble_plot_plotly(df: pd.DataFrame, shared: dict, theme: dict) -> go.Figure:
    """气泡图（按 log10 显著性做双色渐变）。"""
    low_color = st.session_state.get("go_bub_low") or "#669DBC"
    mid_color = st.session_state.get("go_bub_mid") or "#F9EEE4"
    high_color = st.session_state.get("go_bub_high") or "#3A3A98"

    y_labels = _wrap_labels(df["GO_desc"], width=60)

    min_exp = df["Expressed_GO"].min()
    max_exp = df["Expressed_GO"].max()
    if min_exp == max_exp:
        sizes = np.full(len(df), 15)
    else:
        sizes = np.interp(df["Expressed_GO"], (min_exp, max_exp), (6, 28))

    # 颜色：log10(p)，中点取变换后的均值
    logs = np.log10(np.clip(df["Corrected_P"].to_numpy(dtype=float), 1e-300, None))
    cmin, cmax = float(np.min(logs)), float(np.max(logs))
    # 双色渐变的中点默认为 0（log10 空间），色标只用低半段
    mid_pos = 0.5 if cmax <= cmin else (cmax - cmin) / (0.0 - cmin)
    mid_pos = float(np.clip(mid_pos, 0.05, 1.0))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Richfactor"],
        y=y_labels,
        mode='markers',
        marker=dict(
            size=sizes,
            color=logs,
            cmin=cmin,
            cmax=cmax,
            colorscale=[[0, low_color], [mid_pos, mid_color], [1, mid_color]],
            colorbar=dict(
                title=dict(text="pvalue", side="top"),
                x=1.02, y=0.72, len=0.42, thickness=14,
                tickvals=[v for v in (-2, -4, -6, -8) if cmin <= v <= cmax],
                ticktext=[f"1e{v:02d}" for v in (-2, -4, -6, -8) if cmin <= v <= cmax],
                tickfont=dict(
                    size=st.session_state.get("go_bub_legend_text_size", 10),
                    family=_safe_font(st.session_state.get("go_bub_legend_text_family", "sans")),
                    weight=FACE_CHOICES.get(st.session_state.get("go_bub_legend_text_face", "默认"), "normal")
                )
            ),
            showscale=True,
            line=dict(color='#4d4d4d', width=0.4),
            opacity=1.0
        ),
        text=df["Expressed_GO"],
        showlegend=False,
        hovertemplate='%{y}<br>Richfactor: %{x}<br>pvalue: %{marker.color:.3e}<br>Gene count: %{text}<extra></extra>'
    ))

    # 字体设置
    title_font_size = st.session_state.get("go_bub_title_size", 14)
    title_font_family = _safe_font(st.session_state.get("go_bub_title_family", "sans"))
    title_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_title_face", "默认"), "normal")
    xlab_font_size = st.session_state.get("go_bub_xlab_size", 14)
    xlab_font_family = _safe_font(st.session_state.get("go_bub_xlab_family", "sans"))
    xlab_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_xlab_face", "默认"), "normal")
    xtick_font_size = st.session_state.get("go_bub_xtick_size", 14)
    xtick_font_family = _safe_font(st.session_state.get("go_bub_xtick_family", "sans"))
    xtick_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_xtick_face", "默认"), "normal")
    ylab_font_size = st.session_state.get("go_bub_ylab_size", 10)
    ylab_font_family = _safe_font(st.session_state.get("go_bub_ylab_family", "sans"))
    ylab_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_ylab_face", "默认"), "normal")
    legend_title_font_size = st.session_state.get("go_bub_legend_title_size", 14)
    legend_title_font_family = _safe_font(st.session_state.get("go_bub_legend_title_family", "sans"))
    legend_title_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_legend_title_face", "默认"), "normal")
    legend_text_font_size = st.session_state.get("go_bub_legend_text_size", 10)
    legend_text_font_family = _safe_font(st.session_state.get("go_bub_legend_text_family", "sans"))
    legend_text_font_weight = FACE_CHOICES.get(st.session_state.get("go_bub_legend_text_face", "默认"), "normal")

    text_color = theme.get("text", "#000000")
    fig.update_layout(
        title=dict(
            text=st.session_state.get(GO_TITLE_KEYS["气泡图"], "气泡图"),
            font=dict(size=title_font_size, family=title_font_family, weight=title_font_weight, color=text_color),
            x=0.9, xanchor="center"
        ),
        xaxis=dict(
            title=dict(text="Gene Ratio", font=dict(size=xlab_font_size, family=xlab_font_family, weight=xlab_font_weight, color=text_color)),
            tickangle=0,
            tickfont=dict(size=xtick_font_size, family=xtick_font_family, weight=xtick_font_weight, color=text_color),
            range=[0, 0.75],
            tickvals=[0, 0.25, 0.5, 0.75],
            showgrid=True,
            gridcolor="rgba(0,0,0,0.08)",
            showline=True,
            linecolor="black",
            linewidth=1,
            mirror=True,
            zeroline=False,
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=ylab_font_size, family=ylab_font_family, weight=ylab_font_weight, color=text_color),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.08)",
            showline=True,
            linecolor="black",
            linewidth=1,
            mirror=True,
            zeroline=False,
        ),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        width=st.session_state.get("go_w", 900),
        height=st.session_state.get("go_h", 800),
        margin=dict(l=_left_room(df, 10), r=120, t=60, b=60)
    )

    # 添加大小图例（当数据有变化时）
    if min_exp != max_exp:
        size_vals = np.linspace(min_exp, max_exp, 3)
        for v in size_vals:
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode='markers',
                marker=dict(
                    size=np.interp(v, (min_exp, max_exp), (6, 28)),
                    color='#9a9a9a',
                    line=dict(color='#4d4d4d', width=0.4)
                ),
                name=f"{int(round(v))}",
                showlegend=True,
                legendgroup='size',
            ))
        fig.update_layout(
            legend=dict(
                title=dict(text="Gene_number", font=dict(size=legend_title_font_size, family=legend_title_font_family, weight=legend_title_font_weight, color=text_color)),
                font=dict(size=legend_text_font_size, family=legend_text_font_family, weight=legend_text_font_weight, color=text_color),
                x=1.02, y=0.28,
                xanchor='left',
                yanchor='middle',
                bgcolor='rgba(0,0,0,0)',
                itemsizing='constant',
            )
        )
    else:
        fig.update_layout(showlegend=False)

    return fig


def build(shared: dict):
    style = st.session_state.get("go_style", "柱状图")
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    raw, err = _load_current_df()
    if err:
        return None, None, err, HELP_TEXT
    try:
        if style in {"柱状图", "棒状图"}:
            df = _normalize_bar_df(raw)
            if style == "柱状图":
                fig = _build_bar_plot_plotly(df, shared, theme)
            else:
                fig = _build_lollipop_plot_plotly(df, shared, theme)
        else:
            df = _normalize_bubble_df(raw)
            fig = _build_bubble_plot_plotly(df, shared, theme)
    except Exception as exc:
        st.error(f"图形生成失败：{exc}")
        return None, None, str(exc), HELP_TEXT

    shared["last_plotly"] = fig
    shared["data"] = df
    shared["status"] = f"{style}已生成，共 {len(df)} 条记录。"
    shared["help_text"] = HELP_TEXT
    return fig, df, shared["status"], HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
