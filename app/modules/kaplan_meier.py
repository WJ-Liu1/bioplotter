"""Kaplan-Meier — survival curves (architecture §3.10).

Curves are drawn with ``line_shape="hv"`` (Plotly's built-in step) + censor tick
markers; the log-rank test is implemented with numpy/scipy only (no
``lifelines`` dependency).  The optional risk table is a ``go.Table`` inside a
``specs=[[{"type":"xy"}], [{"type": "table"}]]`` subplot grid — a table trace
cannot live in an ``xy`` subplot.
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
Kaplan-Meier（生存曲线）

支持输入（CSV / TSV / TXT / XLSX）：
  - sample   样本 ID
  - time     随访时间（> 0）
  - status   结局状态（0/1 或 dead/alive …，值域可在左侧自定义）
  - group    分组

算法（numpy 手算，不依赖 lifelines）：
  - 每组在每个事件时点计算 S(t) = Π(1 - d/n)，用阶梯线绘制
  - 可选 95% 置信带（Greenwood 方差）
  - log-rank 检验：两组用闭式卡方，多组用 k-1 自由度二次型

可配置项：
  - 列映射、事件值域（逗号分隔，例如 "1,dead,死亡"）
  - 置信带 / 删失标记 / 风险表 / p 值开关，风险表时间点
  - 组 1–4 配色、删失点色、线宽、字号
  - 标题、X / Y 轴标题

说明：
  - status 取值不规范是最常见失败点，左侧「事件值域」可勾选哪些值算事件
  - 风险表用 go.Table 固定在下方 22% 高度
"""

# default event tokens; the control lets the user override them
DEFAULT_EVENTS = "1,dead,Dead,死亡,event,Event"
GROUP_COLOR_KEYS: tuple[str, ...] = ("km_color_g1", "km_color_g2", "km_color_g3", "km_color_g4")
MAX_GROUPS = 4
_FALLBACK_COLORS: dict[str, str] = {    "km_g1": "#E64B35",    "km_g2": "#4DBBD5",    "km_g3": "#00A087",    "km_g4": "#3C5488",    "km_censor": "#111827",    "bg": "#f5f7fb",    "text": "#111827",}
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {    "sample": ("sample", "sample_id", "id", "patient", "subject"),    "time": ("time", "os_time", "months", "days", "followup", "duration"),    "status": ("status", "event", "os_status", "dead", "outcome"),    "group": ("group", "arm", "treatment", "cohort", "stratum"),}
COLUMN_LABELS: dict[str, str] = {    "sample": "sample（样本 ID）",    "time": "time（时间 > 0）",    "status": "status（结局状态）",    "group": "group（分组）",}
_QUALITATIVE = ("#E64B35", "#4DBBD5", "#00A087", "#3C5488")# ---------------------------------------------------------------------------# Helpers# ---------------------------------------------------------------------------
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
    if st.session_state.get("km_use_sample", True):
        try:
            path = get_sample_path("km_survival")
            return read_table(path, path.name), ""
        except Exception as exc:
  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    uploaded = st.session_state.get("km_file_upload")
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
def _event_mask(status: pd.Series, tokens: set[str]) -> np.ndarray:
    """Robust event detection: numeric or textual, case-insensitive."""
    lowered = status.astype(str).str.strip().str.lower()
    return lowered.isin({token.lower() for token in tokens}).to_numpy()
def _km_curve(times: np.ndarray, events: np.ndarray) -> tuple[list[float], list[float], list[float], list[float]]:
    """Return ``(x, survival, ci_low, ci_high)`` for one group."""
    order = np.argsort(times, kind="mergesort")
    ordered_times = times[order].astype(float)
    ordered_events = events[order].astype(bool)
    event_times = np.unique(ordered_times[ordered_events])
    x_values: list[float] = [0.0]
    survival_values: list[float] = [1.0]
    ci_low_values: list[float] = [1.0]
    ci_high_values: list[float] = [1.0]
    survival = 1.0
    greenwood = 0.0
    for time_point in event_times:
        at_risk = float(np.sum(ordered_times >= time_point))
        deaths = float(np.sum((ordered_times == time_point) & ordered_events))
        if at_risk <= 0 or deaths <= 0:
            continue
        survival *= 1.0 - deaths / at_risk
        if at_risk - deaths > 0:
            greenwood += deaths / (at_risk * (at_risk - deaths))
        standard_error = survival * np.sqrt(greenwood)
        x_values.append(float(time_point))
        survival_values.append(float(survival))
        ci_low_values.append(float(max(0.0, survival - 1.96 * standard_error)))
        ci_high_values.append(float(min(1.0, survival + 1.96 * standard_error)))
    return x_values, survival_values, ci_low_values, ci_high_values
