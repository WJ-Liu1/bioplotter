from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES
from app.core.random_seed import rng_for, seed_control

HELP_TEXT = """
ScaBoxDen：二维散点图结合顶部与右侧边际分布图（Plotly 交互版本）
输入数据建议包含：
  - x：横坐标数值列
  - y：纵坐标数值列
  - group：可选分组列
功能：
  - 主图：散点图 + 线性回归 + Pearson 相关系数 + 回归方程
  - 顶部边际图：半小提琴 + 箱线图 + 抖动点
  - 右侧边际图：半小提琴 + 箱线图 + 抖动点
"""

MARKER_MAP = {
    "圆形": "circle",
    "正方形": "square",
    "菱形": "diamond",
    "正三角形": "triangle-up",
    "倒三角形": "triangle-down",
}

def _safe_color(value, fallback="#000000"):
    """将颜色值转换为 Plotly 可接受的十六进制字符串"""
    if value is None:
        return fallback
    if isinstance(value, float) and np.isnan(value):
        return fallback
    if isinstance(value, str):
        v = value.strip().lower()
        if v == 'nan':
            return fallback
        if v.startswith('#'):
            return v
        # 简单颜色名映射
        color_map = {
            "black": "#000000", "white": "#FFFFFF", "red": "#FF0000",
            "green": "#008000", "blue": "#0000FF", "gray": "#808080",
            "grey": "#808080", "lightgray": "#D3D3D3", "darkgray": "#A9A9A9",
            "orange": "#FFA500", "yellow": "#FFFF00", "purple": "#800080",
            "pink": "#FFC0CB", "brown": "#A52A2A", "cyan": "#00FFFF",
            "magenta": "#FF00FF"
        }
        return color_map.get(v, v)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        r, g, b = value[0], value[1], value[2]
        if max(r, g, b) <= 1.0:
            r, g, b = int(r*255), int(g*255), int(b*255)
        return f"#{r:02x}{g:02x}{b:02x}"
    return fallback

def _color_with_alpha(color, alpha):
    if alpha >= 1.0 or not color.startswith('#'):
        return color
    r = int(color[1:3], 16) / 255.0
    g = int(color[3:5], 16) / 255.0
    b = int(color[5:7], 16) / 255.0
    return f"rgba({r*255:.0f}, {g*255:.0f}, {b*255:.0f}, {alpha})"

def _sample_download_bytes() -> bytes:
    return sample_bytes("scaboxden")

def _load_raw_df():
    use_sample = st.session_state.get("sbd_use_sample", True)
    uploaded = st.session_state.get("sbd_file", None)

    if use_sample:
        sample_path = get_sample_path("scaboxden")
        return read_table(sample_path, sample_path.name), None
    if uploaded is None:
        return None, "请先上传数据文件。"
    try:
        df = read_table(uploaded, uploaded.name)
        return df, None
    except Exception as exc:
        return None, f"文件读取失败：{exc}"

def _default_col(cols: list[str], preferred: str, fallback_index: int = 0) -> str:
    if preferred in cols:
        return preferred
    if cols:
        idx = min(fallback_index, len(cols) - 1)
        return cols[idx]
    return ""

def _prepare_df(raw: pd.DataFrame, x_col: str, y_col: str, group_col: str | None):
    df = raw.copy()
    df[x_col] = pd.to_numeric(df[x_col], errors="coerce")
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")
    df = df.dropna(subset=[x_col, y_col]).copy()
    if group_col and group_col in df.columns:
        df["group"] = df[group_col].astype(str)
    else:
        df["group"] = "All"
    df["x"] = df[x_col]
    df["y"] = df[y_col]
    return df

