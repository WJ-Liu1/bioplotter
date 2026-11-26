from __future__ import annotations

import csv
import itertools
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.palettes import SCI_DIST_COLORS
from app.core.theme import THEMES
from app.core.random_seed import rng_for, seed_control

HELP_TEXT = """
Raincloud Plot (Plotly 交互版本)
输入数据格式：
  - 支持宽表：每列代表一个 condition
  - 支持长表：至少包含 condition/group 与 value 两列
  - 上传 txt / csv / tsv / xlsx 后，可自动识别或手动指定格式
功能：
  - 半小提琴 / 全小提琴
  - 箱线图
  - 抖动点 / 蜜蜂点近似
  - 平均值与误差线
  - 两两比较与多组比较
  - 水平参考线
  - 翻转坐标轴
说明：
  - 本模块使用 Plotly 实现，支持缩放、悬停等交互
  - 视觉布局采用经典雨云图样式
"""

PALETTES = [
    "SCI", "default", "Set1", "Set2", "Set3", "Pastel1", "Pastel2", "Dark2", "Paired",
    "Blues", "Greens", "Oranges", "Purples", "Reds", "Spectral", "RdYlBu",
    "RdYlGn", "coolwarm", "viridis", "magma", "plasma", "cividis",
    "NPG", "AAAS", "NEJM", "Lancet", "JAMA", "JCO", "UCSCGB", "IGV", "UChicago",
    "The Simpsons",
]

STYLE_MAP = {
    "Default (Grey)": "plotly",
    "Black & White": "plotly_white",
    "Linedraw": "plotly",
    "Light": "plotly",
    "Dark": "plotly_dark",
    "Minimal": "plotly",
    "Classic": "plotly",
    "Void": "plotly",
    "Cowplot": "plotly",
}

SCIENTIFIC_PALETTES = {
    "SCI": list(SCI_DIST_COLORS),
    "NPG": ["#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F", "#8491B4", "#91D1C2", "#DC0000"],
    "AAAS": ["#3B4992", "#EE0000", "#008B45", "#631879", "#008280", "#BB0021", "#5F559B", "#A20056"],
    "NEJM": ["#BC3C29", "#0072B5", "#E18727", "#20854E", "#7876B1", "#6F99AD", "#FFDC91", "#EE4C97"],
    "Lancet": ["#00468B", "#ED0000", "#42B540", "#0099B4", "#925E9F", "#FDAF91", "#AD002A", "#ADB6B6"],
    "JAMA": ["#374E55", "#DF8F44", "#00A1D5", "#B24745", "#79AF97", "#6A6599", "#80796B"],
    "JCO": ["#0073C2", "#EFC000", "#868686", "#CD534C", "#7AA6DC", "#003C67", "#8F7700", "#3B3B3B"],
    "UCSCGB": ["#FF0000", "#00A08A", "#F2AD00", "#F98400", "#5BBCD6", "#A52A2A", "#46ACC8", "#E58601"],
    "IGV": ["#5050FF", "#CE3D32", "#749B58", "#F0E442", "#CC79A7", "#56B4E9", "#009E73", "#E69F00"],
    "UChicago": ["#800000", "#C16622", "#8A9045", "#155F83", "#350E20", "#5B8FA8", "#A97C50", "#767676"],
    "The Simpsons": ["#FED439", "#709AE1", "#8A9197", "#D2AF81", "#FD7446", "#D5E4A2", "#197EC0", "#F05C3B"],
}

def _sample_df() -> pd.DataFrame:
    sample_path = get_sample_path("raincloud")
    return pd.read_csv(sample_path, sep="\t", decimal=',')

def _sample_download_bytes() -> bytes:
    return sample_bytes("raincloud")

def _load_uploaded_table(uploaded, header: bool, sep: str, decimal_point: str, quote_mode: str):
    if uploaded is None:
        return None, "请先上传数据文件。"
    name = uploaded.name.lower()
    header_row = 0 if header else None
    if quote_mode == "无":
        quoting = csv.QUOTE_NONE
        quotechar = '"'
    elif quote_mode == "单引号":
        quoting = csv.QUOTE_MINIMAL
        quotechar = "'"
    else:
        quoting = csv.QUOTE_MINIMAL
        quotechar = '"'
    decimal = '.' if decimal_point == 'Point' else ','
    try:
        if name.endswith(".xlsx"):
            df = pd.read_excel(uploaded, header=header_row)
        else:
            df = pd.read_csv(
                uploaded,
                sep=sep,
                header=header_row,
                decimal=decimal,
                quoting=quoting,
                quotechar=quotechar,
                engine="python",
            )
        if not header:
            df.columns = [f"V{i+1}" for i in range(df.shape[1])]
        return df, None
    except Exception as exc:
        return None, f"文件读取失败：{exc}"

def _load_raw_df():
    use_sample = st.session_state.get("rc_use_sample", True)
    if use_sample:
        return _sample_df(), None
    uploaded = st.session_state.get("rc_file")
    header = st.session_state.get("rc_header", True)
    sep_label = st.session_state.get("rc_sep", "Tab")
    decimal_point = st.session_state.get("rc_decimal", ".")
    quote_mode = st.session_state.get("rc_quote", "双引号")
    sep_map = {"Comma": ",", "Semicolon": ";", "Tab": "	"}
    sep = sep_map.get(sep_label, "	")
    return _load_uploaded_table(uploaded, header, sep, decimal_point, quote_mode)

def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).replace("﻿", "").strip() for c in out.columns]
    return out

