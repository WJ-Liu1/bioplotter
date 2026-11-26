from __future__ import annotations

import math
import re
import unicodedata

import plotly.graph_objects as go


_TAGS = re.compile(r"<[^>]+>")


def _display_width(text: object) -> float:
    plain = _TAGS.sub("", str(text)).replace("&nbsp;", " ")
    return sum(1.0 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 0.58 for char in plain)


def _longest_label(labels, axis, rotated: bool) -> float:
    widths = []
    for label in labels:
        for line in str(label).split("<br>"):
            widths.append(_display_width(line))
    if not widths:
        return 0.0
    size = float(getattr(axis.tickfont, "size", None) or 12.0)
    longest = max(widths)
    angle = abs(float(getattr(axis, "tickangle", 0) or 0)) % 180
    if angle > 90:
        angle = 180 - angle
    if rotated:
        return longest * size * math.sin(math.radians(angle))
    return longest * size * math.cos(math.radians(angle))


def _axis_suffix(axis_name: str) -> str:
    suffix = axis_name[5:]
    return "" if suffix in {"", "1"} else suffix


def _trace_axis_suffix(trace, axis_key: str) -> str:
    value = getattr(trace, f"{axis_key}axis", None) or axis_key
    if value == axis_key:
        return ""
    return str(value)[len(axis_key):]


def _inferred_category_labels(fig: go.Figure, axis_name: str) -> list[str]:
    """Read category labels from trace data when the layout has no ticktext."""
    axis_key = "x" if axis_name.startswith("xaxis") else "y"
    target_suffix = _axis_suffix(axis_name)
    labels: list[str] = []
    seen: set[str] = set()
    for trace in fig.data:
        if _trace_axis_suffix(trace, axis_key) != target_suffix:
            continue
        values = getattr(trace, axis_key, None)
        if values is None:
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            text = value.strip()
            if text and text not in seen:
                seen.add(text)
                labels.append(text)
    return labels


def prevent_label_clipping(fig: go.Figure, *, max_extra_margin: int = 220) -> go.Figure:
    """Reserve enough room for tick labels, annotations and legends in-place."""
    margin = fig.layout.margin
    left = float(margin.l if margin.l is not None else 60)
    right = float(margin.r if margin.r is not None else 40)
    bottom = float(margin.b if margin.b is not None else 50)
    top = float(margin.t if margin.t is not None else 60)
    base = {"l": left, "r": right, "b": bottom, "t": top}

    for axis_name in fig.layout:
        if not (axis_name.startswith("xaxis") or axis_name.startswith("yaxis")):
            continue
        axis = getattr(fig.layout, axis_name)
        if axis.visible is False:
            continue
        ticktext = axis.ticktext
        labels = list(ticktext) if ticktext is not None and len(ticktext) else []
        if not labels:
            tickvals = axis.tickvals
            labels = list(tickvals) if tickvals is not None and len(tickvals) else []
        if not labels:
            labels = _inferred_category_labels(fig, axis_name)
        is_x = axis_name.startswith("xaxis")
        angle = abs(float(getattr(axis, "tickangle", 0) or 0)) % 180
        rotated = is_x and angle not in {0.0, 180.0}
        needed = _longest_label(labels, axis, rotated)
        if not needed:
            continue
        if is_x:
            target = needed + (float(getattr(axis.tickfont, "size", None) or 12) + 22 if rotated else 0)
            if target > bottom:
                bottom = min(target, base["b"] + max_extra_margin)
            overhang = needed / 2 + 18
            if overhang > left:
                left = min(overhang, base["l"] + max_extra_margin)
            if overhang > right:
                right = min(overhang, base["r"] + max_extra_margin)
        else:
            target = needed + 24
            if target > left:
                left = min(target, base["l"] + max_extra_margin)

    for annotation in fig.layout.annotations or ():
        if annotation.showarrow or not annotation.text:
            continue
        if annotation.xref in {"paper", "x domain", "y domain"} or annotation.yref in {"paper", "x domain", "y domain"}:
            continue
        size = float(getattr(annotation.font, "size", None) or 12.0)
        length = max((_display_width(line) for line in str(annotation.text).split("<br>")), default=0.0) * size
        angle = abs(float(annotation.textangle or 0)) % 180
        if angle > 90:
            angle = 180 - angle
        horizontal = length * abs(math.cos(math.radians(angle)))
        vertical = length * abs(math.sin(math.radians(angle))) + size
        xref = str(annotation.xref)
        yref = str(annotation.yref)
        axis = getattr(fig.layout, "yaxis" + ("1" if xref == "x" else xref[1:]), None) if xref.startswith("x") else None
        if xref.startswith("x") and axis is not None and axis.range is not None and annotation.x is not None:
            lo, hi = map(float, axis.range)
            span = max(hi - lo, 1e-12)
            distance = (float(annotation.x) - lo) / span if annotation.xanchor == "right" else (hi - float(annotation.x)) / span
            needed = horizontal * max(0.0, 1.0 - distance) + 16
            if needed > right:
                right = min(needed, base["r"] + max_extra_margin)
        if yref.startswith("y") and annotation.y is not None:
            suffix = "1" if yref == "y" else yref[1:]
            axis = getattr(fig.layout, "yaxis" + suffix, None)
            if axis is not None and axis.range is not None:
                lo, hi = map(float, axis.range)
                span = max(hi - lo, 1e-12)
                if annotation.yanchor == "top":
                    needed = vertical * max(0.0, (float(annotation.y) - lo) / span) + 12
                    if needed > bottom:
                        bottom = min(needed, base["b"] + max_extra_margin)

    legend = fig.layout.legend
    legend_font_size = float(getattr(legend.font, "size", None) or 12.0) if legend is not None else 12.0
    if legend is not None and (legend.x if legend.x is not None else 1.02) >= 1.0:
        trace_labels = [
            str(getattr(trace, "name", ""))
            for trace in fig.data
            if getattr(trace, "showlegend", False)
        ]
        longest = max((_display_width(label) for label in trace_labels), default=0.0)
        needed = longest * legend_font_size + 65
        if needed > right:
            right = min(needed, base["r"] + max_extra_margin)
    if legend is not None and str(legend.orientation or "v") == "h":
        legend_y = float(legend.y if legend.y is not None else 1.02)
        if legend_y >= 1.0:
            needed = legend_font_size * 1.8 + 16
            if needed > top - base["t"]:
                top = min(base["t"] + needed, base["t"] + max_extra_margin)
        elif legend_y < 0:
            needed = legend_font_size * 1.8 + 24
            if needed > bottom - base["b"]:
                bottom = min(base["b"] + needed, base["b"] + max_extra_margin)

    fig.update_layout(margin=dict(l=round(left), r=round(right), t=round(top), b=round(bottom)))
    return fig
