from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_bytes, sample_loader_control
from app.core.theme import THEMES
from app.core.random_seed import rng_for, seed_control

HELP_TEXT = """
Pirate Plot (Plotly 交互版本)
输入数据：
  - 连续变量文件：包含数值列
  - 分类变量文件：包含分类列
  - 两个文件会按行顺序进行拼接
用法：
  - 选择 1 / 2 / 3 个分类变量
  - 选择 1 个连续变量
  - 系统会自动组合分类变量生成 condition
  - 可选择 Type 1~4 预设风格，或 Customize 自定义风格
说明：
  - 本模块使用 Plotly 实现，支持缩放、悬停等交互
  - 视觉上完整呈现散点、箱线与密度三层结构
"""

from app.core.palettes import SCI_DIST_COLORS

PALETTES = {
    "SCI": list(SCI_DIST_COLORS),
    "basel": ["#2C7FB8", "#41B6C4", "#A1DAB4", "#FFFFCC", "#FD8D3C", "#E31A1C"],
    "info2": ["#4E79A7", "#59A14F", "#9C755F", "#F28E2B", "#E15759", "#76B7B2"],
    "google": ["#4285F4", "#EA4335", "#FBBC05", "#34A853", "#A142F4", "#00ACC1"],
    "rat": ["#6A3D9A", "#B15928", "#1F78B4", "#33A02C", "#E31A1C", "#FF7F00"],
}

COLOR_CHOICES = ["black", "white", "red", "green", "blue"]
ALPHA_CHOICES = ["0", "0.3", "0.5", "0.7", "1"]


def _sample_continuous_df() -> pd.DataFrame:
    sample_path = get_sample_path("pirate_cont")
    return read_table(sample_path, sample_path.name)


def _sample_categorical_df() -> pd.DataFrame:
    sample_path = get_sample_path("pirate_cat")
    return read_table(sample_path, sample_path.name)


def _sample_continuous_bytes() -> bytes:
    return sample_bytes("pirate_cont")


def _sample_categorical_bytes() -> bytes:
    return sample_bytes("pirate_cat")


def _load_df(uploaded, filetype: str, sample_df: pd.DataFrame, use_sample: bool):
    if use_sample:
        return sample_df.copy(), None
    if uploaded is None:
        return None, "请上传对应的数据文件。"
    try:
        return read_table(uploaded, uploaded.name), None
    except Exception as exc:
        return None, f"文件读取失败：{exc}"


def _theme_defaults(theme_value: str):
    """Pirate Plot 的 theme 1-4 默认参数"""
    return {
        "1": dict(point_alpha=0.50, violin_alpha=0.25, box_alpha=0.35, mean_alpha=0.90, line_width=1.0),
        "2": dict(point_alpha=0.65, violin_alpha=0.35, box_alpha=0.45, mean_alpha=0.95, line_width=1.2),
        "3": dict(point_alpha=0.90, violin_alpha=0.55, box_alpha=0.60, mean_alpha=1.00, line_width=1.5),
        "4": dict(point_alpha=0.85, violin_alpha=0.40, box_alpha=0.50, mean_alpha=1.00, line_width=1.8),
        "0": dict(point_alpha=0.70, violin_alpha=0.40, box_alpha=0.45, mean_alpha=1.00, line_width=1.2),
    }[theme_value]


