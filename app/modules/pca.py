"""PCA — principal component analysis scatter (architecture §3.7).

Zero new dependencies: column z-score → ``numpy.linalg.svd`` → sample scores;
axis titles carry the explained-variance ratio; optional per-group confidence
ellipses from ``scipy.stats.chi2.ppf``.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES
HELP_TEXT = """
PCA（主成分分析散点图）

支持输入（宽表 CSV / TSV / TXT / XLSX）：
  - 第 1 列为样本名，其余为数值特征列
  - 可选 group 列（用于着色与置信椭圆）

算法（numpy 内置，无新增依赖）：
  1. 按列 z-score（可切换「仅中心化」/「不处理」）
  2. numpy SVD 分解 → 样本得分 = U · S
  3. 解释方差比 = S² / ΣS²，写入轴标题

可配置项：
  - 分组列、X / Y 轴主成分（PC1–PC10，随样本数动态截断）
  - 标准化方式、置信椭圆开关与置信度
  - 每组配色（最多 8 组）、点大小与透明度、样本标签
  - 标题

说明：
  - 常数列用 +1e-12 兜底，避免除零
  - 主成分个数 = min(样本数, 特征数)，下拉选项会按此动态截断
"""
NO_GROUP = "(无分组)"
SCALE_MODES: tuple[str, ...] = ("z-score 标准化", "仅中心化", "不处理")
GROUP_COLOR_KEYS: tuple[str, ...] = (    "pca_color_group_1",    "pca_color_group_2",    "pca_color_group_3",    "pca_color_group_4",    "pca_color_group_5",    "pca_color_group_6",    "pca_color_group_7",    "pca_color_group_8",)
MAX_PC = 10
_FALLBACK_COLORS: dict[str, str] = {    "pca_group1": "#3C5488",    "pca_group2": "#E64B35",    "pca_group3": "#00A087",    "pca_group4": "#4DBBD5",    "pca_ellipse": "#8491B4",    "bg": "#f5f7fb",    "text": "#111827",}
_QUALITATIVE = (    "#3C5488",    "#E64B35",    "#00A087",    "#4DBBD5",    "#F39B7F",    "#8491B4",    "#91D1C2",    "#DC0000",)# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
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
    if st.session_state.get("pca_use_sample", True):
        try:
            path = get_sample_path("pca_samples")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("pca_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""
def _split_frame(frame: pd.DataFrame, group_col: str) -> tuple[pd.Series, pd.DataFrame, pd.Series | None]:
    """Split a wide table into sample names, numeric feature matrix and groups."""
    samples = frame.iloc[:, 0].astype(str).str.strip()
    group_values = frame[group_col].astype(str).str.strip() if group_col else None
    excluded = {str(frame.columns[0])}
    if group_col:
        excluded.add(str(group_col))
    features = frame[[c for c in frame.columns if str(c) not in excluded]].copy()
    features = features.apply(pd.to_numeric, errors="coerce")
    features = features.dropna(axis=1, how="all")
    if features.shape[1] == 0:
        return samples, features, group_values
    features = features.fillna(features.mean(numeric_only=True)).fillna(0.0)
    return samples, features, group_values
def _pca_scores(matrix: pd.DataFrame, scale_mode: str) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(scores, explained_ratio)`` for the chosen standardisation."""
    values = matrix.to_numpy(dtype=float)
    if values.size == 0:
        return np.zeros((0, 0)), np.zeros(0)
    if scale_mode == "z-score 标准化":
        centred = values - values.mean(axis=0)
        values = centred / (values.std(axis=0, ddof=1) + 1e-12)
    elif scale_mode == "仅中心化":
        values = values - values.mean(axis=0)
    u, s, _ = np.linalg.svd(values, full_matrices=False)
    total = float((s**2).sum())
    explained = (s**2) / total if total > 0 else np.zeros_like(s)
    return u * s, explained