def _detect_long_columns(raw: pd.DataFrame):
    work = _clean_columns(raw)
    lower = {str(c).strip().lower(): c for c in work.columns}
    cond_candidates = ["condition", "group", "class", "category", "sample", "treatment"]
    value_candidates = ["value", "y", "measurement", "score", "abundance", "expression"]
    cond = next((lower[c] for c in cond_candidates if c in lower), None)
    val = next((lower[c] for c in value_candidates if c in lower), None)
    if cond and val:
        return cond, val
    return None, None

def _normalize_long_df(raw: pd.DataFrame, condition_col: str, value_col: str):
    work = raw[[condition_col, value_col]].copy()
    work.columns = ["condition", "value"]
    work["condition"] = work["condition"].astype(str).str.strip()
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["value"])
    work = work[work["condition"] != ""].copy()
    return work

def _melt_data(raw: pd.DataFrame, selected_cols: list[str]) -> pd.DataFrame:
    work = raw[selected_cols].copy()
    for col in work.columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    long_df = work.melt(var_name="condition", value_name="value").dropna(subset=["value"]).copy()
    long_df["condition"] = pd.Categorical(long_df["condition"], categories=selected_cols, ordered=True)
    return long_df

def _get_palette(name: str, n: int):
    """返回十六进制颜色列表，确保所有颜色都是字符串格式"""
    if name == "default":
        import seaborn as sns
        colors = sns.color_palette("Set2", n)
    elif name in SCIENTIFIC_PALETTES:
        colors = SCIENTIFIC_PALETTES[name][:n]
        if len(colors) < n:
            reps = (n // len(colors)) + 1
            colors = (colors * reps)[:n]
    else:
        try:
            import seaborn as sns
            colors = sns.color_palette(name, n)
        except Exception:
            import seaborn as sns
            colors = sns.color_palette("Set2", n)
    # 转换为十六进制字符串
    hex_colors = []
    for c in colors:
        if isinstance(c, str) and c.startswith('#'):
            hex_colors.append(c)
        elif isinstance(c, (tuple, list)) and len(c) >= 3:
            # 如果值是 0-1 浮点数，转换为 0-255
            r, g, b = c[0], c[1], c[2]
            if max(r, g, b) <= 1.0:
                r, g, b = int(r*255), int(g*255), int(b*255)
            hex_colors.append('#{:02x}{:02x}{:02x}'.format(r, g, b))
        else:
            hex_colors.append(str(c))
    return hex_colors

def _safe_color(c, default):
    if c is None:
        return default
    if isinstance(c, float) and np.isnan(c):
        return default
    if isinstance(c, str):
        c_stripped = c.strip().lower()
        if c_stripped == 'nan':
            return default
        if c_stripped.startswith('#'):
            return c_stripped
        color_map = {
            "black": "#000000", "white": "#FFFFFF", "red": "#FF0000",
            "green": "#008000", "blue": "#0000FF", "gray": "#808080",
            "grey": "#808080", "lightgray": "#D3D3D3", "darkgray": "#A9A9A9",
            "orange": "#FFA500", "yellow": "#FFFF00", "purple": "#800080",
            "pink": "#FFC0CB"
        }
        return color_map.get(c_stripped, default)
    # 处理元组或列表
    if isinstance(c, (tuple, list)) and len(c) >= 3:
        r, g, b = c[0], c[1], c[2]
        if max(r, g, b) <= 1.0:
            r, g, b = int(r*255), int(g*255), int(b*255)
        return '#{:02x}{:02x}{:02x}'.format(r, g, b)
    return default

def _color_with_alpha(color, alpha):
    if alpha >= 1.0:
        return color
    # 如果是元组或列表，先转换为十六进制
    if isinstance(color, (tuple, list)) and len(color) >= 3:
        r, g, b = color[0], color[1], color[2]
        if max(r, g, b) <= 1.0:
            r, g, b = int(r*255), int(g*255), int(b*255)
        color = '#{:02x}{:02x}{:02x}'.format(r, g, b)
    if not isinstance(color, str) or not color.startswith('#'):
        return color
    r = int(color[1:3], 16) / 255.0
    g = int(color[3:5], 16) / 255.0
    b = int(color[5:7], 16) / 255.0
    return f"rgba({r*255:.0f}, {g*255:.0f}, {b*255:.0f}, {alpha})"

def _bw_nrd0(values: np.ndarray) -> float:
    """nrd0 带宽：0.9 * min(sd, IQR/1.34) * n^(-1/5)。"""
    n = len(values)
    if n < 2:
        return 0.0
    sd = float(np.std(values, ddof=1))
    q75, q25 = np.percentile(values, [75, 25])
    iqr = float(q75 - q25)
    spread = min(sd, iqr / 1.34) if iqr > 0 else sd
    return 0.9 * spread * n ** (-0.2)


def _kde_curve(values: np.ndarray, adjust: float = 1.0, n: int = 256):
    """高斯核密度估计，支持带宽缩放。"""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2 or np.ptp(values) == 0:
        return None
    bw = _bw_nrd0(values) * max(float(adjust), 0.01)
    if not np.isfinite(bw) or bw <= 0:
        bw = max(float(np.std(values)) * 0.2, 1e-6)
    lo, hi = float(values.min()) - 3 * bw, float(values.max()) + 3 * bw
    grid = np.linspace(lo, hi, n)
    z = (grid[:, None] - values[None, :]) / bw
    dens = np.exp(-0.5 * z * z).sum(axis=1) / (values.size * bw * np.sqrt(2 * np.pi))
    return grid, dens, float(values.min()), float(values.max())


def _beeswarm_offsets(values, max_width: float):
    if len(values) == 0:
        return np.array([])
    order = np.argsort(values)
    offsets = np.zeros(len(values))
    step = max_width / 6 if max_width > 0 else 0.01
    seq = [0.0]
    for i in range(1, len(values)):
        k = (i + 1) // 2
        seq.append(k * step if i % 2 else -k * step)
    for idx, original_idx in enumerate(order):
        offsets[original_idx] = seq[idx]
    return offsets

def _stars(p: float) -> str:
    if p < 0.0001:
        return "****"
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"

def _safe_stat_tests():
    try:
        from scipy import stats
        return stats
    except Exception:
        return None

def _pairwise_pvalue(a, b, method: str):
    stats = _safe_stat_tests()
    if stats is None:
        return None
    a = pd.Series(a).dropna().astype(float)
    b = pd.Series(b).dropna().astype(float)
    if len(a) < 2 or len(b) < 2:
        return None
    if method == "t.test":
        return float(stats.ttest_ind(a, b, equal_var=False, nan_policy="omit").pvalue)
    return float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)

