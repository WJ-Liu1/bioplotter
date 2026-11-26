from __future__ import annotations

import io
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image


TRANSPARENT_BACKGROUND = "rgba(0,0,0,0)"


def _prepare_figure(fig_json: str, transparent: bool) -> go.Figure:
    figure = pio.from_json(fig_json)
    if transparent:
        figure.update_layout(
            paper_bgcolor=TRANSPARENT_BACKGROUND,
            plot_bgcolor=TRANSPARENT_BACKGROUND,
        )
    return figure


def _write_png_dpi(payload: bytes, dpi: int | float | None) -> bytes:
    if dpi is None:
        return payload

    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        output = io.BytesIO()
        image.save(output, format="PNG", dpi=(float(dpi), float(dpi)))
        return output.getvalue()


def render_static_bytes(
    fig_json: str,
    fmt: str,
    width: int,
    height: int,
    scale: float,
    transparent: bool = False,
    dpi: int | float | None = None,
    **image_kwargs: Any,
) -> bytes:
    """Render a Plotly figure to static bytes with optional PNG DPI metadata."""
    normalized = fmt.lower().lstrip(".")
    figure = _prepare_figure(fig_json, transparent)
    payload = figure.to_image(
        format=normalized,
        width=int(width),
        height=int(height),
        scale=float(scale),
        **image_kwargs,
    )
    if normalized == "png":
        payload = _write_png_dpi(payload, dpi)
    return bytes(payload)


def render_html_bytes(figure: go.Figure, *, offline: bool) -> bytes:
    """Render a standalone Plotly HTML document with CDN or inlined Plotly JS."""
    html = pio.to_html(
        figure,
        include_plotlyjs="inline" if offline else "cdn",
        full_html=True,
    )
    return html.encode("utf-8")
