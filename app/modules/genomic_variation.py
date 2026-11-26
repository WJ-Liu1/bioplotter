"""Genomic Variation Viewer — native Plotly implementation.

Implements architecture doc §3.5.

One Cartesian coordinate system holds three stacked tracks (architecture D2):

=================  ================  =========================================
track              y band            rendering
=================  ================  =========================================
upper SNP          ``0.55 – 0.95``   stems (single trace, ``None`` gaps) + markers
gene structure     ``0.40 – 0.50``   one ``add_shape`` rect per block + text trace
lower SNP          ``0.45 – 0.05``   stems (single trace, ``None`` gaps) + markers
=================  ================  =========================================

* ``mode="lines+markers"`` is **not** used: the marker would also be drawn on the
  baseline end of every ``None``-separated segment, so stems and heads are two
  separate traces per track (architecture D2 / §3.5).
* ``yaxis.range`` is pinned to ``[0, 1]`` so an empty track never rescales the
  other two.
* ``data`` is a ``dict[str, DataFrame]`` — ``render_data_preview()`` turns it into
  three tabs.
* ``flag`` has no Plotly symbol, so it falls back to ``triangle-up`` with a guard.

Key naming follows §8.2 — the module prefix is ``genvar_`` (not ``gvar_``).
"""

from __future__ import annotations

import colorsys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
Genomic Variation Viewer（原生基因组变异轨道图）

支持输入（2~3 个 CSV / TSV / TXT / XLSX，三列，带不带表头均可）：
  1. Gene Structure：name, start, end
  2. Upper SNP：name, position, score(可选)
  3. Lower SNP：name, position, score(可选)，仅 lollipop 模式需要

两种模式：
  - Lollipop：上层 SNP 轨道 + 基因结构块 + 下层 SNP 轨道
  - Dandelion：去掉下轨，单层从中心线向外发散

功能：
  - 基因结构按 start / end 画区间矩形块，块高可调
  - SNP 棒棒糖：垂直线（stem）+ 头部标记（circle / flag）
  - 显示区间过滤：start / end 输入 + 「恢复全区间」按钮
  - SNP 大小三模式：统一 / 随机 / 自定义（配合「逐项覆盖」表格）
  - SNP 配色两模式：随机 / 单色
  - SNP 标签显隐与字号、X 轴显隐、标题

说明：
  - 三条轨道共用一个 Cartesian 坐标系，Y 轴范围固定 [0, 1]，不使用 subplot
  - 每层棒棒糖用「单 trace + None 断点」绘制，N 个 SNP 只占 1 条线 trace
  - 首期不做 GFF3 全量解析（只接受三列简化 CSV）
  - 原版 pin 形状用 circle + 短杆近似，flag 用三角头近似