def _multiple_pvalue(groups, method: str):
    stats = _safe_stat_tests()
    if stats is None:
        return None
    arrays = [pd.Series(g).dropna().astype(float) for g in groups]
    arrays = [g for g in arrays if len(g) >= 2]
    if len(arrays) < 2:
        return None
    if method == "anova":
        return float(stats.f_oneway(*arrays).pvalue)
    return float(stats.kruskal(*arrays).pvalue)

def controls(shared: dict) -> None:
    st.markdown("### Data")
    sample_loader_control("rc_use_sample", "raincloud", "rc_load_sample_btn")
    if not st.session_state.get("rc_use_sample", True):
        st.file_uploader(
            "File input",
            type=["txt", "csv", "tsv", "xlsx"],
            key="rc_file",
        )
    st.download_button(
        "下载示例数据",
        data=_sample_download_bytes(),
        file_name="raincloud_sample.txt",
        mime="text/tab-separated-values",
        width="stretch",
    )
    st.checkbox("Header", value=True, key="rc_header")
    st.radio("输入数据结构", ["自动识别", "宽表", "长表"], horizontal=True, key="rc_input_mode")
    st.radio("Decimal separator", ["Point", "Comma"], horizontal=True, key="rc_decimal_label")
    st.session_state["rc_decimal"] = "." if st.session_state.get("rc_decimal_label", "Point") == "Point" else ","
    st.radio("Column Delimiter", ["Comma", "Semicolon", "Tab"], horizontal=True, key="rc_sep")
    st.radio("Quote", ["无", "双引号", "单引号"], horizontal=True, key="rc_quote")

    raw, err = _load_raw_df()
    if raw is not None and not raw.empty:
        raw = _clean_columns(raw)
        cond_guess, val_guess = _detect_long_columns(raw)
        numeric_cols = [c for c in raw.columns if pd.to_numeric(raw[c], errors="coerce").notna().sum() > 0]
        detected_long = st.session_state.get("rc_input_mode", "自动识别") == "长表" or (
            st.session_state.get("rc_input_mode", "自动识别") == "自动识别" and cond_guess and val_guess
        )
        if detected_long:
            st.selectbox("Condition 列", options=list(raw.columns), index=list(raw.columns).index(cond_guess) if cond_guess in raw.columns else 0, key="rc_condition_col")
            value_index = list(raw.columns).index(val_guess) if val_guess in raw.columns else min(1, len(raw.columns)-1)
            st.selectbox("Value 列", options=list(raw.columns), index=value_index, key="rc_value_col")
            cats = []
            try:
                tmp = _normalize_long_df(raw, st.session_state.get("rc_condition_col", cond_guess or raw.columns[0]), st.session_state.get("rc_value_col", val_guess or raw.columns[min(1, len(raw.columns)-1)]))
                cats = list(pd.unique(tmp["condition"]).tolist())
            except Exception:
                pass
            if cats:
                default_cats = cats[: min(6, len(cats))]
                st.multiselect("Detected conditions", options=cats, default=st.session_state.get("rc_filter_conditions", default_cats), key="rc_filter_conditions")
        else:
            default_cols = numeric_cols[: min(4, len(numeric_cols))]
            st.multiselect(
                "Detected columns",
                options=numeric_cols,
                default=st.session_state.get("rc_filter_columns", default_cols),
                key="rc_filter_columns",
                help="用于过滤、排序或移除不需要的列",
            )
    else:
        if err:
            st.caption(err)
        else:
            st.caption("上传数据后可选择需要绘图的列。")

    st.markdown("---")
    with st.expander("General Options", expanded=True):
        st.number_input("Plot Height", min_value=300, max_value=2000, value=600, step=10, key="rc_height")
        st.number_input("Plot Width", min_value=300, max_value=2000, value=600, step=10, key="rc_width")
        st.checkbox("Show Legend", value=True, key="rc_plot_legend")
        st.checkbox("Make it rain! (Flip the Axis)", value=True, key="rc_plot_flip")
        st.checkbox("Plot Major Grid", value=False, key="rc_plot_major_grid")
        if st.session_state.get("rc_plot_major_grid", False):
            st.checkbox("Plot Minor Grid", value=False, key="rc_plot_minor_grid")
        st.checkbox("Show Horizontal Line", value=False, key="rc_horizontal_line")
        if st.session_state.get("rc_horizontal_line", False):
            st.number_input("Position", value=100.0, key="rc_horizontal_line_position")
            st.selectbox("Linetype", ["solid", "dashed", "dotted", "dashdot"], key="rc_horizontal_line_type")
            st.slider("Line Size", 0.0, 2.0, 0.2, 0.1, key="rc_horizontal_line_size")
            st.slider("Transparency", 0.0, 1.0, 1.0, 0.05, key="rc_horizontal_line_alpha")

    with st.expander("Theme and Colors", expanded=False):
        st.selectbox("Theme", list(STYLE_MAP.keys()), index=8, key="rc_plot_theme")
        st.selectbox("Palette", PALETTES, index=PALETTES.index("Set1"), key="rc_plot_palette")

    with st.expander("Titles", expanded=False):
        st.text_input("Main Plot Title", value="Main Plot Title", key="rc_plot_title")
        st.text_input("x Axis Title", value="x Axis Title", key="rc_x_title")
        st.text_input("y Axis Title", value="y Axis Title", key="rc_y_title")
        st.number_input("Main Title Font Size", min_value=0, value=20, key="rc_title_font_size")
        st.number_input("Axis Title Font Size", min_value=0, value=15, key="rc_axis_label_font_size")

    with st.expander("Scale", expanded=False):
        st.number_input("Scale Text Font Size", min_value=0, value=12, key="rc_scale_font_size")
        st.number_input("X Axis Scale Angle", min_value=0, max_value=360, value=0, key="rc_x_axis_angle")
        st.selectbox("Horizontal Scale Justification", ["Left", "Middle", "Right"], index=0, key="rc_x_hjust")
        st.selectbox("Vertical Scale Justification", ["Top", "Middle", "Bottom"], index=0, key="rc_x_vjust")
        st.checkbox("Automatic Scale Limits", value=True, key="rc_auto_scale")
        if not st.session_state.get("rc_auto_scale", True):
            st.number_input("Min Scale Limit", value=0.0, key="rc_min_scale")
            st.number_input("Max Scale Limit", value=150.0, key="rc_max_scale")

    with st.expander("Dots", expanded=False):
        st.checkbox("Plot Data Points", value=True, key="rc_plot_dots")
        if st.session_state.get("rc_plot_dots", True):
            st.selectbox("Column Type", ["Jitter", "Beeswarm"], index=0, key="rc_dot_column_type")
            st.number_input("Dot Size", min_value=0.1, value=2.0, step=0.1, key="rc_dot_size")
            st.selectbox("Dot Shape", ["Empty Dot", "Filled Dot", "Square", "Triangle"], index=1, key="rc_dot_shape")
            st.slider("Plot Width", 0.0, 0.5, 0.15, 0.05, key="rc_dots_width")
            st.slider("Transparency", 0.0, 1.0, 1.0, 0.05, key="rc_dot_alpha")
        seed_control("rc_seed")

    with st.expander("Violin", expanded=False):
        st.checkbox("Plot Violins", value=True, key="rc_plot_violins")
        if st.session_state.get("rc_plot_violins", True):
            st.selectbox("Type of Violin", ["Full Violin", "Half Violin"], index=1, key="rc_violin_type")
            st.slider("Center Offset", 0.0, 0.5, 0.20, 0.05, key="rc_violin_nudge")
            st.selectbox("Scale of the violin", ["Same Area", "Maximum Width"], index=1, key="rc_violin_scale")
            st.number_input("Bandwidth Adjustment", min_value=1.0, value=2.0, step=0.5, key="rc_violin_adjust")
            st.checkbox("Trim Edges to Data Points", value=True, key="rc_violin_trim")
            if st.session_state.get("rc_violin_type", "Half Violin") == "Full Violin":
                st.checkbox("Draw 50% Quantile", value=True, key="rc_violin_quantiles")
            st.slider("Transparency", 0.0, 1.0, 0.6, 0.05, key="rc_violin_alpha")

    with st.expander("Boxplot", expanded=False):
        st.checkbox("Plot Boxplots", value=True, key="rc_boxplots")
        if st.session_state.get("rc_boxplots", True):
            st.checkbox("Add Notch", value=False, key="rc_boxplot_notch")
            st.checkbox("Width Proportional to Data", value=False, key="rc_boxplot_varwidth")
            st.checkbox("Plot Outliers", value=False, key="rc_boxplot_outliers")
            st.slider("Boxplot Width", 0.0, 0.5, 0.1, 0.05, key="rc_boxplot_width")
            st.slider("Center Offset", 0.0, 0.5, 0.20, 0.05, key="rc_boxplot_nudge")
            st.slider("Transparency", 0.0, 1.0, 0.3, 0.05, key="rc_boxplot_alpha")

    with st.expander("Statistics", expanded=False):
        st.checkbox("Compare the means", value=False, key="rc_statistics")
        if st.session_state.get("rc_statistics", False):
            st.selectbox("Type of Test", ["Parametric", "Non-parametric"], index=1, key="rc_stats_type")
            if st.session_state.get("rc_stats_type", "Non-parametric") == "Parametric":
                st.checkbox("Pairwise (T-test)", value=False, key="rc_stats_ttest")
                st.checkbox("Multiple (ANOVA)", value=False, key="rc_stats_anova")
            else:
                st.checkbox("Pairwise (Wilcoxon Test)", value=False, key="rc_stats_wilcoxon")
                st.checkbox("Multiple (Kruskal-Wallis)", value=False, key="rc_stats_kruskal")
            cols = st.session_state.get("rc_filter_columns", [])
            if len(cols) >= 2:
                combos = [f"{a} vs {b}" for a, b in itertools.combinations(cols, 2)]
                st.multiselect("Conditions To Test", combos, default=combos, key="rc_stats_combinations")
            st.selectbox("Pairwise value Format", ["Significance (stars)", "p-values"], index=0, key="rc_stats_label_format")
            st.number_input("Multiple Significance Label Y height", value=0.0, key="rc_stats_label_y")
            st.checkbox("Plot mean", value=False, key="rc_stats_mean")
            if st.session_state.get("rc_stats_mean", False):
                st.selectbox(
                    "Add error bars to the mean",
                    ["None", "95% Confidence Interval", "Standard Error", "Standard Deviation"],
                    index=0,
                    key="rc_stats_mean_error",
                )
                st.slider("Mean Width", 0.0, 1.0, 0.5, 0.05, key="rc_stats_mean_width")
                st.slider("Center Offset", 0.0, 0.5, 0.20, 0.05, key="rc_stats_mean_nudge")
                st.slider("Line Size", 0.0, 2.0, 0.2, 0.1, key="rc_stats_mean_size")

