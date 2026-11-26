from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import plotly.graph_objects as go


FOLLOW = "跟随模块"
FONT_FAMILIES = {
    FOLLOW: None,
    "Arial": "Arial, Helvetica, sans-serif",
    "Helvetica": "Helvetica, Arial, sans-serif",
    "Times New Roman": '"Times New Roman", Times, serif',
    "微软雅黑": '"Microsoft YaHei", "PingFang SC", sans-serif',
}
LEGEND_POSITIONS = [FOLLOW, "右侧", "顶部", "底部", "隐藏"]
GRID_MODES = [FOLLOW, "显示", "隐藏"]

FIGURE_STYLE_DEFAULTS = {
    "fs_font_family": FOLLOW,
    "fs_font_scale": 1.0,
    "fs_title_size": 0,
    "fs_axis_title_size": 0,
    "fs_tick_size": 0,
    "fs_legend_size": 0,
    "fs_legend_position": FOLLOW,
    "fs_grid_mode": FOLLOW,
    "fs_title_override": False,
    "fs_export_name": "",
}

FIGURE_STYLE_KEYS = tuple(FIGURE_STYLE_DEFAULTS)
PLOT_STYLE_KEYS = tuple(key for key in FIGURE_STYLE_KEYS if key != "fs_export_name")