def _ellipse_points(    x_values: np.ndarray,    y_values: np.ndarray,    confidence: float,    n_points: int = 100,) -> tuple[np.ndarray, np.ndarray] | None:
    """Confidence ellipse for one group of 2D scores."""
    if x_values.size < 3:
        return None
    from scipy.stats import chi2  # imported lazily to keep import cost low
    mean = np.array([x_values.mean(), y_values.mean()])
    cov = np.cov(np.vstack([x_values, y_values]))
    if not np.all(np.isfinite(cov)):
        return None
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    order = eigenvalues.argsort()[::-1]
    eigenvalues = np.clip(eigenvalues[order], 1e-12, None)
    eigenvectors = eigenvectors[:, order]
    radius = np.sqrt(chi2.ppf(confidence, 2) * eigenvalues)
    angles = np.linspace(0.0, 2.0 * np.pi, n_points)
    circle = np.vstack([np.cos(angles), np.sin(angles)])
    points = mean[:, None] + eigenvectors @ (radius[:, None] * circle)
    return points[0], points[1]# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("pca_use_sample", ["pca_samples"], "pca_load_sample_btn")
    if not st.session_state.get("pca_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="pca_file_upload",        )
        st.caption("宽表：第 1 列为样本名，其余为数值特征列；可选 group 列。")
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    all_cols = [str(c) for c in frame.columns]
    group_options = [NO_GROUP] + all_cols
    lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
    default_group = lowered.get("group", NO_GROUP)
    st.markdown("### 列映射")
    _pick(        "分组列",        group_options,        "pca_col_group",        group_options.index(default_group) if default_group in group_options else 0,    )
    st.markdown("### 主成分")
    pc_options = [f"PC{index}" for index in range(1, MAX_PC + 1)]
    _pick("X 轴主成分", pc_options, "pca_pc_x", 0)
    _pick("Y 轴主成分", pc_options, "pca_pc_y", 1)
    st.markdown("### 外观")
    st.slider("点大小", 3, 20, 9, 1, key="pca_point_size")
    st.slider("透明度", 0.1, 1.0, 0.85, 0.05, key="pca_opacity")
    st.checkbox("显示样本标签", value=False, key="pca_show_sample_label")
    if st.session_state.get("pca_show_sample_label", False):
        st.slider("标签字号", 6, 16, 9, 1, key="pca_label_size")
    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="pca_add_title")
    if st.session_state.get("pca_add_title", False):
        st.text_input("图形标题", "PCA", key="pca_title")