def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    sample_loader_control("sbd_use_sample", "scaboxden", "sbd_load_sample_btn")
    if not st.session_state.get("sbd_use_sample", True):
        st.file_uploader(
            "选择文件",
            type=["txt", "tsv", "csv", "xlsx"],
            key="sbd_file",
            help="建议包含 x、y、group 三列",
        )

    st.download_button(
        "下载示例数据",
        data=_sample_download_bytes(),
        file_name="scaboxden_sample.txt",
        mime="text/tab-separated-values",
        width="stretch",
    )

    raw, err = _load_raw_df()
    if raw is not None and not raw.empty:
        cols = raw.columns.tolist()
        st.markdown("---")
        st.markdown("### 数据列映射")
        default_x = _default_col(cols, "x", 0)
        default_y = _default_col(cols, "y", 1 if len(cols) > 1 else 0)
        default_group = "group" if "group" in cols else "None"

        st.selectbox("X 列", cols, index=cols.index(default_x), key="sbd_x_col")
        st.selectbox("Y 列", cols, index=cols.index(default_y), key="sbd_y_col")
        st.selectbox(
            "Group 列（可选）",
            ["None"] + cols,
            index=(["None"] + cols).index(default_group),
            key="sbd_group_col",
        )
    else:
        st.caption("上传数据后可选择 x / y / group 列。")

    st.markdown("---")
    with st.expander("主图参数", expanded=True):
        st.text_input("横坐标标题", value="X title", key="sbd_xlabel")
        st.text_input("纵坐标标题", value="Y title", key="sbd_ylabel")
        st.slider("横纵坐标标题字号", 1, 150, 20, key="sbd_axis_title_size")

        st.color_picker(
            "散点填充颜色",
            value=_safe_color(theme.get("sci_dist_1"), "#D96C4F"),
            key="sbd_scatter_fill",
        )
        st.color_picker(
            "散点外圈颜色",
            value=_safe_color(theme.get("line_default"), "#000000"),
            key="sbd_scatter_edge",
        )
        st.color_picker(
            "回归线与方程颜色",
            value=_safe_color(theme.get("sci_dist_2"), "#2E3A4A"),
            key="sbd_reg_color",
        )

        st.slider("点透明度", 0.0, 1.0, 0.5, 0.05, key="sbd_point_alpha")
        st.slider("点大小", 1.0, 10.0, 3.0, 0.1, key="sbd_point_size")
        st.slider("点外圈粗细", 0.0, 2.4, 0.8, 0.1, key="sbd_point_stroke")
        st.selectbox("点形状", list(MARKER_MAP.keys()), index=0, key="sbd_point_shape")

        st.checkbox("显示边框", value=True, key="sbd_show_border")
        st.color_picker(
            "边框颜色",
            value=_safe_color(theme.get("border_color"), "#EDBB47"),
            key="sbd_border_color",
        )
        st.slider("边框粗细", 0.5, 3.0, 0.8, 0.1, key="sbd_border_width")

    with st.expander("坐标轴参数", expanded=False):
        st.slider("横坐标字体大小", 5, 50, 20, key="sbd_xtick_size")
        st.color_picker(
            "横坐标字体颜色",
            value=_safe_color(theme.get("text"), "#000000"),
            key="sbd_xtick_color",
        )
        st.slider("横坐标倾斜角度", -90, 90, 0, key="sbd_xtick_angle")
        st.selectbox(
            "横标题字体样式",
            ["sans-serif", "serif", "monospace"],
            index=0,
            key="sbd_xlabel_family",
        )

        st.slider("纵坐标字体大小", 5, 50, 20, key="sbd_ytick_size")
        st.color_picker(
            "纵坐标字体颜色",
            value=_safe_color(theme.get("text"), "#000000"),
            key="sbd_ytick_color",
        )
        st.slider("纵坐标倾斜角度", 0, 180, 90, key="sbd_ytick_angle")
        st.selectbox(
            "纵标题字体样式",
            ["sans-serif", "serif", "monospace"],
            index=0,
            key="sbd_ylabel_family",
        )

    with st.expander("右侧边际图参数", expanded=False):
        st.color_picker(
            "右侧半小提琴颜色",
            value=_safe_color(theme.get("sci_dist_3"), "#84B19C"),
            key="sbd_right_violin_fill",
        )
        st.color_picker(
            "右侧箱图填充颜色",
            value=_safe_color(theme.get("sci_dist_4"), "#E3C27A"),
            key="sbd_right_box_fill",
        )
        st.color_picker(
            "右侧箱图边框颜色",
            value=_safe_color(theme.get("line_default"), "#000000"),
            key="sbd_right_box_edge",
        )
        st.color_picker(
            "右侧点填充颜色",
            value=_safe_color(theme.get("sbd_right_point_fill"), "#A899E5"),
            key="sbd_right_point_fill",
        )
        st.color_picker(
            "右侧点外圈颜色",
            value=_safe_color(theme.get("line_default"), "#000000"),
            key="sbd_right_point_edge",
        )

        st.slider("右侧半小提琴宽度", 0.1, 1.0, 0.5, 0.05, key="sbd_right_violin_width")
        st.slider("右侧箱图宽度", 0.05, 0.3, 0.1, 0.01, key="sbd_right_box_width")
        st.slider("右侧箱图边框粗细", 0.1, 2.0, 1.2, 0.1, key="sbd_right_box_lw")
        st.slider("右侧点分布宽度", 0.01, 0.5, 0.12, 0.01, key="sbd_right_jitter")
        st.slider("右侧点大小", 1.0, 6.0, 3.0, 0.1, key="sbd_right_point_size")
        st.slider("右侧点透明度", 0.1, 1.0, 0.5, 0.05, key="sbd_right_point_alpha")
        st.slider("右侧点外圈粗细", 0.0, 1.6, 0.8, 0.1, key="sbd_right_point_stroke")
        st.selectbox("右侧点形状", list(MARKER_MAP.keys()), index=0, key="sbd_right_point_shape")

    with st.expander("顶部边际图参数", expanded=False):
        st.color_picker(
            "顶部半小提琴颜色",
            value=_safe_color(theme.get("sbd_top_violin_fill"), "#FFCBB5"),
            key="sbd_top_violin_fill",
        )
        st.color_picker(
            "顶部箱图填充颜色",
            value=_safe_color(theme.get("sbd_top_box_fill"), "#FF6E26"),
            key="sbd_top_box_fill",
        )
        st.color_picker(
            "顶部箱图边框颜色",
            value=_safe_color(theme.get("line_default"), "#000000"),
            key="sbd_top_box_edge",
        )
        st.color_picker(
            "顶部点填充颜色",
            value=_safe_color(theme.get("sbd_top_point_fill"), "#FFB8DF"),
            key="sbd_top_point_fill",
        )
        st.color_picker(
            "顶部点外圈颜色",
            value=_safe_color(theme.get("line_default"), "#000000"),
            key="sbd_top_point_edge",
        )

        st.slider("顶部半小提琴宽度", 0.1, 1.0, 0.5, 0.05, key="sbd_top_violin_width")
        st.slider("顶部箱图高度", 0.05, 0.3, 0.1, 0.01, key="sbd_top_box_width")
        st.slider("顶部箱图边框粗细", 0.1, 2.0, 1.2, 0.1, key="sbd_top_box_lw")
        st.slider("顶部点分布高度", 0.01, 0.5, 0.12, 0.01, key="sbd_top_jitter")
        st.slider("顶部点大小", 1.0, 6.0, 3.0, 0.1, key="sbd_top_point_size")
        st.slider("顶部点透明度", 0.1, 1.0, 0.5, 0.05, key="sbd_top_point_alpha")
        st.slider("顶部点外圈粗细", 0.0, 1.6, 0.8, 0.1, key="sbd_top_point_stroke")
        st.selectbox("顶部点形状", list(MARKER_MAP.keys()), index=0, key="sbd_top_point_shape")

    with st.expander("图像尺寸", expanded=False):
        st.number_input("图形高度（px）", min_value=300, max_value=2000, value=600, step=10, key="sbd_h")
        st.number_input("图形宽度（px）", min_value=300, max_value=2000, value=600, step=10, key="sbd_w")
    with st.expander("可复现性", expanded=False):
        seed_control("sbd_seed")