def _survival_at(x_values: list[float], y_values: list[float], time_point: float) -> float:
    value = 1.0
    for x, y in zip(x_values, y_values):
        if x <= time_point:
            value = y
        else:
            break
    return value
def _log_rank_core(labels: list[str], times: np.ndarray, events: np.ndarray) -> tuple[float, float]:
    """log-rank chi-square / p-value for k >= 2 groups (k-1 degrees of freedom)."""
    from scipy.stats import chi2 as chi2_dist
    groups = list(dict.fromkeys(labels))
    k = len(groups)
    if k < 2:
        return float("nan"), float("nan")
    index_of = {group: index for index, group in enumerate(groups)}
    codes = np.array([index_of[label] for label in labels])
    observed = np.zeros(k)
    expected = np.zeros(k)
    covariance = np.zeros((k, k))
    for time_point in np.unique(times[events]):
        at_risk = times >= time_point
        deaths = (times == time_point) & events
        n_total = float(at_risk.sum())
        d_total = float(deaths.sum())
        if n_total <= 0 or d_total <= 0:
            continue
        n_g = np.array([float(np.sum(at_risk & (codes == g))) for g in range(k)])
        d_g = np.array([float(np.sum(deaths & (codes == g))) for g in range(k)])
        observed += d_g
        expected += d_total * n_g / n_total
        if n_total > 1:
            factor = d_total * (n_total - d_total) / (n_total - 1)
            for i in range(k):
                for j in range(k):
                    delta = 1.0 if i == j else 0.0
                    covariance[i, j] += factor * (n_g[i] / n_total) * (delta - n_g[j] / n_total)
    z = observed - expected    # drop the last group to avoid the singular row/column
    z_reduced = z[:-1]
    v_reduced = covariance[:-1, :-1]
    try:
        chi_square = float(z_reduced @ np.linalg.pinv(v_reduced) @ z_reduced)
    except Exception:
        return float("nan"), float("nan")
    if not np.isfinite(chi_square) or chi_square < 0:
        return float("nan"), float("nan")
    p_value = float(chi2_dist.sf(chi_square, k - 1))
    return chi_square, p_value# ---------------------------------------------------------------------------# Controls# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()
    st.markdown("### 数据")
    sample_loader_control("km_use_sample", ["km_survival"], "km_load_sample_btn")
    if not st.session_state.get("km_use_sample", True):
        st.file_uploader(            "上传数据文件（CSV / TSV / TXT / XLSX）",            type=["csv", "tsv", "txt", "xlsx"],            key="km_file_upload",        )
    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        return
    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    detected = _detect_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    st.markdown("### 列映射")
    for dimension in ("sample", "time", "status", "group"):
        default = detected.get(dimension, all_cols[0])
        _pick(            COLUMN_LABELS[dimension],            all_cols,            f"km_col_{dimension}",            all_cols.index(default) if default in all_cols else 0,        )
    st.text_input("事件值域（逗号分隔）", DEFAULT_EVENTS, key="km_event_values")
    st.markdown("### 显示")
    st.checkbox("显示删失标记", value=True, key="km_show_censor")
    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=False, key="km_add_title")
    if st.session_state.get("km_add_title", False):
        st.text_input("图形标题", "Kaplan-Meier", key="km_title")
    st.text_input("X 轴标题", "Time", key="km_x_title")
    st.text_input("Y 轴标题", "Survival probability", key="km_y_title")