def advanced_controls(shared: dict) -> None:
    """PCA 的高级参数：标准化、置信椭圆与分组配色。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.markdown("### 标准化")
    st.radio("标准化方式", list(SCALE_MODES), index=0, key="pca_scale_mode")
    st.markdown("### 分组与椭圆")
    st.checkbox("显示置信椭圆", value=True, key="pca_show_ellipse")
    if st.session_state.get("pca_show_ellipse", True):
        st.slider("椭圆置信度", 0.50, 0.99, 0.95, 0.01, key="pca_ellipse_conf")
    group_col = st.session_state.get("pca_col_group", NO_GROUP)
    if group_col != NO_GROUP and group_col in frame.columns:
        groups = [str(value) for value in pd.unique(frame[group_col].astype(str))]
        for index, group in enumerate(groups[:8]):
            color_key = GROUP_COLOR_KEYS[index]
            st.color_picker(                f"分组 {group} 颜色",                value=(                    _theme_color(f"pca_group{index + 1}")                    if index < 4                    else _QUALITATIVE[index % len(_QUALITATIVE)]                ),                key=color_key,            )# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    group_col = st.session_state.get("pca_col_group")
    if group_col is None:
        # No widget state yet (headless build) → fall back to name detection.
        lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
        group_col = lowered.get("group", NO_GROUP)
    if group_col == NO_GROUP or group_col not in frame.columns:
        group_col = ""
    samples, features, group_values = _split_frame(frame, group_col)
    if features.shape[1] == 0:
        return None, None, "没有可用的数值特征列。", HELP_TEXT
    if features.shape[0] < 3:
        return None, None, "样本数太少（至少需要 3 个样本）。", HELP_TEXT
    scale_mode = st.session_state.get("pca_scale_mode", SCALE_MODES[0])
    scores, explained = _pca_scores(features, scale_mode)
    if scores.size == 0:
        return None, None, "无法计算主成分，请检查数据矩阵。", HELP_TEXT
    n_components = explained.size
    pc_labels = [f"PC{index}" for index in range(1, n_components + 1)]
    def _pc_index(value: str | None, fallback: int) -> int:
        if value in pc_labels:
            return pc_labels.index(value)
        return min(fallback, n_components - 1)
    x_index = _pc_index(st.session_state.get("pca_pc_x"), 0)
    y_index = _pc_index(st.session_state.get("pca_pc_y"), 1)
    score_df = pd.DataFrame(        {            "sample": samples.to_numpy(),            "group": (group_values.to_numpy() if group_values is not None else NO_GROUP),        }    )
    for index, label in enumerate(pc_labels):
        score_df[label] = scores[:, index]
    point_size = int(st.session_state.get("pca_point_size", 9))
    opacity = float(st.session_state.get("pca_opacity", 0.85))
    show_label = bool(st.session_state.get("pca_show_sample_label", False))
    label_size = int(st.session_state.get("pca_label_size", 9))
    show_ellipse = bool(st.session_state.get("pca_show_ellipse", True))
    ellipse_conf = float(st.session_state.get("pca_ellipse_conf", 0.95))
    add_title = bool(st.session_state.get("pca_add_title", False))
    title = (st.session_state.get("pca_title") or "PCA") if add_title else ""
    text_color = theme.get("text", "#111827")
    ellipse_color = _theme_color("pca_ellipse")
    x_values = score_df[pc_labels[x_index]].to_numpy(dtype=float)
    y_values = score_df[pc_labels[y_index]].to_numpy(dtype=float)
    has_groups = bool(group_col)
    if has_groups:
        group_order = list(pd.unique(score_df["group"]))
        palette = {}
        for index, group in enumerate(group_order):
            key = GROUP_COLOR_KEYS[index % len(GROUP_COLOR_KEYS)]
            fallback = _theme_color(f"pca_group{index + 1}") if index < 4 else _QUALITATIVE[index % len(_QUALITATIVE)]
            palette[group] = st.session_state.get(key) or fallback
    else:
        group_order = [NO_GROUP]
        palette = {NO_GROUP: _theme_color("pca_group1")}
    fig = go.Figure()
    for group in group_order:
        mask = score_df["group"] == group
        subset_x = x_values[mask.to_numpy()]
        subset_y = y_values[mask.to_numpy()]
        if subset_x.size == 0:
            continue
        fig.add_trace(            go.Scatter(                x=subset_x,                y=subset_y,                mode="markers+text" if show_label else "markers",                name=str(group),                marker=dict(size=point_size, color=palette[group], opacity=opacity, line=dict(width=0)),                text=score_df.loc[mask, "sample"].tolist() if show_label else None,                textposition="top center",                textfont=dict(size=label_size, color=text_color),                hovertemplate=f"{group}<br>%{{text}}<br>PC%{{x:.2f}}<extra></extra>",            )        )
        if show_ellipse:
            points = _ellipse_points(subset_x, subset_y, ellipse_conf)
            if points is not None:
                fig.add_trace(                    go.Scatter(                        x=points[0],                        y=points[1],                        mode="lines",                        fill="toself",                        fillcolor=palette[group],                        line=dict(color=palette[group], width=1.4),                        opacity=0.12,                        name=f"{group} 置信椭圆",                        showlegend=False,                        hoverinfo="skip",                    )                )
    x_percent = explained[x_index] * 100.0
    y_percent = explained[y_index] * 100.0
    fig.update_layout(        height=560,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        font=dict(color=text_color),        margin=dict(l=70, r=30, t=60 if title else 30, b=60),        hovermode="closest",        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, x=1.02, xanchor="left", y=1),    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))    # 主成分得分是同一量纲，x/y 必须等比例，否则椭圆形状会被拉伸误读
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_xaxes(        title_text=f"{pc_labels[x_index]} ({x_percent:.1f}%)",        gridcolor="rgba(128,128,128,0.12)",        gridwidth=0.6,        zeroline=False,    )
    fig.update_yaxes(        title_text=f"{pc_labels[y_index]} ({y_percent:.1f}%)",        gridcolor="rgba(128,128,128,0.12)",        gridwidth=0.6,        zeroline=False,    )    # 零轴用虚线参考线（Plotly 的 zeroline 不支持 dash）
    zero_style = dict(color="rgba(128,128,128,0.45)", width=1, dash="dash")
    fig.add_hline(y=0, line=zero_style)
    fig.add_vline(x=0, line=zero_style)
    shared["last_plotly"] = fig
    shared["data"] = score_df
    status = (        f"PCA 就绪：{features.shape[0]} 样本 × {features.shape[1]} 特征；"        f"PC1 {explained[0] * 100:.1f}% / PC2 {explained[1] * 100:.1f}%"        if n_components >= 2        else f"PCA 就绪：{features.shape[0]} 样本 × {features.shape[1]} 特征；PC1 {explained[0] * 100:.1f}%"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, score_df, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render