def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    raw, err = _load_raw_df()
    if err:
        return None, None, err, HELP_TEXT
    if raw is None or raw.empty:
        return None, None, "没有可用数据。", HELP_TEXT

    raw = _clean_columns(raw)
    input_mode = st.session_state.get("rc_input_mode", "自动识别")
    cond_guess, val_guess = _detect_long_columns(raw)
    use_long = input_mode == "长表" or (input_mode == "自动识别" and cond_guess and val_guess)

    if use_long:
        condition_col = st.session_state.get("rc_condition_col", cond_guess or raw.columns[0])
        value_col = st.session_state.get("rc_value_col", val_guess or raw.columns[min(1, len(raw.columns)-1)])
        if condition_col not in raw.columns or value_col not in raw.columns:
            return None, None, "长表模式下请选择有效的 condition/value 列。", HELP_TEXT
        plot_df = _normalize_long_df(raw, condition_col, value_col)
        selected_conditions = st.session_state.get("rc_filter_conditions", [])
        if selected_conditions:
            plot_df = plot_df[plot_df["condition"].isin(selected_conditions)].copy()
        selected_cols = list(pd.unique(plot_df["condition"]).tolist())
        plot_df["condition"] = pd.Categorical(plot_df["condition"], categories=selected_cols, ordered=True)
    else:
        selected_cols = st.session_state.get("rc_filter_columns", [])
        if not selected_cols:
            numeric_cols = []
            for col in raw.columns:
                try:
                    series = pd.to_numeric(raw[col], errors='coerce')
                    if series.notna().sum() > 0:
                        numeric_cols.append(col)
                except:
                    pass
            if not numeric_cols:
                return None, None, "数据中没有数值列，请检查数据格式（示例数据可能使用了逗号作为小数点？请确认文件编码与分隔符）。", HELP_TEXT
            selected_cols = numeric_cols[: min(4, len(numeric_cols))]
        selected_cols = [c for c in selected_cols if c in raw.columns]
        if len(selected_cols) < 1:
            return None, None, "请选择至少一个有效数据列。", HELP_TEXT
        plot_df = _melt_data(raw, selected_cols)

    if plot_df.empty:
        return None, None, "选择的列没有有效数值。", HELP_TEXT

    shared["data"] = plot_df.copy()

    palette_name = st.session_state.get("rc_plot_palette", "SCI")
    colors = _get_palette(palette_name, len(selected_cols))
    color_map = {cond: colors[i] for i, cond in enumerate(selected_cols)}

    width_px = st.session_state.get("rc_width", 600)
    height_px = st.session_state.get("rc_height", 600)
    plot_flip = st.session_state.get("rc_plot_flip", True)
    show_legend = st.session_state.get("rc_plot_legend", True)

    line_color = _safe_color(theme.get("line_default"), "#4d4d4d")
    text_color = _safe_color(theme.get("text"), "#111827")
    bg_color = theme.get("bg", "#f5f7fb")

    violin_nudge = st.session_state.get("rc_violin_nudge", 0.20)
    box_nudge = st.session_state.get("rc_boxplot_nudge", 0.20)
    mean_nudge = st.session_state.get("rc_stats_mean_nudge", 0.20)
    dots_width = st.session_state.get("rc_dots_width", 0.15)

    fig = go.Figure()
    positions = np.arange(len(selected_cols))

    # 先算好每组的小提琴密度，便于 scale = area 时统一面积
    plot_violins = st.session_state.get("rc_plot_violins", True)
    violin_curves: dict[str, tuple] = {}
    if plot_violins:
        adjust = float(st.session_state.get("rc_violin_adjust", 2.0))
        for cond in selected_cols:
            vals = plot_df.loc[plot_df["condition"] == cond, "value"].to_numpy(dtype=float)
            curve = _kde_curve(vals, adjust=adjust)
            if curve is not None:
                violin_curves[cond] = curve

    # 小提琴图默认宽度是 resolution(x) * 0.9，半边即 0.45
    half_width = 0.45
    violin_scale_mode = st.session_state.get("rc_violin_scale", "Maximum Width")
    violin_width_factor: dict[str, float] = {}
    if violin_curves:
        if violin_scale_mode == "Same Area":
            # 等面积：宽度系数 1/∫d²，再归一到最大宽度 0.45
            raw = {}
            for cond, (grid, dens, _lo, _hi) in violin_curves.items():
                area = float(np.trapezoid(dens * dens, grid)) if hasattr(np, "trapezoid") else float(np.trapz(dens * dens, grid))
                raw[cond] = 1.0 / max(area, 1e-12)
            peak = max(raw[c] * float(np.max(violin_curves[c][1])) for c in raw)
            for cond in raw:
                violin_width_factor[cond] = half_width * raw[cond] / peak
        else:
            for cond, (_grid, dens, _lo, _hi) in violin_curves.items():
                violin_width_factor[cond] = half_width / max(float(np.max(dens)), 1e-12)

    for i, cond in enumerate(selected_cols):
        vals = plot_df.loc[plot_df["condition"] == cond, "value"].to_numpy()
        if len(vals) == 0:
            continue

        # 小提琴（半 / 全）
        if plot_violins and cond in violin_curves:
            violin_type = st.session_state.get("rc_violin_type", "Half Violin")
            violin_alpha = st.session_state.get("rc_violin_alpha", 0.6)
            trim = st.session_state.get("rc_violin_trim", True)
            grid, dens, lo, hi = violin_curves[cond]
            factor = violin_width_factor.get(cond, half_width)
            if trim:
                keep = (grid >= lo) & (grid <= hi)
                grid, dens = grid[keep], dens[keep]
            if len(grid) < 2:
                pass
            else:
                base = positions[i] + violin_nudge
                width_axis = factor * dens
                if plot_flip:
                    xs = list(grid) + list(grid[::-1])
                    if violin_type == "Half Violin":
                        ys = list(base + width_axis) + [base] * len(grid)
                    else:
                        ys = list(base + width_axis) + list((base - width_axis)[::-1])
                else:
                    ys = list(grid) + list(grid[::-1])
                    if violin_type == "Half Violin":
                        xs = list(base + width_axis) + [base] * len(grid)
                    else:
                        xs = list(base + width_axis) + list((base - width_axis)[::-1])
                fig.add_trace(go.Scatter(
                    x=xs, y=ys,
                    mode="lines",
                    fill="toself",
                    fillcolor=_color_with_alpha(color_map[cond], violin_alpha),
                    line=dict(color=color_map[cond], width=1),
                    opacity=1.0,
                    hoverinfo="skip",
                    showlegend=False,
                    name=cond,
                ))
            if violin_type == "Full Violin" and st.session_state.get("rc_violin_quantiles", False):
                q50 = np.nanmedian(vals)
                base = positions[i] + violin_nudge
                if plot_flip:
                    fig.add_shape(
                        type="line",
                        x0=q50, x1=q50,
                        y0=base - half_width, y1=base + half_width,
                        line=dict(color=line_color, width=1),
                        layer="above"
                    )
                else:
                    fig.add_shape(
                        type="line",
                        x0=base - half_width, x1=base + half_width,
                        y0=q50, y1=q50,
                        line=dict(color=line_color, width=1),
                        layer="above"
                    )

        # 箱线图
        if st.session_state.get("rc_boxplots", True):
            box_alpha = st.session_state.get("rc_boxplot_alpha", 0.3)
            box_width = st.session_state.get("rc_boxplot_width", 0.1)
            if plot_flip:
                fig.add_trace(go.Box(
                    y=[positions[i] + box_nudge] * len(vals),
                    x=vals,
                    orientation='h',
                    boxmean=False,
                    boxpoints=False,
                    line=dict(color="#000000", width=1),
                    fillcolor=_color_with_alpha(color_map[cond], box_alpha),
                    opacity=1.0,
                    width=box_width,
                    showlegend=False,
                    name=cond
                ))
            else:
                fig.add_trace(go.Box(
                    x=[positions[i] + box_nudge] * len(vals),
                    y=vals,
                    orientation='v',
                    boxmean=False,
                    boxpoints=False,
                    line=dict(color="#000000", width=1),
                    fillcolor=_color_with_alpha(color_map[cond], box_alpha),
                    opacity=1.0,
                    width=box_width,
                    showlegend=False,
                    name=cond
                ))

        # 散点
        if st.session_state.get("rc_plot_dots", True):
            dot_size = st.session_state.get("rc_dot_size", 2.0) * 2.8
            dot_alpha = st.session_state.get("rc_dot_alpha", 1.0)
            dot_shape_name = st.session_state.get("rc_dot_shape", "Filled Dot")
            dot_shape_map = {
                "Empty Dot": "circle",
                "Filled Dot": "circle",
                "Square": "square",
                "Triangle": "triangle-up",
            }
            marker_symbol = dot_shape_map.get(dot_shape_name, "circle")
            use_fill = dot_shape_name != "Empty Dot"
            dot_column_type = st.session_state.get("rc_dot_column_type", "Jitter")
            if dot_column_type == "Jitter":
                # 抖动宽度的总跨度即 width，即 ±width/2
                offsets = rng_for("rc_seed").uniform(-dots_width / 2, dots_width / 2, len(vals))
            else:
                offsets = _beeswarm_offsets(vals, dots_width)
            if plot_flip:
                x_vals = vals
                y_vals = positions[i] + offsets
                fig.add_trace(go.Scatter(
                    x=x_vals, y=y_vals,
                    mode='markers',
                    marker=dict(
                        size=dot_size,
                        color=_color_with_alpha(color_map[cond], dot_alpha) if use_fill else "rgba(0,0,0,0)",
                        symbol=marker_symbol,
                        line=dict(color=color_map[cond], width=0.8),
                        opacity=dot_alpha
                    ),
                    showlegend=False,
                    hoverinfo='x+y'
                ))
            else:
                x_vals = positions[i] + offsets
                y_vals = vals
                fig.add_trace(go.Scatter(
                    x=x_vals, y=y_vals,
                    mode='markers',
                    marker=dict(
                        size=dot_size,
                        color=_color_with_alpha(color_map[cond], dot_alpha) if use_fill else "rgba(0,0,0,0)",
                        symbol=marker_symbol,
                        line=dict(color=color_map[cond], width=0.8),
                        opacity=dot_alpha
                    ),
                    showlegend=False,
                    hoverinfo='x+y'
                ))

        # 均值线
        if st.session_state.get("rc_stats_mean", False):
            mean_width = st.session_state.get("rc_stats_mean_width", 0.5)
            mean_size = st.session_state.get("rc_stats_mean_size", 0.2)
            err_type = st.session_state.get("rc_stats_mean_error", "None")
            mean_val = np.mean(vals)
            if err_type == "None":
                err_low = err_high = 0.0
            else:
                if len(vals) > 1:
                    sd = np.std(vals, ddof=1)
                    se = sd / np.sqrt(len(vals))
                    if err_type == "95% Confidence Interval":
                        err_low = err_high = 1.96 * se
                    elif err_type == "Standard Error":
                        err_low = err_high = se
                    else:
                        err_low = err_high = sd
                else:
                    err_low = err_high = 0.0
            pos = positions[i] + mean_nudge
            if plot_flip:
                fig.add_trace(go.Scatter(
                    x=[mean_val - mean_width/2, mean_val + mean_width/2],
                    y=[pos, pos],
                    mode='lines',
                    line=dict(color=line_color, width=mean_size*5),
                    opacity=1.0,
                    showlegend=False,
                    hoverinfo='none'
                ))
                if err_low > 0:
                    fig.add_trace(go.Scatter(
                        x=[mean_val - err_low, mean_val + err_high],
                        y=[pos, pos],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))
                    fig.add_trace(go.Scatter(
                        x=[mean_val - err_low, mean_val - err_low],
                        y=[pos - 0.05, pos + 0.05],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))
                    fig.add_trace(go.Scatter(
                        x=[mean_val + err_high, mean_val + err_high],
                        y=[pos - 0.05, pos + 0.05],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))
            else:
                fig.add_trace(go.Scatter(
                    x=[pos - mean_width/2, pos + mean_width/2],
                    y=[mean_val, mean_val],
                    mode='lines',
                    line=dict(color=line_color, width=mean_size*5),
                    opacity=1.0,
                    showlegend=False,
                    hoverinfo='none'
                ))
                if err_low > 0:
                    fig.add_trace(go.Scatter(
                        x=[pos, pos],
                        y=[mean_val - err_low, mean_val + err_high],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))
                    fig.add_trace(go.Scatter(
                        x=[pos - 0.05, pos + 0.05],
                        y=[mean_val - err_low, mean_val - err_low],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))
                    fig.add_trace(go.Scatter(
                        x=[pos - 0.05, pos + 0.05],
                        y=[mean_val + err_high, mean_val + err_high],
                        mode='lines',
                        line=dict(color=line_color, width=mean_size*5),
                        showlegend=False,
                        hoverinfo='none'
                    ))

    # 水平参考线
    if st.session_state.get("rc_horizontal_line", False):
        hl_pos = st.session_state.get("rc_horizontal_line_position", 100.0)
        hl_type = st.session_state.get("rc_horizontal_line_type", "dashed")
        hl_size = st.session_state.get("rc_horizontal_line_size", 0.2)
        hl_alpha = st.session_state.get("rc_horizontal_line_alpha", 1.0)
        if plot_flip:
            fig.add_vline(x=hl_pos, line=dict(color=line_color, width=hl_size*5, dash=hl_type), opacity=hl_alpha)
        else:
            fig.add_hline(y=hl_pos, line=dict(color=line_color, width=hl_size*5, dash=hl_type), opacity=hl_alpha)

    # 统计比较标注
    if st.session_state.get("rc_statistics", False):
        label_format = st.session_state.get("rc_stats_label_format", "Significance (stars)")
        pairwise_method = None
        multiple_method = None
        if st.session_state.get("rc_stats_type", "Non-parametric") == "Parametric":
            if st.session_state.get("rc_stats_ttest", False):
                pairwise_method = "t.test"
            if st.session_state.get("rc_stats_anova", False):
                multiple_method = "anova"
        else:
            if st.session_state.get("rc_stats_wilcoxon", False):
                pairwise_method = "wilcox.test"
            if st.session_state.get("rc_stats_kruskal", False):
                multiple_method = "kruskal"

        data_max = float(np.nanmax(plot_df["value"]))
        data_min = float(np.nanmin(plot_df["value"]))
        span = max(data_max - data_min, 1.0)

        combos = st.session_state.get("rc_stats_combinations", [])
        if pairwise_method and combos:
            base_y = data_max + span * 0.08
            step_y = span * 0.08
            for idx, combo in enumerate(combos):
                try:
                    a_name, b_name = combo.split(" vs ")
                except ValueError:
                    continue
                if a_name not in selected_cols or b_name not in selected_cols:
                    continue
                a = plot_df.loc[plot_df["condition"] == a_name, "value"].to_numpy()
                b = plot_df.loc[plot_df["condition"] == b_name, "value"].to_numpy()
                p = _pairwise_pvalue(a, b, pairwise_method)
                if p is None:
                    continue
                label = _stars(p) if label_format == "Significance (stars)" else f"p={p:.3g}"
                i1 = selected_cols.index(a_name)
                i2 = selected_cols.index(b_name)
                level = base_y + idx * step_y
                if plot_flip:
                    fig.add_shape(type="line", x0=level, x1=level, y0=i1, y1=i2,
                                  line=dict(color=line_color, width=1))
                    fig.add_shape(type="line", x0=level - span*0.01, x1=level, y0=i1, y1=i1,
                                  line=dict(color=line_color, width=1))
                    fig.add_shape(type="line", x0=level - span*0.01, x1=level, y0=i2, y1=i2,
                                  line=dict(color=line_color, width=1))
                    fig.add_annotation(x=level + span*0.01, y=(i1+i2)/2, text=label,
                                       showarrow=False, font=dict(size=10, color=text_color))
                else:
                    fig.add_shape(type="line", x0=i1, x1=i1, y0=level - step_y*0.25, y1=level,
                                  line=dict(color=line_color, width=1))
                    fig.add_shape(type="line", x0=i1, x1=i2, y0=level, y1=level,
                                  line=dict(color=line_color, width=1))
                    fig.add_shape(type="line", x0=i2, x1=i2, y0=level - step_y*0.25, y1=level,
                                  line=dict(color=line_color, width=1))
                    fig.add_annotation(x=(i1+i2)/2, y=level + step_y*0.08, text=label,
                                       showarrow=False, font=dict(size=10, color=text_color))

        if multiple_method:
            groups = [plot_df.loc[plot_df["condition"] == cond, "value"].to_numpy() for cond in selected_cols]
            p = _multiple_pvalue(groups, multiple_method)
            if p is not None:
                label = f"{multiple_method.upper()} p={p:.3g}" if multiple_method == "anova" else f"Kruskal p={p:.3g}"
                y_pos = st.session_state.get("rc_stats_label_y", 0.0)
                if y_pos == 0.0:
                    y_pos = data_max + span * 0.20
                if plot_flip:
                    fig.add_annotation(x=y_pos, y=len(selected_cols)-0.2, text=label,
                                       showarrow=False, font=dict(size=10, color=text_color))
                else:
                    fig.add_annotation(x=np.mean(positions), y=y_pos, text=label,
                                       showarrow=False, font=dict(size=10, color=text_color))

    # 坐标轴与布局
    title_text = st.session_state.get("rc_plot_title", "Main Plot Title")
    x_title = st.session_state.get("rc_x_title", "x Axis Title")
    y_title = st.session_state.get("rc_y_title", "y Axis Title")
    title_font_size = st.session_state.get("rc_title_font_size", 20)
    axis_label_font_size = st.session_state.get("rc_axis_label_font_size", 15)
    scale_font_size = st.session_state.get("rc_scale_font_size", 15)
    x_axis_angle = st.session_state.get("rc_x_axis_angle", 0)

    if plot_flip:
        # 翻转坐标轴会把 x/y 轴标题互换：横轴显示原 y 轴标题
        fig.update_layout(
            title=dict(text=title_text, font=dict(size=title_font_size, color=text_color), x=0.5),
            xaxis=dict(title=dict(text=y_title, font=dict(size=axis_label_font_size, color=text_color)),
                       tickfont=dict(size=scale_font_size, color=text_color),
                       showgrid=st.session_state.get("rc_plot_major_grid", False),
                       showline=True, linecolor=text_color, linewidth=1, zeroline=False),
            yaxis=dict(title=dict(text=x_title, font=dict(size=axis_label_font_size, color=text_color)),
                       tickvals=positions, ticktext=selected_cols,
                       tickfont=dict(size=scale_font_size, color=text_color),
                       tickangle=x_axis_angle,
                       showgrid=st.session_state.get("rc_plot_major_grid", False),
                       showline=True, linecolor=text_color, linewidth=1, zeroline=False),
            plot_bgcolor=bg_color,
            paper_bgcolor=bg_color,
            width=width_px,
            height=height_px,
            margin=dict(l=60, r=30, t=80, b=50),
            hovermode='closest'
        )
        if not st.session_state.get("rc_auto_scale", True):
            fig.update_xaxes(range=[st.session_state.get("rc_min_scale", 0.0), st.session_state.get("rc_max_scale", 150.0)])
    else:
        fig.update_layout(
            title=dict(text=title_text, font=dict(size=title_font_size, color=text_color), x=0.5),
            xaxis=dict(title=dict(text=x_title, font=dict(size=axis_label_font_size, color=text_color)),
                       tickvals=positions, ticktext=selected_cols,
                       tickfont=dict(size=scale_font_size, color=text_color),
                       tickangle=x_axis_angle,
                       showgrid=st.session_state.get("rc_plot_major_grid", False),
                       showline=True, linecolor=text_color, linewidth=1, zeroline=False),
            yaxis=dict(title=dict(text=y_title, font=dict(size=axis_label_font_size, color=text_color)),
                       tickfont=dict(size=scale_font_size, color=text_color),
                       showgrid=st.session_state.get("rc_plot_major_grid", False),
                       showline=True, linecolor=text_color, linewidth=1, zeroline=False),
            plot_bgcolor=bg_color,
            paper_bgcolor=bg_color,
            width=width_px,
            height=height_px,
            margin=dict(l=60, r=30, t=80, b=50),
            hovermode='closest'
        )
        if not st.session_state.get("rc_auto_scale", True):
            fig.update_yaxes(range=[st.session_state.get("rc_min_scale", 0.0), st.session_state.get("rc_max_scale", 150.0)])

    if show_legend:
        for cond, color in color_map.items():
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode='markers',
                marker=dict(size=10, color=color, symbol="circle"),
                name=cond,
                showlegend=True
            ))
        fig.update_layout(legend=dict(title="condition", font=dict(color=text_color), bgcolor='rgba(255,255,255,0.7)'))

    shared["last_plotly"] = fig
    shared["status"] = f"Raincloud 图已生成，共 {len(selected_cols)} 个 condition，{len(plot_df)} 条记录。"
    shared["help_text"] = HELP_TEXT
    return fig, plot_df, shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render
