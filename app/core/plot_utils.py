from __future__ import annotations

import io
from typing import Literal

import matplotlib.pyplot as plt


def fig_to_bytes(
    fig: plt.Figure,
    fmt: Literal["png", "svg", "pdf"] = "png",
    width_mm: float | None = None,
    dpi: int = 300,
) -> bytes:
    """把 Matplotlib 图导出为字节。

    给定 ``width_mm`` 时按该物理宽度等比重设画布（高按原图宽高比），
    并且不再用 ``bbox_inches="tight"``——否则裁剪会把尺寸改掉，投稿时对不上期刊要求。
    """
    buf = io.BytesIO()

    if width_mm:
        old_size = fig.get_size_inches()
        aspect = (old_size[1] / old_size[0]) if old_size[0] else 0.62
        width_in = width_mm / 25.4
        fig.set_size_inches(width_in, width_in * aspect)
        try:
            fig.savefig(buf, format=fmt, dpi=dpi)
        finally:
            fig.set_size_inches(*old_size)
    else:
        fig.savefig(buf, format=fmt, bbox_inches="tight", dpi=dpi)

    buf.seek(0)
    return buf.getvalue()