def _summary_table(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.groupby("condition", dropna=False, observed=False)["value"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .reset_index()
        .rename(columns={"count": "N", "std": "SD"})
    )
    out["SE"] = out["SD"] / np.sqrt(out["N"].replace(0, np.nan))
    return out


def _calc_interval(values: np.ndarray, method: str):
    """计算置信区间：hdi, ci, iqr"""
    vals = pd.Series(values).dropna().astype(float).to_numpy()
    if len(vals) == 0:
        return None, None
    if method == "iqr":
        return np.quantile(vals, 0.25), np.quantile(vals, 0.75)
    mean = float(np.mean(vals))
    if len(vals) < 2:
        return mean, mean
    sd = float(np.std(vals, ddof=1))
    se = sd / np.sqrt(len(vals))
    if method == "ci":
        delta = 1.96 * se
        return mean - delta, mean + delta
    # hdi：包含 95% 样本的最短经验区间（等价 HDInterval::hdi 的基本定义）
    ordered = np.sort(vals)
    n = len(ordered)
    width = max(int(np.floor(0.95 * n)), 1)
    if width >= n:
        return float(ordered[0]), float(ordered[-1])
    spans = ordered[width:] - ordered[: n - width]
    start = int(np.argmin(spans))
    return float(ordered[start]), float(ordered[start + width])


def _bw_nrd0(values: np.ndarray) -> float:
    """核密度带宽选择（nrd0 规则）。"""
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    if n < 2:
        return 1.0
    sd = float(np.std(vals, ddof=1))
    q75, q25 = np.percentile(vals, [75, 25])
    iqr = float(q75 - q25)
    spread = min(sd, iqr / 1.34)
    if spread <= 0:
        spread = sd if sd > 0 else 1.0
    return 0.9 * spread * n ** (-0.2)


def _kde_curve(values: np.ndarray, n_points: int = 256):
    """高斯核密度估计，使用 nrd0 带宽。"""
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 2:
        return np.array([vals[0], vals[0]]), np.array([1.0, 1.0])
    bw = _bw_nrd0(vals)
    lo, hi = float(np.min(vals)), float(np.max(vals))
    if np.isclose(lo, hi):
        return np.array([lo, hi]), np.array([1.0, 1.0])
    grid = np.linspace(lo, hi, n_points)
    z = (grid[:, None] - vals[None, :]) / bw
    dens = np.exp(-0.5 * z * z).sum(axis=1) / (
        len(vals) * bw * np.sqrt(2.0 * np.pi)
    )
    area = np.trapezoid(dens, grid) if hasattr(np, "trapezoid") else np.trapz(dens, grid)
    if area > 0:
        dens = dens / area
    return grid, dens


def _safe_color(c, default):
    """将颜色值转换为 Plotly 可接受的格式"""
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
        # 颜色名映射
        color_map = {
            "black": "#000000", "white": "#FFFFFF", "red": "#FF0000",
            "green": "#008000", "blue": "#0000FF", "gray": "#808080",
            "grey": "#808080", "lightgray": "#D3D3D3", "darkgray": "#A9A9A9",
            "orange": "#FFA500", "yellow": "#FFFF00", "purple": "#800080",
            "pink": "#FFC0CB"
        }
        return color_map.get(c_stripped, default)
    return default


def _color_with_alpha(color, alpha):
    """为十六进制颜色添加 alpha 通道"""
    if alpha >= 1.0 or not color.startswith('#'):
        return color
    r = int(color[1:3], 16) / 255.0
    g = int(color[3:5], 16) / 255.0
    b = int(color[5:7], 16) / 255.0
    return f"rgba({r*255:.0f}, {g*255:.0f}, {b*255:.0f}, {alpha})"


def controls(shared: dict) -> None:
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    sample_loader_control("pir_use_sample", ["pirate_cont", "pirate_cat"], "pir_load_sample_btn")
    st.radio(
        "Upload file type",
        ["csv", "xlsx"],
        horizontal=True,
        key="pir_filetype",
    )
    if not st.session_state.get("pir_use_sample", True):
        st.file_uploader(
            "Upload continuous variable file",
            type=["csv", "xlsx", "txt", "tsv"],
            key="pir_cont_file",
        )
        st.file_uploader(
            "Upload categorical variable file",
            type=["csv", "xlsx", "txt", "tsv"],
            key="pir_cat_file",
        )
    st.download_button(
        "Download example file for continuous variables",
        data=_sample_continuous_bytes(),
        file_name="continuous_variable.csv",
        mime="text/csv",
        width="stretch",
    )
    st.download_button(
        "Download example file for categorical variables",
        data=_sample_categorical_bytes(),
        file_name="categorical_variable.csv",
        mime="text/csv",
        width="stretch",
    )

    cont_df, _ = _load_df(
        st.session_state.get("pir_cont_file"),
        st.session_state.get("pir_filetype", "csv"),
        _sample_continuous_df(),
        st.session_state.get("pir_use_sample", True),
    )
    cat_df, _ = _load_df(
        st.session_state.get("pir_cat_file"),
        st.session_state.get("pir_filetype", "csv"),
        _sample_categorical_df(),
        st.session_state.get("pir_use_sample", True),
    )

    st.radio(
        "Pirateplot Type",
        ["Type 1", "Type 2", "Type 3", "Type 4", "Customize"],
        horizontal=True,
        key="pir_theme_label",
    )
    theme_map = {
        "Type 1": "1",
        "Type 2": "2",
        "Type 3": "3",
        "Type 4": "4",
        "Customize": "0",
    }
    st.session_state["pir_theme"] = theme_map[st.session_state["pir_theme_label"]]

    st.selectbox(
        "Select the number of associated categorical variables",
        ["a categorical variable", "two categorical variables", "three categorical variables"],
        index=0,
        key="pir_numdata_label",
    )
    num_map = {
        "a categorical variable": 1,
        "two categorical variables": 2,
        "three categorical variables": 3,
    }
    num_cat = num_map[st.session_state["pir_numdata_label"]]

    cont_cols = cont_df.columns.tolist() if cont_df is not None else []
    cat_cols = cat_df.columns.tolist() if cat_df is not None else []

    st.selectbox(
        "Select continuous variable",
        cont_cols if cont_cols else [""],
        index=0,
        key="pir_convar",
    )
    st.selectbox(
        "Select categorical variable 1",
        cat_cols if cat_cols else [""],
        index=0,
        key="pir_catvar1",
    )
    if num_cat >= 2:
        st.selectbox(
            "Select categorical variable 2",
            cat_cols if cat_cols else [""],
            index=min(1, max(len(cat_cols) - 1, 0)) if cat_cols else 0,
            key="pir_catvar2",
        )
    if num_cat >= 3:
        st.selectbox(
            "Select categorical variable 3",
            cat_cols if cat_cols else [""],
            index=min(2, max(len(cat_cols) - 1, 0)) if cat_cols else 0,
            key="pir_catvar3",
        )

    st.selectbox("Create a table", ["F", "T"], index=0, key="pir_table")
    st.selectbox("Scheme color", list(PALETTES.keys()), index=0, key="pir_palette")

    if st.session_state.get("pir_theme") == "0":
        st.radio("Custom Pirate Map", ["color", "opacity"], horizontal=True, key="pir_about")
        if st.session_state.get("pir_about") == "color":
            st.selectbox("point edge", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_PTcol"), "black"))
                         if _safe_color(theme.get("pir_PTcol"), "black") in COLOR_CHOICES else 0,
                         key="pir_PTcol")
            st.selectbox("point fill", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_PTbg"), "white"))
                         if _safe_color(theme.get("pir_PTbg"), "white") in COLOR_CHOICES else 1,
                         key="pir_PTbg")
            st.selectbox("trend bar edge", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_BNbcol"), "black"))
                         if _safe_color(theme.get("pir_BNbcol"), "black") in COLOR_CHOICES else 0,
                         key="pir_BNbcol")
            st.selectbox("trend bar fill", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_BNfcol"), "white"))
                         if _safe_color(theme.get("pir_BNfcol"), "white") in COLOR_CHOICES else 1,
                         key="pir_BNfcol")
            st.selectbox("smoothed density edge", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_BRbcol"), "black"))
                         if _safe_color(theme.get("pir_BRbcol"), "black") in COLOR_CHOICES else 0,
                         key="pir_BRbcol")
            st.selectbox("inference interval edge", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_IFbcol"), "black"))
                         if _safe_color(theme.get("pir_IFbcol"), "black") in COLOR_CHOICES else 0,
                         key="pir_IFbcol")
            st.selectbox("inference interval fill", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_IFfcol"), "lightgray"))
                         if _safe_color(theme.get("pir_IFfcol"), "lightgray") in COLOR_CHOICES else 3,
                         key="pir_IFfcol")
            st.selectbox("Color of the average line", COLOR_CHOICES,
                         index=COLOR_CHOICES.index(_safe_color(theme.get("pir_AGcol"), "black"))
                         if _safe_color(theme.get("pir_AGcol"), "black") in COLOR_CHOICES else 0,
                         key="pir_AGcol")
        else:
            st.selectbox("Transparency for the points", ALPHA_CHOICES, key="pir_PTo")
            st.selectbox("Edge opacity of trend bars", ALPHA_CHOICES, key="pir_BNb")
            st.selectbox("Interior opacity of trend bars", ALPHA_CHOICES, key="pir_BNf")
            st.selectbox("Edge opacity of smoothed density", ALPHA_CHOICES, key="pir_BRb")
            st.selectbox("Interior opacity of smoothed density", ALPHA_CHOICES, key="pir_BRf")
            st.selectbox("Edge opacity of inference bands", ALPHA_CHOICES, key="pir_IFb")
            st.selectbox("Interior opacity of inference bands", ALPHA_CHOICES, key="pir_IFf")
            st.selectbox("Transparency for the mean line", ALPHA_CHOICES, key="pir_AGo")

    st.radio(
        "Additional parameter configuration",
        ["background color", "Calculation method of confidence intervals", "Display mode of confidence intervals"],
        horizontal=True,
        key="pir_adjust",
    )
    if st.session_state.get("pir_adjust") == "background color":
        st.slider("background color", 0.0, 1.0, 0.95, 0.05, key="pir_backcol")
    if st.session_state.get("pir_adjust") == "Calculation method of confidence intervals":
        st.selectbox(
            "Calculation method of confidence intervals",
            ["hdi", "ci", "iqr"],
            index=0,
            key="pir_inf_method",
        )
    if st.session_state.get("pir_adjust") == "Display mode of confidence intervals":
        st.selectbox(
            "Display mode of confidence intervals",
            ["line", "bean", "rect"],
            index=0,
            key="pir_inf_disp",
        )

    st.text_input("PiratePlots title", value="", key="pir_title")
    with st.expander("可复现性", expanded=False):
        seed_control("pir_seed")


def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    use_sample = st.session_state.get("pir_use_sample", True)
    cont_df, cont_err = _load_df(
        st.session_state.get("pir_cont_file"),
        st.session_state.get("pir_filetype", "csv"),
        _sample_continuous_df(),
        use_sample,
    )
    cat_df, cat_err = _load_df(
        st.session_state.get("pir_cat_file"),
        st.session_state.get("pir_filetype", "csv"),
        _sample_categorical_df(),
        use_sample,
    )
    if cont_err:
        return None, None, cont_err, HELP_TEXT
    if cat_err:
        return None, None, cat_err, HELP_TEXT
    if cont_df is None or cat_df is None:
        return None, None, "请先上传连续变量和分类变量文件。", HELP_TEXT
    if len(cont_df) != len(cat_df):
        return None, None, "连续变量文件和分类变量文件的行数必须一致。", HELP_TEXT

    convar = st.session_state.get("pir_convar", "")
    num_cat = {
        "a categorical variable": 1,
        "two categorical variables": 2,
        "three categorical variables": 3,
    }[st.session_state.get("pir_numdata_label", "a categorical variable")]
    cat_vars = [st.session_state.get("pir_catvar1", "")]
    if num_cat >= 2:
        cat_vars.append(st.session_state.get("pir_catvar2", ""))
    if num_cat >= 3:
        cat_vars.append(st.session_state.get("pir_catvar3", ""))

    if convar not in cont_df.columns:
        return None, None, "请选择有效的连续变量列。", HELP_TEXT
    for cat_var in cat_vars:
        if cat_var not in cat_df.columns:
            return None, None, "请选择有效的分类变量列。", HELP_TEXT

    value = pd.to_numeric(cont_df[convar], errors="coerce")
    work = pd.DataFrame({"value": value})
    cat_cols = []
    for i, cat_var in enumerate(cat_vars, 1):
        col = f"cat{i}"
        work[col] = cat_df[cat_var]
        cat_cols.append(col)
    # 分类变量缺失的行直接丢弃（忽略缺失分组），避免出现 NaN 组
    work = work.dropna(subset=["value", *cat_cols]).copy()
    if work.empty:
        return None, None, "连续变量列没有可用数值。", HELP_TEXT
    for col in cat_cols:
        work[col] = work[col].astype(str)

    work["condition"] = work[cat_cols].astype(str).agg(" | ".join, axis=1)
    order = pd.unique(work["condition"]).tolist()
    work["condition"] = pd.Categorical(work["condition"], categories=order, ordered=True)

    summary = _summary_table(work)
    shared["data"] = {
        "plot_data": work[["value", "condition"]].copy(),
        "summary_table": summary.copy(),
    }

    palette_name = st.session_state.get("pir_palette", "SCI")
    palette = PALETTES.get(palette_name, PALETTES["SCI"])
    # 循环使用调色板颜色
    colors = (palette * ((len(order) // len(palette)) + 1))[: len(order)]

    theme_value = st.session_state.get("pir_theme", "1")
    defaults = _theme_defaults(theme_value)

    # 从主题获取默认颜色（转换为十六进制）
    line_default = _safe_color(theme.get("line_default"), "#4d4d4d")
    text_color = _safe_color(theme.get("text"), "#111827")
    bg_color = theme.get("bg", "#f5f7fb")

    # 预设模式使用主题的线条颜色
    point_edge = line_default
    point_fill = colors
    violin_edge = line_default
    box_edge = line_default
    inf_edge = line_default
    inf_fill = "#D3D3D3"
    mean_color = line_default
    point_alpha = defaults["point_alpha"]
    violin_fill_alpha = defaults["violin_alpha"]
    box_fill_alpha = defaults["box_alpha"]
    mean_alpha = defaults["mean_alpha"]
    bg_gray = st.session_state.get("pir_backcol", 0.95)
    inf_method = st.session_state.get("pir_inf_method", "hdi")
    inf_disp = st.session_state.get("pir_inf_disp", "line")

    if theme_value == "0":
        # 自定义模式，从 session_state 读取用户自定义颜色
        point_edge = _safe_color(st.session_state.get("pir_PTcol", theme.get("pir_PTcol")), line_default)
        fill_color = _safe_color(st.session_state.get("pir_PTbg", theme.get("pir_PTbg")), "#FFFFFF")
        point_fill = [fill_color] * len(order)
        box_edge = _safe_color(st.session_state.get("pir_BNbcol", theme.get("pir_BNbcol")), line_default)
        violin_edge = _safe_color(st.session_state.get("pir_BRbcol", theme.get("pir_BRbcol")), line_default)
        inf_edge = _safe_color(st.session_state.get("pir_IFbcol", theme.get("pir_IFbcol")), line_default)
        inf_fill = _safe_color(st.session_state.get("pir_IFfcol", theme.get("pir_IFfcol")), "#D3D3D3")
        mean_color = _safe_color(st.session_state.get("pir_AGcol", theme.get("pir_AGcol")), line_default)
        point_alpha = float(st.session_state.get("pir_PTo", str(defaults["point_alpha"])))
        violin_fill_alpha = float(st.session_state.get("pir_BRf", str(defaults["violin_alpha"])))
        box_fill_alpha = float(st.session_state.get("pir_BNf", str(defaults["box_alpha"])))
        mean_alpha = float(st.session_state.get("pir_AGo", str(defaults["mean_alpha"])))

    # 创建 Plotly 图形（四层结构）
    fig = go.Figure()

    positions = np.arange(len(order), dtype=float)
    bean_half_width = 0.42
    bar_half_width = 0.24
    jitter_width = 0.08
    point_size = 5.5
    rng = rng_for("pir_seed")

    for i, cond in enumerate(order):
        vals = work.loc[work["condition"] == cond, "value"].to_numpy(dtype=float)
        if len(vals) == 0:
            continue

        center = float(positions[i])
        cond_color = point_fill[i] if i < len(point_fill) else point_fill[-1]
        mean_val = float(np.mean(vals))
        q_low, q_high = np.percentile(vals, [25, 75])
        w_low, w_high = np.percentile(vals, [2.5, 97.5])
        low, high = _calc_interval(vals, inf_method)

        # 1) 推断区间（inf band），画在最底层
        if low is not None and high is not None:
            if inf_disp == "bean":
                grid, dens = _kde_curve(vals)
                half = dens / max(float(np.max(dens)), 1e-12) * bean_half_width
                half_low = float(np.interp(low, grid, half))
                half_high = float(np.interp(high, grid, half))
                fig.add_shape(
                    type="path",
                    path=(
                        f"M {center - half_low:.4f} {float(low):.4f} "
                        f"L {center + half_low:.4f} {float(low):.4f} "
                        f"L {center + half_high:.4f} {float(high):.4f} "
                        f"L {center - half_high:.4f} {float(high):.4f} Z"
                    ),
                    fillcolor=_color_with_alpha(inf_fill, 0.35),
                    line=dict(color=inf_edge, width=1.0),
                    layer="below",
                )
            else:
                half = 0.46 if inf_disp == "line" else 0.25
                fig.add_shape(
                    type="rect",
                    x0=center - half, x1=center + half,
                    y0=float(low), y1=float(high),
                    fillcolor=_color_with_alpha(inf_fill, 0.35),
                    line=dict(color=inf_edge, width=1.2),
                    layer="below",
                )

        # 2) Bar/Line Center：Q25–Q75 方块（顶边为 Q75）
        fig.add_shape(
            type="rect",
            x0=center - bar_half_width, x1=center + bar_half_width,
            y0=float(q_low), y1=float(q_high),
            fillcolor=_color_with_alpha(cond_color, box_fill_alpha),
            line=dict(color=box_edge, width=1.2),
            layer="below",
        )

        # 须线：2.5%–97.5% 分位，带端帽
        fig.add_trace(go.Scatter(
            x=[center, center],
            y=[float(w_low), float(w_high)],
            mode="lines",
            line=dict(color=box_edge, width=1.0),
            showlegend=False,
            hoverinfo="none",
        ))
        for cap_y in (float(w_low), float(w_high)):
            fig.add_trace(go.Scatter(
                x=[center - 0.07, center + 0.07],
                y=[cap_y, cap_y],
                mode="lines",
                line=dict(color=box_edge, width=1.0),
                showlegend=False,
                hoverinfo="none",
            ))

        # 3) Bean：完整对称核密度多边形，居中于分组
        grid, dens = _kde_curve(vals)
        half = dens / max(float(np.max(dens)), 1e-12) * bean_half_width
        bean_x = np.concatenate([center + half, (center - half)[::-1]])
        bean_y = np.concatenate([grid, grid[::-1]])
        fig.add_trace(go.Scatter(
            x=bean_x,
            y=bean_y,
            mode="lines",
            fill="toself",
            fillcolor=_color_with_alpha(cond_color, violin_fill_alpha),
            line=dict(
                color=violin_edge if theme_value == "0" else cond_color,
                width=1.2,
            ),
            showlegend=False,
            hoverinfo="skip",
        ))

        # 4) Points：原始数据抖动后叠加在 bean 上
        x_jitter = center + rng.uniform(-jitter_width, jitter_width, len(vals))
        fig.add_trace(go.Scatter(
            x=x_jitter,
            y=vals,
            mode="markers",
            marker=dict(
                color=_color_with_alpha(cond_color, point_alpha),
                size=point_size,
                line=dict(color=point_edge, width=0.5),
            ),
            showlegend=False,
            hoverinfo="y+x",
        ))

        # 5) 均值横线
        fig.add_trace(go.Scatter(
            x=[center - bar_half_width, center + bar_half_width],
            y=[mean_val, mean_val],
            mode="lines",
            line=dict(color=mean_color, width=defaults["line_width"] + 0.8),
            opacity=mean_alpha,
            showlegend=False,
            hoverinfo="none",
        ))

    # 布局设置
    title_text = st.session_state.get("pir_title", "")
    # 背景灰度（精确十六进制）
    gray_val = int(255 * bg_gray)
    plot_bgcolor = f"#{gray_val:02x}{gray_val:02x}{gray_val:02x}"
    fig.update_layout(
        title=dict(text=title_text, font=dict(color=text_color), x=0.5),
        xaxis=dict(
            title="",
            tickvals=positions,
            ticktext=order,
            tickangle=20,
            tickfont=dict(color=text_color)
        ),
        yaxis=dict(
            title=dict(text=convar, font=dict(color=text_color)),
            tickfont=dict(color=text_color),
            gridcolor=line_default,
            gridwidth=0.5,
            griddash='dash'
        ),
        plot_bgcolor=plot_bgcolor,
        paper_bgcolor=bg_color,
        width=850,
        height=850,
        margin=dict(l=60, r=30, t=80, b=50),
        hovermode='closest'
    )

    # 添加水平网格线
    fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor=line_default, griddash='dash')

    shared["last_plotly"] = fig
    shared["status"] = f"Pirate Plot 已生成，共 {len(order)} 个 condition，{len(work)} 条记录。"
    shared["help_text"] = HELP_TEXT

    if st.session_state.get("pir_table", "F") == "T":
        return fig, {"plot_data": work[["value", "condition"]], "summary_table": summary}, shared["status"], HELP_TEXT
    return fig, work[["value", "condition"]], shared["status"], HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
