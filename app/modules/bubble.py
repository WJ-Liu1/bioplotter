"""BubbleViz — native Plotly rewrite of the original Vue 3 + ECharts app.

Implements architecture doc §3.1.

* 4D static mapping — ``x`` / ``y`` / ``size`` / ``hue`` (group colour)
* optional 5th ``frame`` column drives per-frame animation with a play / pause
  button pair and a time slider
* log10 size normalisation into ``[bubble_size_min, bubble_size_scale]`` pixels
* opacity, marker symbol, optional log10 X axis, group filtering (max 5)
* title switch + aspect ratio

The animated figure is hand-built (``go.Figure`` + ``frames`` + ``updatemenus`` +
``sliders``) instead of ``px.scatter(animation_frame=...)``: Express cannot keep
per-frame marker sizes and re-scales the axes on every frame (architecture D8).
All axis ranges are therefore computed once from the full data set.

Key naming follows §8.2: column mappings are ``*_col`` / ``bubble_hue_col`` and
never contain the ``color/fill/edge/line/bg/reg`` substrings that
``reset_module_colors()`` filters on.  Only the real colour picker is
``bubble_point_color``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.colors import sample_colorscale
import streamlit as st

from app.core.io_utils import read_table
from app.core.palettes import palette_for
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """BubbleViz（原生气泡图）

支持输入（宽表 CSV / TSV / TXT / XLSX）：
  - 必需：x、y 两列数值
  - 可选：size（数值 > 0）、hue（分组列）、frame（时间 / 帧列）
  - 列名不区分大小写，会按别名自动匹配；匹配不到时手动在下拉框中选择

功能：
  - 四维静态映射：x / y / 气泡大小 / 分组配色
  - 第五维动画：frame 列驱动逐帧播放，带播放/暂停按钮与时间滑杆
  - 气泡大小按 log10 归一化到 [最小直径, 最大直径]，避免极端值压扁图形
  - 透明度、气泡形状（circle / square / triangle）、X 轴 log10 变换
  - 配色方案可选 Viridis / Plasma / Bluyl / Sunset，每个分组自动取色
  - 分组多选筛选（最多 5 组）
  - 图形标题开关、16:9 / 2:1 / 4:3 / 3:4 宽高比

说明：
  - 动画帧的坐标轴范围固定为全量数据范围，播放时不会跳轴
  - 帧数超过 60 时会自动截取前 60 帧并在状态栏提示
  - 原版 GIF 导出现在走站点导出中心（HTML 交互 + 当前帧 PNG）