def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    raw, err = _load_raw_df()
    if err:
        return None, None, err, HELP_TEXT

    cols = raw.columns.tolist()
    if len(cols) < 2:
        return None, None, "输入数据至少需要两列数值数据。", HELP_TEXT

    x_col = st.session_state.get("sbd_x_col", _default_col(cols, "x", 0))
    y_col = st.session_state.get("sbd_y_col", _default_col(cols, "y", 1 if len(cols) > 1 else 0))
    group_col = st.session_state.get("sbd_group_col", "None")
    if group_col == "None":
        group_col = None

    if x_col not in cols or y_col not in cols:
        return None, None, "请选择有效的 x / y 列。", HELP_TEXT

    df = _prepare_df(raw, x_col, y_col, group_col)
    if df.empty:
        return None, None, "有效数据为空，请检查 x / y 列是否为数值。", HELP_TEXT

    shared["data"] = df[["x", "y", "group"]].copy()

    # 读取参数
    xlabel = st.session_state.get("sbd_xlabel", "X title")
    ylabel = st.session_state.get("sbd_ylabel", "Y title")
    axis_title_size = st.session_state.get("sbd_axis_title_size", 20)

    scatter_fill = _safe_color(st.session_state.get("sbd_scatter_fill", theme.get("scatter_fill")), "#EDBB47")
    scatter_edge = _safe_color(st.session_state.get("sbd_scatter_edge", theme.get("line_default")), "#000000")
    reg_color = _safe_color(st.session_state.get("sbd_reg_color", theme.get("reg_color")), "#F77423")
    point_alpha = st.session_state.get("sbd_point_alpha", 0.5)
    point_size = st.session_state.get("sbd_point_size", 3.0) * 2  # Plotly 中大小比例不同
    point_stroke = st.session_state.get("sbd_point_stroke", 0.8)
    point_marker = MARKER_MAP.get(st.session_state.get("sbd_point_shape", "圆形"), "circle")
    show_border = st.session_state.get("sbd_show_border", True)
    border_color = _safe_color(st.session_state.get("sbd_border_color", theme.get("border_color")), "#EDBB47")
    border_width = st.session_state.get("sbd_border_width", 0.8)

    xtick_size = st.session_state.get("sbd_xtick_size", 20)
    xtick_color = _safe_color(st.session_state.get("sbd_xtick_color", theme.get("text")), "#000000")
    xtick_angle = st.session_state.get("sbd_xtick_angle", 0)
    xlabel_family = st.session_state.get("sbd_xlabel_family", "sans-serif")
    ytick_size = st.session_state.get("sbd_ytick_size", 20)
    ytick_color = _safe_color(st.session_state.get("sbd_ytick_color", theme.get("text")), "#000000")
    ytick_angle = st.session_state.get("sbd_ytick_angle", 90)
    ylabel_family = st.session_state.get("sbd_ylabel_family", "sans-serif")

    theme_text_color = _safe_color(theme.get("text"), "#000000")
    theme_line_color = _safe_color(theme.get("line_default"), "#000000")

    # 边际图参数
    right_violin_fill = _safe_color(st.session_state.get("sbd_right_violin_fill", theme.get("sbd_right_violin_fill")), "#FFEAB5")
    right_box_fill = _safe_color(st.session_state.get("sbd_right_box_fill", theme.get("sbd_right_box_fill")), "#FFE570")
    right_box_edge = _safe_color(st.session_state.get("sbd_right_box_edge", theme.get("line_default")), "#000000")
    right_point_fill = _safe_color(st.session_state.get("sbd_right_point_fill", theme.get("sbd_right_point_fill")), "#A899E5")
    right_point_edge = _safe_color(st.session_state.get("sbd_right_point_edge", theme.get("line_default")), "#000000")
    right_violin_width = st.session_state.get("sbd_right_violin_width", 0.5)
    right_box_width = st.session_state.get("sbd_right_box_width", 0.1)
    right_box_lw = st.session_state.get("sbd_right_box_lw", 1.2)
    right_jitter = st.session_state.get("sbd_right_jitter", 0.12)
    right_point_size = st.session_state.get("sbd_right_point_size", 3.0) * 2
    right_point_alpha = st.session_state.get("sbd_right_point_alpha", 0.5)
    right_point_stroke = st.session_state.get("sbd_right_point_stroke", 0.8)
    right_point_marker = MARKER_MAP.get(st.session_state.get("sbd_right_point_shape", "圆形"), "circle")

    top_violin_fill = _safe_color(st.session_state.get("sbd_top_violin_fill", theme.get("sbd_top_violin_fill")), "#FFCBB5")
    top_box_fill = _safe_color(st.session_state.get("sbd_top_box_fill", theme.get("sbd_top_box_fill")), "#FF6E26")
    top_box_edge = _safe_color(st.session_state.get("sbd_top_box_edge", theme.get("line_default")), "#000000")
    top_point_fill = _safe_color(st.session_state.get("sbd_top_point_fill", theme.get("sbd_top_point_fill")), "#FFB8DF")
    top_point_edge = _safe_color(st.session_state.get("sbd_top_point_edge", theme.get("line_default")), "#000000")
    top_violin_width = st.session_state.get("sbd_top_violin_width", 0.5)
    top_box_width = st.session_state.get("sbd_top_box_width", 0.1)
    top_box_lw = st.session_state.get("sbd_top_box_lw", 1.2)
    top_jitter = st.session_state.get("sbd_top_jitter", 0.12)
    top_point_size = st.session_state.get("sbd_top_point_size", 3.0) * 2
    top_point_alpha = st.session_state.get("sbd_top_point_alpha", 0.5)
    top_point_stroke = st.session_state.get("sbd_top_point_stroke", 0.8)
    top_point_marker = MARKER_MAP.get(st.session_state.get("sbd_top_point_shape", "圆形"), "circle")

    h_px = st.session_state.get("sbd_h", 600)
    w_px = st.session_state.get("sbd_w", 600)

    # 创建子图布局
    fig = make_subplots(
        rows=2, cols=2,
        shared_xaxes=True, shared_yaxes=True,
        column_widths=[0.85, 0.15],
        row_heights=[0.15, 0.85],
        horizontal_spacing=0.02,
        vertical_spacing=0.02,
        subplot_titles=("", "", "", ""),
    )

    # 主图：散点图（有 group 时按组着色）
    group_colors = {}
    if "group" in df.columns and df["group"].nunique() > 1:
        palette = ["#D96C4F", "#2E7D8F", "#7FA65A", "#8E6FA8", "#C9A227", "#4E79A7"]
        for idx, g in enumerate(pd.unique(df["group"])):
            group_colors[g] = palette[idx % len(palette)]

    if group_colors:
        for g, color in group_colors.items():
            sub = df[df["group"] == g]
            fig.add_trace(
                go.Scatter(
                    x=sub["x"], y=sub["y"],
                    mode='markers',
                    marker=dict(
                        size=point_size,
                        color=color,
                        opacity=point_alpha,
                        symbol=point_marker,
                        line=dict(color=scatter_edge, width=point_stroke)
                    ),
                    name=str(g),
                    showlegend=False,
                    hovertemplate='x: %{x}<br>y: %{y}<extra></extra>'
                ),
                row=2, col=1
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=df["x"], y=df["y"],
                mode='markers',
                marker=dict(
                    size=point_size,
                    color=scatter_fill,
                    opacity=point_alpha,
                    symbol=point_marker,
                    line=dict(color=scatter_edge, width=point_stroke)
                ),
                name="Data",
                showlegend=False,
                hovertemplate='x: %{x}<br>y: %{y}<extra></extra>'
            ),
            row=2, col=1
        )

    # 主图：回归线（有分组时每组一条，按分组着色）
    if len(df) >= 2:
        line_groups = [(None, df)] if not group_colors else list(group_colors.items())
        for g, sub in line_groups:
            if len(sub) < 2:
                continue
            coef = np.polyfit(sub["x"], sub["y"], 1)
            a, b = coef[0], coef[1]
            x_line = np.linspace(sub["x"].min(), sub["x"].max(), 100)
            y_line = a * x_line + b
            color = group_colors.get(g, reg_color) if g is not None else reg_color
            fig.add_trace(
                go.Scatter(
                    x=x_line, y=y_line,
                    mode='lines',
                    line=dict(color=color, width=1.8),
                    name="Regression" if g is None else f"fit-{g}",
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=2, col=1
            )
            if g is not None:
                fig.add_annotation(
                    x=float(x_line[-1]), y=float(y_line[-1]),
                    text=f"y = {a:.2f}x {b:+.2f}",
                    showarrow=False,
                    xanchor="right", yanchor="bottom",
                    font=dict(size=9, color=color),
                    row=2, col=1,
                )
            else:
                a_main, b_main = a, b
        # 显示整体相关系数
        r = np.corrcoef(df["x"], df["y"])[0, 1]
        a0, b0 = np.polyfit(df["x"], df["y"], 1)
        annotation_text = f"Pearson r = {r:.3f}<br>y = {a0:.3f}x + {b0:.3f}"
        fig.add_annotation(
            # 放到主图左上角（该区域数据稀疏），避免压住顶部边际小提琴
            x=0.02, y=0.97, xref="x3 domain", yref="y3 domain",
            xanchor="left", yanchor="top",
            text=annotation_text,
            showarrow=False,
            font=dict(size=11, color=reg_color),
            align="left",
            bgcolor="rgba(255,255,255,0.7)",
            bordercolor=reg_color,
            borderwidth=0.5,
            borderpad=4
        )

    # 主图：边框
    if show_border:
        # Plotly 中边框通过 update_xaxes/update_yaxes 的 linecolor 设置
        fig.update_xaxes(linecolor=border_color, linewidth=border_width, row=2, col=1)
        fig.update_yaxes(linecolor=border_color, linewidth=border_width, row=2, col=1)
    else:
        fig.update_xaxes(showline=False, row=2, col=1)
        fig.update_yaxes(showline=False, row=2, col=1)

    # 顶部边际图 (row=1, col=1) - 水平方向
    x_vals = df["x"].values
    # 半小提琴（只显示上半部分，使用 side='positive' 并放在 y=0 上方）
    fig.add_trace(
        go.Violin(
            x=x_vals,
            y=np.zeros_like(x_vals),
            orientation='h',
            side='positive',
            line=dict(color=theme_line_color, width=1),
            fillcolor=top_violin_fill,
            opacity=1.0,
            points=False,
            box_visible=False,
            meanline_visible=False,
            spanmode='hard',
            width=top_violin_width,
            name="Top Violin",
            showlegend=False,
            hoverinfo='skip'
        ),
        row=1, col=1
    )
    # 箱线图（水平方向，放在 y=0 位置，宽度很小）
    fig.add_trace(
        go.Box(
            x=x_vals,
            y=np.zeros_like(x_vals),
            orientation='h',
            boxmean=False,
            boxpoints=False,
            line=dict(color=top_box_edge, width=top_box_lw),
            fillcolor=top_box_fill,
            opacity=1.0,
            width=top_box_width,
            showlegend=False,
            hoverinfo='skip'
        ),
        row=1, col=1
    )
    # 抖动点
    rng = rng_for("sbd_seed")
    y_jitter = rng.normal(0, top_jitter, len(x_vals))
    fig.add_trace(
        go.Scatter(
            x=x_vals, y=y_jitter,
            mode='markers',
            marker=dict(
                size=top_point_size,
                color=top_point_fill,
                opacity=top_point_alpha,
                symbol=top_point_marker,
                line=dict(color=top_point_edge, width=top_point_stroke)
            ),
            showlegend=False,
            hoverinfo='skip'
        ),
        row=1, col=1
    )

    # 右侧边际图 (row=2, col=2) - 垂直方向
    y_vals = df["y"].values
    # 半小提琴（只显示右侧半，使用 side='positive' 并放在 x=0 右侧）
    fig.add_trace(
        go.Violin(
            x=np.zeros_like(y_vals), y=y_vals,
            orientation='v',
            side='positive',
            line=dict(color=theme_line_color, width=1),
            fillcolor=right_violin_fill,
            opacity=1.0,
            points=False,
            box_visible=False,
            meanline_visible=False,
            spanmode='hard',
            width=right_violin_width,
            name="Right Violin",
            showlegend=False,
            hoverinfo='skip'
        ),
        row=2, col=2
    )
    # 箱线图（垂直方向，放在 x=0 位置）
    fig.add_trace(
        go.Box(
            x=np.zeros_like(y_vals), y=y_vals,
            orientation='v',
            boxmean=False,
            boxpoints=False,
            line=dict(color=right_box_edge, width=right_box_lw),
            fillcolor=right_box_fill,
            opacity=1.0,
            width=right_box_width,
            showlegend=False,
            hoverinfo='skip'
        ),
        row=2, col=2
    )
    # 抖动点
    x_jitter = rng.normal(0, right_jitter, len(y_vals))
    fig.add_trace(
        go.Scatter(
            x=x_jitter, y=y_vals,
            mode='markers',
            marker=dict(
                size=right_point_size,
                color=right_point_fill,
                opacity=right_point_alpha,
                symbol=right_point_marker,
                line=dict(color=right_point_edge, width=right_point_stroke)
            ),
            showlegend=False,
            hoverinfo='skip'
        ),
        row=2, col=2
    )

    # 坐标轴样式
    # 主图 x 轴
    fig.update_xaxes(
        title_text=xlabel, title_font=dict(size=axis_title_size, family=xlabel_family, color=theme_text_color),
        tickfont=dict(size=xtick_size, color=xtick_color), tickangle=xtick_angle,
        showgrid=False, row=2, col=1
    )
    # 主图 y 轴
    fig.update_yaxes(
        title_text=ylabel, title_font=dict(size=axis_title_size, family=ylabel_family, color=theme_text_color),
        tickfont=dict(size=ytick_size, color=ytick_color), tickangle=ytick_angle,
        showgrid=False, row=2, col=1
    )
    # 顶部边际图 x 轴与主图共享，但需要隐藏标题和刻度
    fig.update_xaxes(showticklabels=False, title_text="", row=1, col=1)
    fig.update_yaxes(showticklabels=False, title_text="", range=[-0.5, 0.5], row=1, col=1)
    # 右侧边际图 y 轴与主图共享，隐藏标题和刻度
    fig.update_xaxes(showticklabels=False, title_text="", range=[-0.5, 0.5], row=2, col=2)
    fig.update_yaxes(showticklabels=False, title_text="", row=2, col=2)

    # 整体布局
    fig.update_layout(
        plot_bgcolor=_safe_color(theme.get("bg"), "#f5f7fb"),
        paper_bgcolor=_safe_color(theme.get("bg"), "#f5f7fb"),
        width=w_px, height=h_px,
        margin=dict(l=60, r=40, t=80, b=50),
        hovermode='closest'
    )
    # theme_bw：不显示零线，仅保留主图边框
    fig.update_xaxes(zeroline=False, showgrid=False)
    fig.update_yaxes(zeroline=False, showgrid=False)
    # 边际图坐标范围固定，保证半小提琴的宽度能撑满边际条带
    fig.update_yaxes(range=[-0.02, 0.55], row=1, col=1)
    fig.update_xaxes(range=[-0.02, 0.55], row=2, col=2)

    shared["last_plotly"] = fig
    shared["status"] = f"ScaBoxDen 图已生成，共 {len(df)} 条记录。"
    shared["help_text"] = HELP_TEXT
    return fig, df[["x", "y", "group"]], shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render