"""

MODE_LOLLIPOP = "Lollipop（上下双层）"
MODE_DANDELION = "Dandelion（单层发散）"

MARKER_SHAPES: dict[str, str] = {
    "circle": "圆形 (circle)",
    "flag": "旗帜 (flag，近似为三角头)",
    "pin": "图钉 (pin，双色圆头)",
}

SIZE_MODES: tuple[str, ...] = ("统一", "随机", "自定义")
FEATURE_PALETTE_MODES: tuple[str, ...] = ("多色", "单色")
PALETTE_MODES: tuple[str, ...] = ("随机", "单色")

# Y layout (architecture §3.5) — single Cartesian system, no subplots.
GENE_BAND_CENTRE = 0.45
UPPER_BASE = 0.55
UPPER_TOP = 0.95
LOWER_BASE = 0.45
LOWER_BOTTOM = 0.05

FEATURE_BASE_COLORS = (
    "#699ECA",
    "#FF8C00",
    "#F898CB",
    "#4DAF4A",
    "#D65190",
    "#731A73",
    "#FFCB5B",
    "#E87B1E",
    "#0076B9",
    "#3D505A",
    "#0098B2",
    "#E41A1C",
    "#377EB8",
    "#984EA3",
    "#FF7F00",
    "#A65628",
    "#66C2A5",
    "#FC8D62",
    "#8DA0CB",
    "#E78AC3",
    "#1B9E77",
    "#D95F02",
    "#7570B3",
    "#E7298A",
    "#66A61E",
    "#00CED1",
    "#FF6347",
    "#9ACD32",
    "#8B4513",
    "#2E8B57",
    "#6A5ACD",
    "#DC143C",
    "#00FA9A",
    "#FFD700",
    "#FF69B4",
)

RICH_COLORS = (
    "#E41A1C",
    "#377EB8",
    "#4DAF4A",
    "#984EA3",
    "#FF7F00",
    "#FFFF33",
    "#A65628",
    "#F781BF",
    "#999999",
    "#66C2A5",
    "#FC8D62",
    "#8DA0CB",
    "#E78AC3",
    "#A6D854",
    "#FFD92F",
    "#E5C494",
    "#B3B3B3",
    "#1B9E77",
    "#D95F02",
    "#7570B3",
    "#E7298A",
    "#66A61E",
    "#E6AB02",
    "#A6761D",
    "#666666",
    "#8DD3C7",
    "#FFFFB3",
    "#BEBADA",
    "#FB8072",
    "#80B1D3",
    "#FDB462",
    "#B3DE69",
    "#FCCDE5",
    "#D9D9D9",
    "#BC80BD",
    "#CCEBC5",
    "#FFED6F",
    "#00CED1",
    "#FF6347",
    "#9ACD32",
)

SNP_BORDER_COLOR = "#4D4D4D"

_VALID_MARKERS = frozenset({"circle", "triangle-up", "square", "diamond", "triangle-down"})

_FALLBACK_COLORS: dict[str, str] = {
    "genvar_feature": "#4C78A8",
    "genvar_snp": "#98CE31",
    "genvar_upper": "#98CE31",
    "genvar_lower": "#3B7DD8",
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


def _hsv_hex(hue: float, saturation: float, value: float) -> str:
    red, green, blue = colorsys.hsv_to_rgb(float(hue) % 1.0, float(saturation), float(value))
    return f"#{int(round(red * 255)):02X}{int(round(green * 255)):02X}{int(round(blue * 255)):02X}"


def _feature_colors(count: int) -> list[str]:
    """固定色板优先，超出后按 HSV 均匀补色。"""
    if count <= 0:
        return []
    if count <= len(FEATURE_BASE_COLORS):
        return list(FEATURE_BASE_COLORS[:count])
    extra = count - len(FEATURE_BASE_COLORS)
    hues = np.linspace(0.0, 1.0, extra + 1)[:extra]
    return list(FEATURE_BASE_COLORS) + [_hsv_hex(hue, 0.7, 0.8) for hue in hues]


def _random_colors(count: int, seed: int) -> list[str]:
    """从丰富色板随机取色，数量超出时改用随机 HSV。"""
    if count <= 0:
        return []
    rng = np.random.default_rng(int(seed))
    if count <= len(RICH_COLORS):
        indices = rng.choice(len(RICH_COLORS), size=count, replace=False)
        return [RICH_COLORS[int(index)] for index in indices]
    return [
        _hsv_hex(rng.uniform(0.0, 1.0), rng.uniform(0.5, 1.0), rng.uniform(0.6, 0.95))
        for _ in range(count)
    ]


def _smart_xlabels(start: float, end: float) -> list[int]:
    """生成整齐、数量适中的 X 轴刻度。"""
    span = float(end) - float(start)
    if span <= 0:
        return [int(round(start)), int(round(end))]
    nice_steps = (
        1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500,
        1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000,
        100000, 200000, 250000, 500000, 1000000,
    )
    ideal_step = span / 4.0
    step = min(nice_steps, key=lambda candidate: abs(candidate - ideal_step))
    label_count = int(np.floor(span / step)) + 1
    if label_count > 8:
        larger = [candidate for candidate in nice_steps if candidate > step]
        step = larger[0] if larger else nice_steps[-1]
    elif label_count < 3:
        index = nice_steps.index(step)
        if index > 0:
            step = nice_steps[index - 1]

    first_nice = np.ceil(float(start) / step) * step
    if first_nice > float(end):
        labels = [float(start), float(end)]
    else:
        nice_labels = np.arange(first_nice, float(end) + step * 1e-9, step)
        labels = [float(start), *[float(value) for value in nice_labels], float(end)]
    return sorted({int(np.floor(value + 1e-9)) for value in labels})


def _read_any(uploaded, sample_key: str | None) -> tuple[pd.DataFrame | None, str]:
    if sample_key is not None:
        try:
            path = get_sample_path(sample_key)
            return read_table(path, path.name), ""
        except Exception as exc:  # pragma: no cover - filesystem guard
            return None, f"文件解析失败：{exc}"
    if uploaded is None:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    try:
        frame = read_table(uploaded, getattr(uploaded, "name", "uploaded.csv"))
    except Exception as exc:
        return None, f"文件解析失败：{exc}"
    if frame is None or frame.empty:
        return None, "请先上传数据文件，或在左侧勾选「使用示例数据」。"
    return frame, ""


def _looks_like_header(frame: pd.DataFrame) -> bool:
    """判断输入是否带表头；内置示例文件均带表头。"""
    if frame.empty or frame.shape[1] < 2:
        return False
    probe = frame.iloc[:, 1]
    return pd.to_numeric(probe, errors="coerce").isna().all()


def _normalise_feature(frame: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    if frame.shape[1] < 3:
        return None, f"缺少必需列：name/start/end。当前列：{', '.join(map(str, frame.columns))}"
    body = frame
    if _looks_like_header(frame):
        body = frame.iloc[1:, :]
    work = pd.DataFrame(
        {
            "name": body.iloc[:, 0].astype(str).str.strip(),
            "start": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
            "end": pd.to_numeric(body.iloc[:, 2], errors="coerce"),
        }
    ).dropna(subset=["start", "end"])
    work = work[work["name"] != ""]
    if work.empty:
        return None, "Gene Structure 没有有效的 start / end 数值。"
    low = work[["start", "end"]].min(axis=1)
    high = work[["start", "end"]].max(axis=1)
    work["start"] = low
    work["end"] = high
    return work.reset_index(drop=True), ""


def _normalise_snp(frame: pd.DataFrame, label: str) -> tuple[pd.DataFrame | None, str]:
    if frame.shape[1] < 2:
        return None, f"{label} 缺少必需列：name/position。当前列：{', '.join(map(str, frame.columns))}"
    body = frame
    if _looks_like_header(frame):
        body = frame.iloc[1:, :]
    work = pd.DataFrame(
        {
            "name": body.iloc[:, 0].astype(str).str.strip(),
            "position": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
        }
    )
    if body.shape[1] >= 3:
        work["score"] = pd.to_numeric(body.iloc[:, 2], errors="coerce").to_numpy()
    else:
        work["score"] = 1.0
    work["score"] = pd.to_numeric(work["score"], errors="coerce").fillna(1.0)
    work = work.dropna(subset=["position"])
    work = work[work["name"] != ""]
    if work.empty:
        return None, f"{label} 没有有效的 position 数值。"
    return work.reset_index(drop=True), ""


def _stem_segments(positions: list[float], bases: list[float], tops: list[float]):
    """``(x, y)`` lists with ``None`` breaks so all stems live in one trace."""
    xs: list[float | None] = []
    ys: list[float | None] = []
    for x, base, top in zip(positions, bases, tops):
        xs.extend([x, x, None])
        ys.extend([base, top, None])
    return xs, ys


def _load_all() -> tuple[dict[str, pd.DataFrame], str]:
    if st.session_state.get("genvar_use_sample", True):
        tables: dict[str, pd.DataFrame] = {}
        for role, key in (
            ("feature", "genvar_feature"),
            ("upper", "genvar_snp_upper"),
            ("lower", "genvar_snp_lower"),
        ):
            frame, error = _read_any(None, key)
            if frame is None:
                return {}, error
            tables[role] = frame
        return tables, ""

    tables = {}
    for role, key in (
        ("feature", "genvar_feature_upload"),
        ("upper", "genvar_up_upload"),
        ("lower", "genvar_low_upload"),
    ):
        frame, error = _read_any(st.session_state.get(key), None)
        if frame is None:
            return {}, error
        tables[role] = frame
    return tables, ""


def _compute_bounds(feature: pd.DataFrame, upper: pd.DataFrame, lower: pd.DataFrame) -> tuple[float, float]:
    positions: list[float] = []
    for frame in (feature, upper, lower):
        if frame is None or frame.empty:
            continue
        for column in ("start", "end", "position"):
            if column in frame.columns:
                positions.extend(frame[column].dropna().astype(float).tolist())
    if not positions:
        return 0.0, 1000.0
    low, high = float(np.min(positions)), float(np.max(positions))
    if np.isclose(low, high):
        high = low + 1.0
    return low, high


def _parsed_tables() -> tuple[dict[str, pd.DataFrame], str]:
    tables, error = _load_all()
    if not tables:
        return {}, error
    feature, feature_error = _normalise_feature(tables["feature"])
    if feature is None:
        return {}, feature_error
    upper, upper_error = _normalise_snp(tables["upper"], "Upper SNP")
    if upper is None:
        return {}, upper_error
    lower = pd.DataFrame(columns=["name", "position", "score"])
    if st.session_state.get("genvar_mode", MODE_LOLLIPOP) == MODE_LOLLIPOP:
        parsed_lower, lower_error = _normalise_snp(tables["lower"], "Lower SNP")
        if parsed_lower is None:
            return {}, lower_error
        lower = parsed_lower
    return {"feature": feature, "upper": upper, "lower": lower}, ""


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
def controls(shared: dict) -> None:
    st.markdown("### 模式")
    st.radio("图形模式", [MODE_LOLLIPOP, MODE_DANDELION], index=0, key="genvar_mode")

    st.markdown("### 数据")
    sample_loader_control(
        "genvar_use_sample",
        ["genvar_feature", "genvar_snp_upper", "genvar_snp_lower"],
        "genvar_load_sample_btn",
    )
    if not st.session_state.get("genvar_use_sample", True):
        st.file_uploader(
            "Gene Structure（name, start, end）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="genvar_feature_upload",
        )
        st.file_uploader(
            "Upper SNP（name, position, score）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="genvar_up_upload",
        )
        st.file_uploader(
            "Lower SNP（name, position, score）",
            type=["csv", "tsv", "txt", "xlsx"],
            key="genvar_low_upload",
        )

    st.markdown("### 显示区间")
    parsed, _ = _parsed_tables()
    if parsed:
        bounds = _compute_bounds(parsed["feature"], parsed["upper"], parsed["lower"])
    else:
        bounds = (0.0, 1000.0)
    st.session_state["_genvar_bounds"] = bounds
    st.session_state.setdefault("genvar_range_start", float(bounds[0]))
    st.session_state.setdefault("genvar_range_end", float(bounds[1]))

    st.number_input("区间起点 (start)", step=10.0, key="genvar_range_start")
    st.number_input("区间终点 (end)", step=10.0, key="genvar_range_end")
    if st.button("恢复全区间", key="genvar_reset_range_btn", width="stretch"):
        st.session_state["genvar_range_start"] = float(bounds[0])
        st.session_state["genvar_range_end"] = float(bounds[1])
    if float(st.session_state.get("genvar_range_start", bounds[0])) >= float(
        st.session_state.get("genvar_range_end", bounds[1])
    ):
        st.warning("区间起点必须小于终点，否则将回退为全区间。")

    st.markdown("### 标题")
    st.checkbox("添加图形标题（默认关闭）", value=False, key="genvar_add_title")
    if st.session_state.get("genvar_add_title", False):
        st.text_input("图形标题", "Genomic Variation", key="genvar_title")


def advanced_controls(shared: dict) -> None:
    """Genomic Variation 的高级参数：基因结构、SNP、逐项覆盖与标签。"""
    st.markdown("### 基因结构")
    if st.session_state.get("genvar_feature_palette_mode") not in FEATURE_PALETTE_MODES:
        st.session_state["genvar_feature_palette_mode"] = "多色"
    st.slider("Gene block 高度", 0.02, 0.15, 0.04, 0.01, key="genvar_block_height")
    st.radio(
        "Gene block 配色",
        list(FEATURE_PALETTE_MODES),
        index=0,
        key="genvar_feature_palette_mode",
        horizontal=True,
    )
    if st.session_state.get("genvar_feature_palette_mode", "多色") == "单色":
        st.color_picker("Gene block 颜色", value=_theme_color("genvar_feature"), key="genvar_feature_color")

    st.markdown("### SNP")
    st.radio(
        "标记形状",
        options=list(MARKER_SHAPES.keys()),
        format_func=lambda value: MARKER_SHAPES[value],
        index=0,
        key="genvar_marker_shape",
        horizontal=True,
    )
    st.radio("大小模式", list(SIZE_MODES), index=0, key="genvar_snp_size_mode", horizontal=True)
    if st.session_state.get("genvar_snp_size_mode", "统一") != "自定义":
        st.slider("统一大小", 0.5, 2.0, 1.0, 0.1, key="genvar_snp_size")
    st.radio("配色模式", list(PALETTE_MODES), index=0, key="genvar_snp_palette_mode", horizontal=True)
    if st.session_state.get("genvar_snp_palette_mode", "随机") == "单色":
        st.color_picker("单色 SNP 颜色", value=_theme_color("genvar_snp"), key="genvar_snp_color")
    else:
        st.number_input("随机种子", min_value=0, max_value=2147483647, value=0, step=1, key="genvar_palette_seed", help="相同数据和种子会生成相同 SNP 配色，并随项目包保存。")
        if st.button("刷新随机配色", key="genvar_refresh_palette", width="stretch"):
            st.session_state["genvar_palette_seed"] = int(st.session_state.get("genvar_palette_seed", 0)) + 1

    st.markdown("### 逐项覆盖（label / size / color）")
    if "genvar_override_table" not in st.session_state:
        st.session_state["genvar_override_table"] = pd.DataFrame(
            {"label": pd.Series(dtype="str"), "size": pd.Series(dtype="float"), "color": pd.Series(dtype="str")}
        )
    st.data_editor(
        st.session_state["genvar_override_table"],
        key="genvar_override_editor_state",
        num_rows="dynamic",
        width="stretch",
        column_config={
            "label": st.column_config.TextColumn("label"),
            "size": st.column_config.NumberColumn("size", min_value=0.2, max_value=4.0, step=0.1),
            "color": st.column_config.TextColumn("color", help="#RRGGBB"),
        },
    )

    st.markdown("### 标签与坐标轴")
    st.checkbox("显示 gene block 名称", value=False, key="genvar_show_feature_label")
    st.checkbox("显示 SNP 标签", value=False, key="genvar_show_label")
    if st.session_state.get("genvar_show_label", False):
        st.slider("标签字号", 6, 16, 9, 1, key="genvar_label_size")
    st.checkbox("显示 X 轴", value=True, key="genvar_show_xaxis")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def _override_map(table) -> tuple[dict[str, float], dict[str, str]]:
    """Parse the per-label override table into (size map, colour map)."""
    sizes: dict[str, float] = {}
    colors: dict[str, str] = {}
    if not isinstance(table, pd.DataFrame) or table.empty:
        return sizes, colors
    for _, row in table.iterrows():
        label = str(row.get("label", "") or "").strip()
        if not label:
            continue
        size_value = pd.to_numeric(row.get("size"), errors="coerce")
        if pd.notna(size_value):
            sizes[label] = float(size_value)
        color_value = str(row.get("color", "") or "").strip()
        if color_value.startswith("#") and len(color_value) in (4, 7):
            colors[label] = color_value
    return sizes, colors


def build(shared: dict):
    theme = _theme()
    tables, error = _load_all()
    if not tables:
        return None, None, error, HELP_TEXT

    feature, feature_error = _normalise_feature(tables["feature"])
    if feature is None:
        return None, None, feature_error, HELP_TEXT
    upper, upper_error = _normalise_snp(tables["upper"], "Upper SNP")
    if upper is None:
        return None, None, upper_error, HELP_TEXT

    mode = st.session_state.get("genvar_mode", MODE_LOLLIPOP)
    lower = pd.DataFrame(columns=["name", "position", "score"])
    if mode == MODE_LOLLIPOP:
        lower, lower_error = _normalise_snp(tables["lower"], "Lower SNP")
        if lower is None:
            return None, None, lower_error, HELP_TEXT

    # ---- range filter -----------------------------------------------------
    full_start, full_end = _compute_bounds(feature, upper, lower)
    st.session_state["_genvar_bounds"] = (full_start, full_end)
    range_start = float(st.session_state.get("genvar_range_start", full_start))
    range_end = float(st.session_state.get("genvar_range_end", full_end))
    if range_start >= range_end:
        range_start, range_end = full_start, full_end
    range_start = max(range_start, full_start)
    range_end = min(range_end, full_end)
    if range_start >= range_end:
        range_start, range_end = full_start, full_end

    feature_view = feature[(feature["end"] >= range_start) & (feature["start"] <= range_end)].copy()
    upper_view = upper[(upper["position"] >= range_start) & (upper["position"] <= range_end)].copy()
    lower_view = (
        lower[(lower["position"] >= range_start) & (lower["position"] <= range_end)].copy()
        if not lower.empty
        else lower.copy()
    )
    if feature_view.empty and upper_view.empty and lower_view.empty:
        return None, None, "当前筛选无数据可绘制。", HELP_TEXT

    # ---- styling ---------------------------------------------------------
    view_span = max(range_end - range_start, 1e-9)
    block_height = float(st.session_state.get("genvar_block_height", 0.04))
    feature_palette_mode = st.session_state.get("genvar_feature_palette_mode", "多色")
    feature_color = st.session_state.get("genvar_feature_color") or _theme_color("genvar_feature")
    feature_colors = (
        _feature_colors(len(feature_view))
        if feature_palette_mode == "多色"
        else [feature_color] * len(feature_view)
    )
    # 基因块是深色填充，标签必须用浅色，否则深字压深块看不见
    label_color = _theme_color("genvar_label")
    shape_key = st.session_state.get("genvar_marker_shape", "circle")
    if shape_key == "flag":
        # Plotly has no "flag" symbol → triangle head on the same stem.
        marker_symbol = "triangle-up"
    else:
        marker_symbol = shape_key if shape_key in _VALID_MARKERS else "circle"
    size_mode = st.session_state.get("genvar_snp_size_mode", "统一")
    base_size = float(st.session_state.get("genvar_snp_size", 1.0))
    palette_mode = st.session_state.get("genvar_snp_palette_mode", "随机")
    single_color = st.session_state.get("genvar_snp_color") or _theme_color("genvar_snp")
    show_feature_label = bool(st.session_state.get("genvar_show_feature_label", False))
    show_label = bool(st.session_state.get("genvar_show_label", False))
    label_size = int(st.session_state.get("genvar_label_size", 9))
    show_xaxis = bool(st.session_state.get("genvar_show_xaxis", True))
    add_title = bool(st.session_state.get("genvar_add_title", False))
    title_text = (st.session_state.get("genvar_title") or "Genomic Variation") if add_title else ""
    text_color = theme.get("text", "#111827")

    override_sizes, override_colors = _override_map(st.session_state.get("genvar_override_table"))
    palette_seed = int(st.session_state.get("genvar_palette_seed", 0))
    random_upper = _random_colors(len(upper_view), palette_seed)
    random_lower = _random_colors(len(lower_view), palette_seed + 1)

    def _size_of(label: str, seed_index: int) -> float:
        if label in override_sizes:
            return override_sizes[label]
        if size_mode == "随机":
            rng = np.random.default_rng(abs(hash((label, seed_index))) % (2**32))
            return float(rng.uniform(0.6, 2.0))
        return base_size

    def _color_of(label: str, track: str, index: int) -> str:
        if label in override_colors:
            return override_colors[label]
        if palette_mode == "随机":
            palette = random_upper if track == "upper" else random_lower
            return palette[index] if index < len(palette) else single_color
        # 单色模式下，上下两层棒棒糖复用同一个颜色。
        return single_color

    def _marker_size(scale: float) -> float:
        return 6.0 + 10.0 * float(scale)

    fig = go.Figure()

    # ---- gene structure blocks -------------------------------------------
    half_height = block_height / 2.0
    y_low = GENE_BAND_CENTRE - half_height
    y_high = GENE_BAND_CENTRE + half_height
    for index, row in feature_view.reset_index(drop=True).iterrows():
        start = float(row["start"])
        end = float(row["end"])
        width = max(end - start, 1e-9)
        head = min(width * 0.2, max(view_span * 0.012, 1.0))
        path = (
            f"M {start:.9g},{y_low:.9g} "
            f"L {end - head:.9g},{y_low:.9g} "
            f"L {end:.9g},{GENE_BAND_CENTRE:.9g} "
            f"L {end - head:.9g},{y_high:.9g} "
            f"L {start:.9g},{y_high:.9g} Z"
        )
        fig.add_shape(
            type="path",
            path=path,
            xref="x",
            yref="y",
            line=dict(color="rgba(17, 24, 39, 0.45)", width=0.8),
            fillcolor=feature_colors[index] if index < len(feature_colors) else feature_color,
            layer="below",
        )
    if show_feature_label and not feature_view.empty:
        fig.add_trace(
            go.Scatter(
                x=((feature_view["start"] + feature_view["end"]) / 2.0).tolist(),
                y=[GENE_BAND_CENTRE] * len(feature_view),
                mode="text",
                text=feature_view["name"].astype(str).tolist(),
                textfont=dict(size=9, color="#FFFFFF" if feature_palette_mode == "多色" else label_color),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    def _draw_track(
        subset: pd.DataFrame,
        base: float,
        top_of: float,
        track: str,
        name: str,
        text_position: str,
    ) -> None:
        if subset.empty:
            return
        positions = subset["position"].astype(float).tolist()
        tops = [top_of(value) for value in subset["score"].astype(float)]
        colors = [_color_of(str(label), track, index) for index, label in enumerate(subset["name"])]

        stem_x, stem_y = _stem_segments(positions, [base] * len(tops), tops)
        stem_color = colors[0] if len(set(colors)) == 1 else SNP_BORDER_COLOR
        fig.add_trace(
            go.Scatter(
                x=stem_x,
                y=stem_y,
                mode="lines",
                line=dict(color=stem_color, width=1.2),
                name=f"{name} stem",
                showlegend=False,
                hoverinfo="skip",
            )
        )
        marker_sizes = [
            _marker_size(_size_of(str(label), index))
            for index, label in enumerate(subset["name"])
        ]
        fig.add_trace(
            go.Scatter(
                x=positions,
                y=tops,
                mode="markers+text" if show_label else "markers",
                marker=dict(
                    symbol=marker_symbol,
                    size=marker_sizes,
                    color=colors,
                    line=dict(color=SNP_BORDER_COLOR, width=0.8),
                    opacity=0.9,
                ),
                text=subset["name"].astype(str).tolist() if show_label else None,
                textposition=text_position,
                textfont=dict(size=label_size, color=text_color),
                name=name,
                customdata=[[str(label), f"{float(score):g}"] for label, score in zip(subset["name"], subset["score"])],
                hovertemplate="%{customdata[0]}<br>position: %{x}<br>score: %{customdata[1]}<extra></extra>",
            )
        )
        if shape_key == "pin":
            fig.add_trace(
                go.Scatter(
                    x=positions,
                    y=tops,
                    mode="markers",
                    marker=dict(
                        symbol="circle",
                        size=[max(2.2, value * 0.38) for value in marker_sizes],
                        color="#FFFFFF",
                        line=dict(width=0),
                    ),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

    upper_span = float(np.abs(upper_view["score"]).max()) if not upper_view.empty else 1.0
    upper_span = upper_span or 1.0

    if mode == MODE_DANDELION:
        # Dandelion 模式：所有 SNP 使用统一的中心高度与圆点样式。
        def _dandelion_top(score: float) -> float:
            return GENE_BAND_CENTRE + 0.45

        _draw_track(upper_view, LOWER_BASE, _dandelion_top, "upper", "SNP", "top center")
    else:
        def _upper_top(score: float) -> float:
            return UPPER_BASE + (UPPER_TOP - UPPER_BASE) * (0.2 + 0.8 * abs(score) / upper_span)

        lower_span = float(np.abs(lower_view["score"]).max()) if not lower_view.empty else 1.0
        lower_span = lower_span or 1.0

        def _lower_top(score: float) -> float:
            # The lower track grows *downwards* from LOWER_BASE to LOWER_BOTTOM.
            return LOWER_BASE - (LOWER_BASE - LOWER_BOTTOM) * (0.2 + 0.8 * abs(score) / lower_span)

        _draw_track(upper_view, UPPER_BASE, _upper_top, "upper", "Upper SNP", "top center")
        _draw_track(lower_view, LOWER_BASE, _lower_top, "lower", "Lower SNP", "bottom center")

    # ---- layout ----------------------------------------------------------
    span = view_span
    tick_values = _smart_xlabels(range_start, range_end) if show_xaxis else None
    fig.update_layout(
        height=480,
        plot_bgcolor=theme.get("bg", "#f5f7fb"),
        paper_bgcolor=theme.get("bg", "#f5f7fb"),
        margin=dict(l=50, r=30, t=60 if title_text else 30, b=60 if show_xaxis else 20),
        font=dict(color=text_color),
        showlegend=False,
        hovermode="closest",
    )
    if title_text:
        fig.update_layout(title=dict(text=title_text, font=dict(size=17, color=text_color)))
    fig.update_xaxes(
        title_text="Genomic position" if show_xaxis else "",
        range=[range_start - span * 0.02, range_end + span * 0.02],
        visible=show_xaxis,
        showgrid=False,
        zeroline=False,
        showline=show_xaxis,
        linecolor=text_color,
        tickmode="array" if tick_values else "auto",
        tickvals=tick_values,
        ticktext=[f"{value:g}" for value in tick_values] if tick_values else None,
        ticks="outside" if show_xaxis else "",
    )
    # fixed Y domain so a missing track never rescales the others
    fig.update_yaxes(range=[0.0, 1.0], visible=False, showgrid=False, zeroline=False)
    fig.add_shape(
        type="line",
        x0=range_start,
        x1=range_end,
        y0=GENE_BAND_CENTRE,
        y1=GENE_BAND_CENTRE,
        line=dict(color=text_color, width=0.8, dash="dot"),
        layer="below",
    )

    data = {
        "Gene Structure": feature_view[["name", "start", "end"]].reset_index(drop=True),
        "Upper SNP": upper_view.reset_index(drop=True),
        "Lower SNP": lower_view.reset_index(drop=True),
    }
    shared["last_plotly"] = fig
    shared["data"] = data
    status = (
        f"Genomic Variation 就绪：{len(feature_view)} 个基因块；上轨 {len(upper_view)} 个 SNP"
        + (f"；下轨 {len(lower_view)} 个 SNP" if mode == MODE_LOLLIPOP else "；单层发散")
        + f"；显示区间 {range_start:g}–{range_end:g}"
    )
    shared["status"] = status
    shared["help_text"] = HELP_TEXT
    return fig, data, status, HELP_TEXT


def render(shared: dict):
    controls(shared)
    return build(shared)


__call__ = render