def _state_get(session_state: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return session_state.get(key, default)
    except (AttributeError, KeyError):
        try:
            return session_state[key]
        except (KeyError, TypeError):
            return default


def init_figure_style_defaults(session_state: Mapping[str, Any]) -> None:
    for key, value in FIGURE_STYLE_DEFAULTS.items():
        if _state_get(session_state, key, None) is None:
            session_state[key] = value


def reset_figure_style(session_state: Mapping[str, Any]) -> None:
    for key, value in FIGURE_STYLE_DEFAULTS.items():
        session_state[key] = value


def _number(session_state: Mapping[str, Any], key: str, default: float) -> float:
    try:
        return float(_state_get(session_state, key, default))
    except (TypeError, ValueError):
        return default


def figure_style_manifest(session_state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "font_family": str(_state_get(session_state, "fs_font_family", FOLLOW)),
        "font_scale": round(_number(session_state, "fs_font_scale", 1.0), 3),
        "title_size": int(_number(session_state, "fs_title_size", 0)),
        "axis_title_size": int(_number(session_state, "fs_axis_title_size", 0)),
        "tick_size": int(_number(session_state, "fs_tick_size", 0)),
        "legend_size": int(_number(session_state, "fs_legend_size", 0)),
        "legend_position": str(_state_get(session_state, "fs_legend_position", FOLLOW)),
        "grid_mode": str(_state_get(session_state, "fs_grid_mode", FOLLOW)),
        "title_override": bool(_state_get(session_state, "fs_title_override", False)),
        "export_name": str(_state_get(session_state, "fs_export_name", ""))[:160],
    }


def restore_figure_style(
    payload: Mapping[str, Any] | None,
    session_state: Mapping[str, Any],
) -> None:
    reset_figure_style(session_state)
    if not isinstance(payload, Mapping):
        return

    font_family = payload.get("font_family", FOLLOW)
    if font_family in FONT_FAMILIES:
        session_state["fs_font_family"] = font_family

    scale = payload.get("font_scale", 1.0)
    try:
        session_state["fs_font_scale"] = min(1.6, max(0.6, round(float(scale), 2)))
    except (TypeError, ValueError):
        pass

    for style_key in ("title_size", "axis_title_size", "tick_size", "legend_size"):
        value = payload.get(style_key, 0)
        try:
            session_state[f"fs_{style_key}"] = min(48, max(0, int(value)))
        except (TypeError, ValueError):
            continue

    legend_position = payload.get("legend_position", FOLLOW)
    if legend_position in LEGEND_POSITIONS:
        session_state["fs_legend_position"] = legend_position

    grid_mode = payload.get("grid_mode", FOLLOW)
    if grid_mode in GRID_MODES:
        session_state["fs_grid_mode"] = grid_mode

    session_state["fs_title_override"] = bool(payload.get("title_override", False))
    session_state["fs_export_name"] = str(payload.get("export_name", ""))[:160]


def is_figure_style_customized(session_state: Mapping[str, Any]) -> bool:
    for key in PLOT_STYLE_KEYS:
        if _state_get(session_state, key, FIGURE_STYLE_DEFAULTS[key]) != FIGURE_STYLE_DEFAULTS[key]:
            return True
    return False


def style_source_label(session_state: Mapping[str, Any]) -> str:
    customized = is_figure_style_customized(session_state)
    if customized:
        return "自定义通用外观"
    return "网站默认"


def plot_style_signature(session_state: Mapping[str, Any]) -> str:
    payload = figure_style_manifest(session_state)
    payload.pop("export_name", None)
    if payload.get("title_override"):
        payload["figure_title"] = str(_state_get(session_state, "figure_title", ""))
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return raw


def normalized_export_stem(session_state: Mapping[str, Any], plot_name: str) -> str:
    title = (
        _state_get(session_state, "fs_export_name")
        or _state_get(session_state, "figure_title")
        or plot_name
    )
    title = str(title).strip()
    title = re.sub(r"\.(?:png|svg|pdf|html|json|zip)$", "", title, flags=re.IGNORECASE)
    title = re.sub(r'[\\/:*?"<>|]+', "_", title)
    return title or plot_name


def _scaled_size(value: Any, scale: float) -> int | None:
    if value is None:
        return None
    try:
        size = float(value) * scale
    except (TypeError, ValueError):
        return None
    return max(1, int(round(size)))


def _axis_names(fig: go.Figure):
    for name in fig.layout:
        if name.startswith("xaxis") or name.startswith("yaxis"):
            axis = getattr(fig.layout, name, None)
            if axis is not None:
                yield axis


def apply_figure_style(fig: go.Figure, session_state: Mapping[str, Any]) -> go.Figure:
    """Apply shared appearance settings without touching plotted data."""
    family = FONT_FAMILIES.get(str(_state_get(session_state, "fs_font_family", FOLLOW)))
    scale = min(1.6, max(0.6, _number(session_state, "fs_font_scale", 1.0)))
    title_size = max(0, int(_number(session_state, "fs_title_size", 0)))
    axis_title_size = max(0, int(_number(session_state, "fs_axis_title_size", 0)))
    tick_size = max(0, int(_number(session_state, "fs_tick_size", 0)))
    legend_size = max(0, int(_number(session_state, "fs_legend_size", 0)))

    if _state_get(session_state, "fs_title_override", False):
        title = str(_state_get(session_state, "figure_title", "") or "").strip()
        fig.update_layout(title=dict(text=title or None))

    if family:
        fig.update_layout(font=dict(family=family))
        fig.layout.title.font.update(family=family)
        fig.layout.legend.font.update(family=family)
        for axis in _axis_names(fig):
            axis.title.font.update(family=family)
            axis.tickfont.update(family=family)
        for annotation in fig.layout.annotations or ():
            annotation.font.update(family=family)
        fig.layout.hoverlabel.font.update(family=family)

    if scale != 1.0:
        global_size = _scaled_size(fig.layout.font.size, scale) or _scaled_size(12, scale)
        fig.update_layout(font=dict(size=global_size))
        fig.layout.title.font.update(size=_scaled_size(fig.layout.title.font.size, scale))
        fig.layout.legend.font.update(size=_scaled_size(fig.layout.legend.font.size, scale))
        for axis in _axis_names(fig):
            axis.title.font.update(size=_scaled_size(axis.title.font.size, scale))
            axis.tickfont.update(size=_scaled_size(axis.tickfont.size, scale))
        for annotation in fig.layout.annotations or ():
            annotation.font.update(size=_scaled_size(annotation.font.size, scale))

    if title_size:
        fig.layout.title.font.update(size=title_size)
    if axis_title_size:
        for axis in _axis_names(fig):
            axis.title.font.update(size=axis_title_size)
    if tick_size:
        for axis in _axis_names(fig):
            axis.tickfont.update(size=tick_size)
    if legend_size:
        fig.layout.legend.font.update(size=legend_size)

    legend_position = _state_get(session_state, "fs_legend_position", FOLLOW)
    if legend_position == "右侧":
        fig.update_layout(
            legend=dict(orientation="v", x=1.02, xanchor="left", y=1.0, yanchor="top")
        )
    elif legend_position == "顶部":
        fig.update_layout(
            legend=dict(orientation="h", x=0.5, xanchor="center", y=1.02, yanchor="bottom")
        )
    elif legend_position == "底部":
        fig.update_layout(
            legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.18, yanchor="top")
        )
    elif legend_position == "隐藏":
        fig.update_layout(showlegend=False)

    grid_mode = _state_get(session_state, "fs_grid_mode", FOLLOW)
    if grid_mode in {"显示", "隐藏"}:
        show_grid = grid_mode == "显示"
        fig.update_xaxes(showgrid=show_grid)
        fig.update_yaxes(showgrid=show_grid)

    return fig