"""

_SINGLE = "(单色)"
_FIXED_SIZE = "(固定大小)"

SAMPLE_LABELS: dict[str, str] = {
    "bubble_country": "国家发展（data1 · 含 Year，可动画）",
    "bubble_aqi": "城市空气质量（data2 · 静态）",
}

# Seeded defaults for the two built-in samples; uploads use the alias table.
SAMPLE_MAPPINGS: dict[str, dict[str, str | None]] = {
    "bubble_country": {
        "x": "GDP per capita",
        "y": "Life expectancy",
        "size": "Population",
        "hue": "Continent",
        "frame": "Year",
    },
    "bubble_aqi": {
        "x": "PM2.5",
        "y": "AQI",
        "size": "SO2",
        "hue": "City",
        "frame": None,
    },
}

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "x": ("x", "time", "date"),
    "y": ("y", "value"),
    "size": ("size", "population", "count"),
    "hue": ("color", "colour", "continent", "group", "category"),
    "frame": ("frame", "year", "date", "time"),
}

ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "16:9": (960, 540),
    "2:1": (1000, 500),
    "4:3": (880, 660),
    "3:4": (660, 880),
}

SYMBOL_OPTIONS: tuple[str, ...] = ("circle", "square", "triangle-up")
PALETTE_NAMES: tuple[str, ...] = ("SCI 期刊色板", "Viridis", "Plasma", "Bluyl", "Sunset")
MAX_FRAMES = 60

_FALLBACK_COLORS: dict[str, str] = {
    "bubble_point": "#4C78A8",
    "bubble_low": "#BBD7EC",
    "bubble_high": "#0B3C5D",
    "bg": "#f5f7fb",
    "text": "#111827",
    "panel": "#ffffff",
    "muted": "#6b7280",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def html_escape(value) -> str:
    import html as _html

    return _html.escape(str(value))


def _theme() -> dict:
    return THEMES.get(st.session_state.get("theme", "Light"), THEMES["Light"])


def _theme_color(key: str) -> str:
    """Theme colour with a module-local fallback (arch §3.0)."""
    return _theme().get(key, _FALLBACK_COLORS.get(key, "#4C78A8"))


def _select_option(label: str, options: list[str], key: str, index: int = 0):
    """``st.selectbox`` that tolerates stale session values after
    a data change."""
    if not options:
        options = ["—"]
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]
    if key in st.session_state:
        return st.selectbox(label, options, key=key)
    return st.selectbox(label, options, index=min(index, len(options) - 1), key=key)


def _palette_colors(name: str, count: int) -> list[str]:
    """SCI 色板直接取模块主题色；其余走 Plotly 连续色阶采样。"""
    if name == "SCI 期刊色板":
        base = list(palette_for("BubbleViz"))
        # 气泡是实体填充，跳掉接近白色的底色（否则浅色背景上几乎看不见）
        usable = [c for c in base if sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) < 690] or base
        colors = list(usable)
        # 分组数超过色板容量时，用同色相加深的派生色补齐，避免出现重复色
        while len(colors) < count:
            source = usable[len(colors) % len(usable)]
            raw = source.lstrip("#")
            rgb = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
            colors.append("#" + "".join(f"{round(v * 0.72):02X}" for v in rgb))
        return colors[:count]

    scale = getattr(px.colors.sequential, name, None) or px.colors.sequential.Viridis
    if count <= 1:
        return [sample_colorscale(scale, [0.65])[0]]
    stops = [index / (count - 1) for index in range(count)]
    return sample_colorscale(scale, stops)


def _load_frame() -> tuple[pd.DataFrame | None, str]:
    use_sample = st.session_state.get("bubble_use_sample", True)
    if use_sample:
        pick = st.session_state.get("bubble_sample_pick", "bubble_country")
        if pick not in SAMPLE_LABELS:
            pick = "bubble_country"
        try:
            path = get_sample_path(pick)
            return read_table(path, path.name), ""
        except Exception as exc:  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"

    uploaded = st.session_state.get("bubble_file_upload")
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""


def _numeric_columns(frame: pd.DataFrame) -> list[str]:
    return [str(c) for c in frame.columns if pd.to_numeric(frame[c], errors="coerce").notna().mean() >= 0.8]


def _alias_match(frame: pd.DataFrame, dimension: str, numeric_only: bool) -> str | None:
    lowered = {str(c).strip().lower(): str(c) for c in frame.columns}
    numeric = set(_numeric_columns(frame))
    for alias in COLUMN_ALIASES.get(dimension, ()):
        candidate = lowered.get(alias)
        if candidate is None:
            continue
        if numeric_only and candidate not in numeric:
            continue
        return candidate
    return None


def _scale_sizes(values: pd.Series, min_px: float, max_px: float) -> np.ndarray:
    """log10-normalise ``values`` into ``[min_px, max_px]`` pixel diameters."""
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    numeric = np.where(np.isfinite(numeric), numeric, np.nan)
    # arch §8.4: never feed 0 or negatives into log10
    logged = np.log10(np.clip(numeric, 1.0, None))
    valid = logged[np.isfinite(logged)]
    if valid.size == 0:
        return np.full(len(logged), (min_px + max_px) / 2.0)
    low, high = float(valid.min()), float(valid.max())
    if np.isclose(low, high):
        return np.full(len(logged), (min_px + max_px) / 2.0)
    scaled = min_px + (logged - low) * (max_px - min_px) / (high - low)
    return np.clip(np.where(np.isfinite(scaled), scaled, min_px), min_px, max_px)


def _apply_mapping(pick: str | None, frame: pd.DataFrame) -> None:
    """Seed the mapping widgets once per data source."""
    token = pick or f"upload:{frame.shape}"
    if st.session_state.get("_bubble_mapped_for") == token:
        return
    preset = SAMPLE_MAPPINGS.get(pick or "", {})
    numeric = _numeric_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    defaults = {
        "x": preset.get("x") or _alias_match(frame, "x", True) or (numeric[0] if numeric else all_cols[0]),
        "y": preset.get("y")
        or _alias_match(frame, "y", True)
        or (numeric[1] if len(numeric) > 1 else (numeric[0] if numeric else all_cols[-1])),
        "size": preset.get("size") or _alias_match(frame, "size", True) or _FIXED_SIZE,
        "hue": preset.get("hue") or _alias_match(frame, "hue", False) or _SINGLE,
        "frame": preset.get("frame") or _alias_match(frame, "frame", False) or "无",
    }
    for dimension, value in defaults.items():
        # NOTE: the hue column widget is keyed ``bubble_hue_col`` (the other
        # column mappings follow the ``bubble_col_<dimension>`` pattern).
        state_key = "bubble_hue_col" if dimension == "hue" else f"bubble_col_{dimension}"
        st.session_state[state_key] = value
    st.session_state["_bubble_mapped_for"] = token


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    frame, _ = _load_frame()

    st.markdown("### 数据")
    sample_loader_control(
        "bubble_use_sample",
        ["bubble_country", "bubble_aqi"],
        "bubble_load_sample_btn",
    )

    use_sample = st.session_state.get("bubble_use_sample", True)
    if use_sample:
        st.selectbox(
            "示例数据集",
            options=list(SAMPLE_LABELS.keys()),
            format_func=lambda key: SAMPLE_LABELS[key],
            key="bubble_sample_pick",
        )
    else:
        st.file_uploader(
            "上传数据文件（CSV / TSV / TXT / XLSX）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="bubble_file_upload",
        )

    if frame is None:
        st.info("等待可用的数据文件，其余控件在数据就绪后生效。")
        st.text_input("图形标题", "Bubble Chart", key="bubble_title")
        return

    st.caption(f"已读取 {frame.shape[0]} 行 × {frame.shape[1]} 列")
    _apply_mapping(st.session_state.get("bubble_sample_pick") if use_sample else None, frame)

    numeric_cols = _numeric_columns(frame)
    all_cols = [str(c) for c in frame.columns]
    size_options = [_FIXED_SIZE] + (numeric_cols or all_cols)
    hue_options = [_SINGLE] + all_cols
    frame_options = ["无"] + all_cols

    st.markdown("### 列映射")
    _select_option("X 轴（数值）", numeric_cols or all_cols, "bubble_col_x")
    _select_option("Y 轴（数值）", numeric_cols or all_cols, "bubble_col_y")
    _select_option("气泡大小（数值 > 0）", size_options, "bubble_col_size")
    _select_option("分组配色列", hue_options, "bubble_hue_col")

    st.markdown("### 模式与外观")
    _select_option("配色方案", list(PALETTE_NAMES), "bubble_palette")
    st.slider("最大气泡直径 (px)", 10, 120, 40, 5, key="bubble_size_scale")
    st.slider("最小气泡直径 (px)", 2, 24, 6, 1, key="bubble_size_min")
    st.slider("透明度", 0.1, 1.0, 0.75, 0.05, key="bubble_opacity")
    st.selectbox("气泡形状", list(SYMBOL_OPTIONS), index=0, key="bubble_symbol")

    hue_col = st.session_state.get("bubble_hue_col", _SINGLE)
    if hue_col != _SINGLE and hue_col in frame.columns:
        groups = [str(value) for value in pd.unique(frame[hue_col].astype(str))]
        current = st.session_state.get("bubble_hue_sel")
        if current is None or any(value not in groups for value in current):
            st.session_state["bubble_hue_sel"] = groups[:5]
        st.multiselect(
            "显示分组（最多 5 组）",
            options=groups,
            max_selections=5,
            key="bubble_hue_sel",
        )
    else:
        st.color_picker("单色气泡颜色", value=_theme_color("bubble_point"), key="bubble_point_color")

    st.markdown("### 标题")
    st.checkbox("添加图形标题", value=True, key="bubble_add_title")
    if st.session_state.get("bubble_add_title", True):
        st.text_input("图形标题", "Bubble Chart", key="bubble_title")


def advanced_controls(shared: dict) -> None:
    """Bubble 的高级参数：动画、坐标变换与数据标签。"""
    frame, _ = _load_frame()
    if frame is None or frame.empty:
        return
    all_cols = [str(c) for c in frame.columns]
    frame_options = ["无"] + all_cols
    st.radio("输出模式", ["静态", "动画"], index=0, key="bubble_mode", horizontal=True)
    if st.session_state.get("bubble_mode") == "动画":
        _select_option("动画帧列", frame_options, "bubble_col_frame")
        st.number_input("帧间隔 (ms)", min_value=200, max_value=3000, value=600, step=50, key="bubble_frame_ms")
    st.checkbox("X 轴 log10 变换", value=False, key="bubble_xlog")
    st.selectbox("宽高比", list(ASPECT_PRESETS.keys()), index=0, key="bubble_aspect")
    st.checkbox("显示数据标签", value=False, key="bubble_show_label")
    if st.session_state.get("bubble_show_label", False):
        st.slider("标签字号", 8, 18, 10, 1, key="bubble_label_size")


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

    numeric_cols = _numeric_columns(frame)
    x_col = st.session_state.get("bubble_col_x") or (numeric_cols[0] if numeric_cols else None)
    y_col = st.session_state.get("bubble_col_y") or (numeric_cols[-1] if numeric_cols else None)
    if not x_col or x_col not in frame.columns:
        return None, None, f"缺少必需列：x。当前列：{', '.join(map(str, frame.columns))}", HELP_TEXT
    if not y_col or y_col not in frame.columns:
        return None, None, f"缺少必需列：y。当前列：{', '.join(map(str, frame.columns))}", HELP_TEXT

    size_col = st.session_state.get("bubble_col_size", _FIXED_SIZE)
    hue_col = st.session_state.get("bubble_hue_col", _SINGLE)
    has_size = bool(size_col and size_col != _FIXED_SIZE and size_col in frame.columns)
    has_hue = bool(hue_col and hue_col != _SINGLE and hue_col in frame.columns)

    work = frame.copy()
    work[x_col] = pd.to_numeric(work[x_col], errors="coerce")
    work[y_col] = pd.to_numeric(work[y_col], errors="coerce")
    work = work.dropna(subset=[x_col, y_col])
    if has_size:
        work[size_col] = pd.to_numeric(work[size_col], errors="coerce")
        work = work.dropna(subset=[size_col])
    if work.empty:
        return None, None, "x / y 两列没有可用数值行。", HELP_TEXT

    # ---- group filter -----------------------------------------------------
    if has_hue:
        work[hue_col] = work[hue_col].astype(str)
        all_groups = [str(value) for value in pd.unique(work[hue_col])]
        selected = st.session_state.get("bubble_hue_sel") or all_groups[:5]
        work = work[work[hue_col].isin(selected)].copy()
        if work.empty:
            return None, None, "当前筛选无数据可绘制。", HELP_TEXT
        group_order = [value for value in all_groups if value in set(work[hue_col])]
    else:
        group_order = [_SINGLE]
        work["_bubble_group"] = _SINGLE
    group_field = hue_col if has_hue else "_bubble_group"

    # ---- appearance -------------------------------------------------------
    min_px = float(st.session_state.get("bubble_size_min", 6))
    max_px = float(st.session_state.get("bubble_size_scale", 40))
    if max_px <= min_px:
        max_px = min_px + 4.0
    opacity = float(st.session_state.get("bubble_opacity", 0.75))
    symbol = st.session_state.get("bubble_symbol", "circle")
    use_xlog = bool(st.session_state.get("bubble_xlog", False))
    aspect = st.session_state.get("bubble_aspect", "16:9")
    width, height = ASPECT_PRESETS.get(aspect, ASPECT_PRESETS["16:9"])
    show_label = bool(st.session_state.get("bubble_show_label", False))
    label_size = int(st.session_state.get("bubble_label_size", 10))
    add_title = bool(st.session_state.get("bubble_add_title", True))
    title = (st.session_state.get("bubble_title") or "Bubble Chart") if add_title else ""

    if has_size:
        work["_bubble_size_px"] = _scale_sizes(work[size_col], min_px, max_px)
    else:
        work["_bubble_size_px"] = (min_px + max_px) / 2.0

    if has_hue:
        colors = _palette_colors(st.session_state.get("bubble_palette", PALETTE_NAMES[0]), len(group_order))
        palette = {group: colors[index % len(colors)] for index, group in enumerate(group_order)}
    else:
        palette = {_SINGLE: st.session_state.get("bubble_point_color") or _theme_color("bubble_point")}

    # ---- fixed axis ranges (shared by every frame) ------------------------
    def _axis_range(series: pd.Series, log_mode: bool) -> list[float] | None:
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if log_mode:
            values = values[values > 0]
            if values.size == 0:
                return None
            values = np.log10(values)
        if values.size == 0:
            return None
        low, high = float(values.min()), float(values.max())
        pad = (high - low) * 0.06 if not np.isclose(low, high) else max(abs(low) * 0.1, 0.5)
        return [low - pad, high + pad]

    x_range = _axis_range(work[x_col], use_xlog)
    y_range = _axis_range(work[y_col], False)

    def _trace(subset: pd.DataFrame, group: str) -> go.Scatter:
        return go.Scatter(
            x=subset[x_col],
            y=subset[y_col],
            mode="markers+text" if show_label else "markers",
            name=str(group),
            marker=dict(
                size=subset["_bubble_size_px"],
                color=palette.get(str(group), _theme_color("bubble_point")),
                symbol=symbol,
                opacity=opacity,
                line=dict(width=1, color=theme.get("text", "#111827")),
            ),
            text=subset[hue_col] if (show_label and has_hue) else (subset[x_col] if show_label else None),
            textposition="top center",
            textfont=dict(size=label_size, color=theme.get("text", "#111827")),
            customdata=subset[[x_col, y_col]].to_numpy(),
            hovertemplate=(
                f"{hue_col}: {group}<br>" if has_hue else ""
            )
            + f"{x_col}: %{{customdata[0]:g}}<br>{y_col}: %{{customdata[1]:g}}<extra></extra>",
        )

    layout_common: dict = dict(
        width=width,
        height=height,
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        font=dict(color=theme.get("text", "#111827")),
        hovermode="closest",
        legend=dict(
            title=dict(text=hue_col if has_hue else ""),
            bgcolor="rgba(0,0,0,0)",
            x=1.02,
            xanchor="left",
            y=1,
        ),
    )
    if title:
        layout_common["title"] = dict(text=title, font=dict(size=18, color=theme.get("text", "#111827")))

    def _size_legend_annotation() -> None:
        """在右下角标注气泡大小映射（注释而非 trace，动画帧不会丢失）。"""
        if not has_size:
            return
        values = pd.to_numeric(work[size_col], errors="coerce").dropna()
        if values.empty:
            return
        low, mid, high = float(values.min()), float(values.median()), float(values.max())
        fig.add_annotation(
            x=1.0,
            y=0.02,
            xref="paper",
            yref="paper",
            xanchor="right",
            yanchor="bottom",
            showarrow=False,
            align="right",
            text=(
                f"<span style='font-size:10px;color:{theme.get('muted', '#6b7280')}'>"
                f"size = {html_escape(size_col)}</span><br>"
                f"<span style='font-size:10px;color:{theme.get('muted', '#6b7280')}'>"
                f"{low:,.0f} · {mid:,.0f} · {high:,.0f}</span>"
            ),
        )

    frame_col = st.session_state.get("bubble_col_frame", "无")
    want_anim = (
        st.session_state.get("bubble_mode", "静态") == "动画"
        and frame_col
        and frame_col != "无"
        and frame_col in work.columns
    )

    # ---- static -----------------------------------------------------------
    if not want_anim:
        fig = go.Figure()
        for group in group_order:
            subset = work[work[group_field] == group]
            if subset.empty:
                continue
            fig.add_trace(_trace(subset, group))
        if not has_hue and len(fig.data) == 1:
            fig.data[0].showlegend = False
        fig.update_layout(**layout_common)
        fig.update_layout(margin=dict(l=60, r=30, t=60 if title else 30, b=60))
        fig.update_xaxes(
            title_text=x_col,
            type="log" if use_xlog else "linear",
            range=x_range,
            gridcolor="rgba(128,128,128,0.12)",
            gridwidth=0.6,
            zeroline=False,
        )
        fig.update_yaxes(
            title_text=y_col,
            range=y_range,
            gridcolor="rgba(128,128,128,0.12)",
            gridwidth=0.6,
            zeroline=False,
        )
        _size_legend_annotation()
        preview = work.drop(columns=[c for c in ("_bubble_size_px", "_bubble_group") if c in work.columns])
        preview = preview.reset_index(drop=True)
        shared["last_plotly"] = fig
        shared["data"] = preview
        status = (
            f"BubbleViz 就绪：{len(work)} 行 × {frame.shape[1]} 列；静态图 "
            f"{len(fig.data)} 个分组；x={x_col} / y={y_col}"
            + (f" / size={size_col}" if has_size else "")
            + (f" / hue={hue_col}" if has_hue else "")
        )
        shared["status"] = status
        shared["help_text"] = HELP_TEXT
        return fig, preview, status, HELP_TEXT

    # ---- animated ---------------------------------------------------------
    work[frame_col] = work[frame_col].astype(str)
    frame_values = list(pd.unique(work[frame_col]))
    try:
        frame_values = sorted(frame_values, key=lambda value: float(value))
    except (TypeError, ValueError):
        frame_values = sorted(frame_values)
    truncated = 0
    if len(frame_values) > MAX_FRAMES:
        truncated = len(frame_values) - MAX_FRAMES
        frame_values = frame_values[:MAX_FRAMES]
        work = work[work[frame_col].isin(frame_values)].copy()

    def _frame_traces(snapshot: pd.DataFrame) -> list[go.Scatter]:
        traces: list[go.Scatter] = []
        for group in group_order:
            subset = snapshot[snapshot[group_field] == group]
            if subset.empty:
                # keep the trace count stable so legend bindings never shift
                traces.append(
                    go.Scatter(
                        x=[None],
                        y=[None],
                        mode="markers",
                        name=str(group),
                        marker=dict(size=0, color=palette.get(str(group), "#4C78A8")),
                        showlegend=has_hue,
                    )
                )
                continue
            trace = _trace(subset, group)
            trace.showlegend = has_hue
            traces.append(trace)
        return traces

    frames = [
        go.Frame(name=str(value), data=_frame_traces(work[work[frame_col] == value]))
        for value in frame_values
    ]
    fig = go.Figure(data=_frame_traces(work[work[frame_col] == frame_values[0]]), frames=frames)
    fig.update_layout(**layout_common)
    fig.update_layout(
        height=height + 90,
        margin=dict(l=60, r=30, t=60 if title else 30, b=190),
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                x=0.0,
                y=-0.30,
                xanchor="left",
                yanchor="top",
                showactive=False,
                pad=dict(t=0, r=6, b=0, l=0),
                bgcolor=theme.get("panel", "#ffffff"),
                bordercolor=theme.get("muted", "#6b7280"),
                font=dict(color=theme.get("text", "#111827")),
                buttons=[
                    dict(
                        label="▶ 播放",
                        method="animate",
                        args=[
                            None,
                            dict(
                                frame=dict(duration=int(st.session_state.get("bubble_frame_ms", 600)), redraw=True),
                                transition=dict(duration=280, easing="cubic-in-out"),
                                fromcurrent=True,
                                mode="immediate",
                            ),
                        ],
                    ),
                    dict(
                        label="⏸ 暂停",
                        method="animate",
                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")],
                    ),
                ],
            )
        ],
        sliders=[
            dict(
                active=0,
                currentvalue=dict(
                    prefix=f"{frame_col} = ",
                    font=dict(color=theme.get("text", "#111827"), size=14),
                    xanchor="center",
                ),
                transition=dict(duration=200),
                pad=dict(b=10, t=40),
                len=0.9,
                x=0.05,
                y=-0.14,
                steps=[
                    dict(
                        label=str(value),
                        method="animate",
                        args=[
                            [str(value)],
                            dict(mode="immediate", frame=dict(duration=300, redraw=True), transition=dict(duration=200)),
                        ],
                    )
                    for value in frame_values
                ],
            )
        ],
    )
    fig.update_xaxes(
        title_text=x_col,
        type="log" if use_xlog else "linear",
        range=x_range,
        gridcolor="rgba(128,128,128,0.12)",
        gridwidth=0.6,
        zeroline=False,
    )
    fig.update_yaxes(
        title_text=y_col,
        range=y_range,
        gridcolor="rgba(128,128,128,0.12)",
        gridwidth=0.6,
        zeroline=False,
    )
    _size_legend_annotation()
    preview = work.drop(columns=[c for c in ("_bubble_size_px", "_bubble_group") if c in work.columns])
    preview = preview.reset_index(drop=True)
    shared["last_plotly"] = fig
    shared["data"] = preview
    status = (
        f"BubbleViz 就绪：{len(work)} 行 × {frame.shape[1]} 列；动画帧 {len(frame_values)} 个"
        f"（{frame_values[0]}–{frame_values[-1]}）；x={x_col} / y={y_col}"
        + (f" / hue={hue_col}" if has_hue else "")
    )
    if truncated:
        status += f"；帧数过多，已截取前 {MAX_FRAMES} 帧（省略 {truncated} 帧）"
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, preview, status, HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