def advanced_controls(shared: dict) -> None:
    """Kaplan-Meier 的高级参数：统计标注、风险表与配色尺寸。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    st.markdown("### 统计标注")
    st.checkbox("显示 95% 置信带", value=False, key="km_show_ci")
    st.checkbox("显示风险表", value=True, key="km_show_risk_table")
    st.text_input(        "风险表时间点（逗号分隔）",        "0,12,24,36,48,60",        key="km_risk_timepoints",    )
    st.checkbox("显示 p 值", value=True, key="km_show_pvalue")
    st.markdown("### 配色与尺寸")
    for index in range(MAX_GROUPS):
        st.color_picker(            f"组 {index + 1} 颜色",            value=_theme_color(f"km_g{index + 1}"),            key=GROUP_COLOR_KEYS[index],        )
    st.color_picker("删失点颜色", value=_theme_color("km_censor"), key="km_color_censor")
    st.slider("曲线宽度", 1.0, 6.0, 2.4, 0.1, key="km_curve_width")
    st.slider("字号", 8, 18, 11, 1, key="km_font_size")# ---------------------------------------------------------------------------# Build# ---------------------------------------------------------------------------
def build(shared: dict):
    theme = _theme()
    frame, error = _load_frame()
    if frame is None:
        return None, None, error, HELP_TEXT
    if frame.empty:
        return None, None, "请先上传数据文件，或在左侧勾选「使用示例数据」。", HELP_TEXT
    detected = _detect_columns(frame)
    columns: dict[str, str] = {}
    for dimension in ("sample", "time", "status", "group"):
        chosen = st.session_state.get(f"km_col_{dimension}") or detected.get(dimension)
        if not chosen or chosen not in frame.columns:
            return (                None,                None,                f"缺少必需列：{COLUMN_LABELS[dimension]}。当前列：{', '.join(map(str, frame.columns))}",                HELP_TEXT,            )
        columns[dimension] = chosen
    raw_events = st.session_state.get("km_event_values", DEFAULT_EVENTS) or DEFAULT_EVENTS
    tokens = {token.strip() for token in raw_events.split(",") if token.strip()}
    work = pd.DataFrame(        {            "sample": frame[columns["sample"]].astype(str).str.strip(),            "time": pd.to_numeric(frame[columns["time"]], errors="coerce"),            "group": frame[columns["group"]].astype(str).str.strip(),        }    )
    work["event"] = _event_mask(frame[columns["status"]], tokens)
    work = work.dropna(subset=["time"])
    work = work[work["time"] > 0]
    work = work[work["group"] != ""]
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT
    group_order = list(dict.fromkeys(work["group"].tolist()))
    if len(group_order) > MAX_GROUPS:
        group_order = group_order[:MAX_GROUPS]
        work = work[work["group"].isin(group_order)].copy()
    if work.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT
    curve_width = float(st.session_state.get("km_curve_width", 2.4))
    font_size = int(st.session_state.get("km_font_size", 11))
    show_ci = bool(st.session_state.get("km_show_ci", False))
    show_censor = bool(st.session_state.get("km_show_censor", True))
    show_risk_table = bool(st.session_state.get("km_show_risk_table", True))
    show_pvalue = bool(st.session_state.get("km_show_pvalue", True))
    add_title = bool(st.session_state.get("km_add_title", False))
    title = (st.session_state.get("km_title") or "Kaplan-Meier") if add_title else ""
    x_title = st.session_state.get("km_x_title", "Time") or ""
    y_title = st.session_state.get("km_y_title", "Survival probability") or ""
    text_color = theme.get("text", "#111827")
    censor_color = st.session_state.get("km_color_censor") or _theme_color("km_censor")
    group_colors: dict[str, str] = {}
    for index, group in enumerate(group_order):
        key = GROUP_COLOR_KEYS[index % len(GROUP_COLOR_KEYS)]
        fallback = _theme_color(f"km_g{index + 1}") if index < 4 else _QUALITATIVE[index % len(_QUALITATIVE)]
        group_colors[group] = st.session_state.get(key) or fallback    # ---- log-rank --------------------------------------------------------
    times = work["time"].to_numpy(dtype=float)
    events = work["event"].to_numpy(dtype=bool)
    _, p_value = _log_rank_core(work["group"].tolist(), times, events)    # ---- risk table time points -----------------------------------------
    raw_points = st.session_state.get("km_risk_timepoints", "0,12,24,36,48,60") or ""
    risk_points: list[float] = []
    for chunk in raw_points.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            risk_points.append(float(chunk))
        except ValueError:
            continue
    if not risk_points:
        risk_points = [0.0, float(np.nanmax(times))]
    curves: dict[str, tuple[list[float], list[float], list[float], list[float]]] = {}
    for group in group_order:
        mask = (work["group"] == group).to_numpy()
        curves[group] = _km_curve(times[mask], events[mask])
    if show_risk_table:
        fig = make_subplots(            rows=2,            row_heights=[0.66, 0.34],            shared_xaxes=True,            vertical_spacing=0.16,            specs=[[{"type": "xy"}], [{"type": "table"}]],        )
        trace_row = 1
    else:
        fig = go.Figure()
        trace_row = None
    def _add(trace, **kwargs) -> None:
        if trace_row is None:
            fig.add_trace(trace)
        else:
            fig.add_trace(trace, row=trace_row, col=1)
    for group in group_order:
        x_values, y_values, ci_low, ci_high = curves[group]
        if show_ci and len(x_values) > 1:
            band_x = x_values + x_values[::-1]
            band_y = ci_high + ci_low[::-1]
            _add(                go.Scatter(                    x=band_x,                    y=band_y,                    mode="lines",                    line=dict(width=0),                    fill="toself",                    fillcolor=group_colors[group],                    opacity=0.14,                    name=f"{group} 95% CI",                    showlegend=False,                    hoverinfo="skip",                )            )
        _add(            go.Scatter(                x=x_values,                y=y_values,                mode="lines",                # NOTE: ``line_shape=`` and ``line=dict(...)`` are mutually                # exclusive in Plotly (the dict wins), so the step mode must be                # carried inside the ``line`` dict.
                line=dict(shape="hv", color=group_colors[group], width=curve_width),                name=f"{group} (n={int((work['group'] == group).sum())})",                hovertemplate=f"{group}<br>t=%{{x}}<br>S=%{{y:.3f}}<extra></extra>",            )        )
        if show_censor:
            group_mask = (work["group"] == group).to_numpy()
            censor_mask = group_mask & ~events
            if censor_mask.any():
                censor_times = times[censor_mask]
                censor_survival = [_survival_at(x_values, y_values, value) for value in censor_times]
                _add(                    go.Scatter(                        x=censor_times,                        y=censor_survival,                        mode="markers",                        marker=dict(symbol="cross", size=max(6, font_size - 1), color=censor_color, line=dict(width=1.1)),                        name=f"{group} 删失",                        showlegend=False,                        hovertemplate=f"{group} 删失<br>t=%{{x}}<extra></extra>",                    )                )
    if show_pvalue and np.isfinite(p_value):
        p_text = f"log-rank p = {p_value:.4g}"
        fig.add_annotation(            x=0.98,            y=0.96,            xref="paper",            yref="paper",            xanchor="right",            showarrow=False,            text=p_text,            font=dict(size=font_size, color=text_color),        )
    if show_risk_table:
        header_values = ["Time"] + [str(group) for group in group_order]
        cell_values: list[list] = [["%.4g" % value for value in risk_points]]
        for group in group_order:
            row_values = []
            group_times = times[(work["group"] == group).to_numpy()]
            for point in risk_points:
                row_values.append(str(int(np.sum(group_times >= point))))
            cell_values.append(row_values)
        fig.add_trace(            go.Table(                header=dict(                    values=[f"<b>{value}</b>" for value in header_values],                    fill_color=theme.get("panel", "#ffffff"),                    font=dict(color=text_color, size=max(9, font_size - 1)),                    align="center",                ),                cells=dict(                    values=cell_values,                    fill_color=theme.get("bg", "#f5f7fb"),                    font=dict(color=text_color, size=max(9, font_size - 1)),                    align="center",                    height=20,                ),            ),            row=2,            col=1,        )
    fig.update_layout(        height=700,        plot_bgcolor=theme.get("bg", "#f5f7fb"),        paper_bgcolor=theme.get("bg", "#f5f7fb"),        font=dict(color=text_color, size=font_size),        margin=dict(l=70, r=30, t=60 if title else 30, b=60),        legend=dict(bgcolor="rgba(0,0,0,0)", x=1.02, xanchor="left", y=1),    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=17, color=text_color)))
    fig.update_xaxes(        title_text=x_title,        gridcolor="rgba(128,128,128,0.2)",        range=[0, float(np.nanmax(times)) * 1.02],    )
    fig.update_yaxes(        title_text=y_title,        range=[0, 1.02],        gridcolor="rgba(128,128,128,0.12)",        gridwidth=0.6,    )
    preview = work.rename(columns={"event": "is_event"}).reset_index(drop=True)
    events_total = int(events.sum())
    p_text = f"log-rank p = {p_value:.4g}" if np.isfinite(p_value) else "log-rank p = N/A"
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (        f"Kaplan-Meier 就绪：{len(work)} 例 / {len(group_order)} 组"        f"（事件 {events_total} 例）；{p_text}"    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT
def render(shared: dict):
    controls(shared)
    return build(shared)
__call__ = render