"""Acceptance tests for real PNG / SVG / PDF export products.

    .venv\\Scripts\\python.exe -X utf8 scripts\\apptest_export_products.py
"""

from __future__ import annotations

import io
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.export_static import render_static_bytes  # noqa: E402
from app.core.figure_style import apply_figure_style  # noqa: E402
from app.core.layout_guard import prevent_label_clipping  # noqa: E402


APP_FILE = str(PROJECT_ROOT / "app.py")
WIDTH_MM = 85.0
BASE_DPI = 96
MM_PER_INCH = 25.4
TITLE = "中文导出验收"
FONT_FAMILY = "微软雅黑"
FONT_CSS_FAMILY = "Microsoft YaHei"
PLOTS = (
    ("普通图", "Volcano Plot"),
    ("热图", "Heatmap"),
    ("网络图", "Node-link Diagram"),
)


def _css_size(fig: go.Figure) -> tuple[int, int]:
    width = max(50, int(round(WIDTH_MM / MM_PER_INCH * BASE_DPI)))
    fig_width = float(getattr(fig.layout, "width", None) or 960)
    fig_height = float(getattr(fig.layout, "height", None) or 560)
    height = max(50, int(round(width * fig_height / fig_width)))
    return width, height


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _style_state() -> dict:
    return {
        "fs_font_family": FONT_FAMILY,
        "fs_font_scale": 1.1,
        "fs_title_override": True,
        "figure_title": TITLE,
        "fs_legend_position": "顶部",
        "fs_grid_mode": "隐藏",
    }


def _open_styled_plot(name: str) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=240)
    at.session_state["page"] = "home"
    at.run()
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        if _state(at, "last_plotly") is not None:
            break
        at.run()
    for key, value in _style_state().items():
        at.session_state[key] = value
    at.button(key=f"generate_{name}").click().run()
    return at


def _svg_root(svg: str) -> str:
    match = re.search(r"<svg\b[^>]*>", svg)
    return match.group(0) if match else ""


def _svg_attr(root: str, name: str) -> float | None:
    match = re.search(rf'\b{re.escape(name)}="([^"]+)"', root)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _media_box(pdf: bytes) -> tuple[float, float, float, float] | None:
    match = re.search(rb"/MediaBox\s*\[\s*([^\]]+)\]", pdf)
    if not match:
        return None
    try:
        values = tuple(float(part) for part in match.group(1).split())
    except ValueError:
        return None
    return values if len(values) == 4 else None


def _border_clear(image: Image.Image, pixels: int = 2) -> bool:
    if image.mode != "RGBA":
        return False
    alpha = np.asarray(image.getchannel("A"))
    return bool(
        np.all(alpha[:pixels, :] == 0)
        and np.all(alpha[-pixels:, :] == 0)
        and np.all(alpha[:, :pixels] == 0)
        and np.all(alpha[:, -pixels:] == 0)
    )


def _check_png(
    checks: list[tuple[str, bool, str]],
    label: str,
    payload: bytes,
    css_w: int,
    css_h: int,
    dpi: int,
    transparent: bool,
) -> None:
    with Image.open(io.BytesIO(payload)) as image:
        expected = (round(css_w * dpi / BASE_DPI), round(css_h * dpi / BASE_DPI))
        actual = image.size
        actual_dpi = image.info.get("dpi")
        dpi_x = float(actual_dpi[0]) if actual_dpi else 0.0
        width_mm = actual[0] / float(dpi) * MM_PER_INCH if dpi else 0.0
        ok = (
            image.format == "PNG"
            and abs(actual[0] - expected[0]) <= 1
            and abs(actual[1] - expected[1]) <= 1
            and abs(dpi_x - dpi) <= 1
            and abs(width_mm - WIDTH_MM) <= 0.35
        )
        checks.append((
            f"{label} PNG {dpi} dpi 物理尺寸与元数据",
            ok,
            f"{actual} dpi={actual_dpi} width={width_mm:.2f}mm expected={expected}",
        ))

        if transparent:
            alpha = image.convert("RGBA").getchannel("A")
            corners = [
                alpha.getpixel((0, 0)),
                alpha.getpixel((alpha.width - 1, 0)),
                alpha.getpixel((0, alpha.height - 1)),
                alpha.getpixel((alpha.width - 1, alpha.height - 1)),
            ]
            checks.append((
                f"{label} PNG 透明背景",
                all(value == 0 for value in corners) and alpha.getextrema()[1] > 0,
                f"corners={corners} alpha_max={alpha.getextrema()[1]}",
            ))


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    figure_json: dict[str, str] = {}

    for label, name in PLOTS:
        at = _open_styled_plot(name)
        fig = _state(at, "last_plotly")
        ok = (
            len(at.exception) == 0
            and fig is not None
            and fig.layout.title.text == TITLE
            and FONT_CSS_FAMILY in str(fig.layout.font.family)
        )
        checks.append((
            f"{label}：应用中文标题与字体后真实出图",
            ok,
            f"exception={list(at.exception)} title={getattr(getattr(fig, 'layout', None), 'title', None)} "
            f"font={getattr(getattr(fig, 'layout', None), 'font', None)}",
        ))
        if fig is None:
            continue
        figure_json[name] = pio.to_json(fig)

    if len(figure_json) != len(PLOTS):
        failures = sum(0 if ok else 1 for _, ok, _ in checks)
        for label, ok, detail in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        print(f"export-products-apptest: {len(checks) - failures}/{len(checks)} passed")
        return 1

    with tempfile.TemporaryDirectory(prefix="bioplotter-export-") as temp_dir:
        temp_root = Path(temp_dir)

        for label, name in PLOTS:
            fig = pio.from_json(figure_json[name])
            css_w, css_h = _css_size(fig)
            transparent = name == "Node-link Diagram"
            dpi = 600 if name == "Heatmap" else 300
            scale = dpi / BASE_DPI

            png = render_static_bytes(
                figure_json[name], "png", css_w, css_h, scale, transparent, dpi
            )
            (temp_root / f"{name}.png").write_bytes(png)
            _check_png(checks, label, png, css_w, css_h, dpi, transparent)

            svg = render_static_bytes(
                figure_json[name], "svg", css_w, css_h, 1.0, False, dpi
            )
            (temp_root / f"{name}.svg").write_bytes(svg)
            svg_text = svg.decode("utf-8")
            root = _svg_root(svg_text)
            view_box = re.search(r'viewBox="([^"]+)"', root)
            view_values = (
                tuple(float(part) for part in view_box.group(1).split())
                if view_box
                else ()
            )
            svg_width = _svg_attr(root, "width")
            svg_height = _svg_attr(root, "height")
            checks.append((
                f"{label} SVG 物理尺寸与中文内容",
                bool(root)
                and svg_width == css_w
                and svg_height == css_h
                and view_values == (0.0, 0.0, float(css_w), float(css_h))
                and TITLE in svg_text
                and "Microsoft YaHei" in svg_text,
                f"root={root} viewBox={view_values}",
            ))

            pdf = render_static_bytes(
                figure_json[name], "pdf", css_w, css_h, 1.0, False, dpi
            )
            (temp_root / f"{name}.pdf").write_bytes(pdf)
            box = _media_box(pdf)
            width_mm = (box[2] - box[0]) / 72 * MM_PER_INCH if box else 0.0
            height_mm = (box[3] - box[1]) / 72 * MM_PER_INCH if box else 0.0
            expected_height_mm = css_h / BASE_DPI * MM_PER_INCH
            checks.append((
                f"{label} PDF MediaBox 物理尺寸",
                pdf.startswith(b"%PDF-")
                and box is not None
                and abs(width_mm - WIDTH_MM) <= 0.5
                and abs(height_mm - expected_height_mm) <= 0.5,
                f"box={box} size={width_mm:.2f}x{height_mm:.2f}mm",
            ))

            checks.append((
                f"{label} 顶部图例与隐藏网格",
                str(fig.layout.legend.orientation) == "h"
                and float(fig.layout.legend.y or 0) > 1.0
                and fig.layout.xaxis.showgrid is False
                and fig.layout.yaxis.showgrid is False,
                f"legend={fig.layout.legend.orientation}@{fig.layout.legend.y}",
            ))

        volcano_json = figure_json["Volcano Plot"]
        volcano = pio.from_json(volcano_json)
        css_w, css_h = _css_size(volcano)
        low = render_static_bytes(volcano_json, "png", css_w, css_h, 1.0, False)
        high = render_static_bytes(
            volcano_json, "png", css_w, css_h, 300 / BASE_DPI, False, 300
        )
        with Image.open(io.BytesIO(low)) as preview_image:
            preview = preview_image.convert("RGB")
        with Image.open(io.BytesIO(high)) as export_image:
            exported = export_image.convert("RGB")
        resized = exported.resize(preview.size, Image.Resampling.LANCZOS)
        pixel_delta = float(
            np.abs(
                np.asarray(preview, dtype=np.int16)
                - np.asarray(resized, dtype=np.int16)
            ).mean()
        )
        ratio_delta = abs(
            preview.width / preview.height - exported.width / exported.height
        )
        checks.append((
            "预览基准与 300 dpi 导出样式/比例一致",
            ratio_delta < 0.002 and pixel_delta < 18.0,
            f"ratio_delta={ratio_delta:.5f} mean_pixel_delta={pixel_delta:.2f}",
        ))

        long_labels = [
            "显著上调的基因集合 Alpha",
            "显著下调的基因集合 Beta",
            "细胞周期相关基因模块 Gamma",
            "免疫应答核心基因模块 Delta",
        ]
        long_x_labels = [
            "处理组 A 长期随访",
            "处理组 B 长期随访",
            "对照组 C 长期随访",
            "对照组 D 长期随访",
        ]
        long_fig = go.Figure(
            go.Scatter(
                x=long_x_labels,
                y=long_labels,
                mode="markers+text",
                text=["18", "11", "7", "4"],
                textposition="top center",
                name="基因数量",
                showlegend=True,
            )
        )
        long_fig.update_layout(
            margin=dict(l=20, r=20, t=24, b=24),
            width=960,
            height=640,
        )
        long_fig.update_xaxes(tickangle=-30)
        apply_figure_style(long_fig, _style_state())
        left_before = float(long_fig.layout.margin.l or 0)
        bottom_before = float(long_fig.layout.margin.b or 0)
        prevent_label_clipping(long_fig)
        left_after = float(long_fig.layout.margin.l or 0)
        bottom_after = float(long_fig.layout.margin.b or 0)
        checks.append((
            "长分类标签触发左侧/底部安全边距",
            left_after >= left_before + 80 and bottom_after >= bottom_before + 20,
            f"left {left_before}->{left_after}, bottom {bottom_before}->{bottom_after}",
        ))

        long_css_w, long_css_h = _css_size(long_fig)
        long_png = render_static_bytes(
            pio.to_json(long_fig),
            "png",
            long_css_w,
            long_css_h,
            300 / BASE_DPI,
            True,
            300,
        )
        (temp_root / "long-labels.png").write_bytes(long_png)
        with Image.open(io.BytesIO(long_png)) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            checks.append((
                "长标签导出图四边无内容裁切",
                _border_clear(rgba) and alpha.getbbox() is not None,
                f"size={rgba.size} bbox={alpha.getbbox()}",
            ))

    source = Path(APP_FILE).read_text(encoding="utf-8")
    checks.append((
        "应用导出路径接入静态核心并传递 DPI",
        "from app.core.export_static import" in source
        and "render_static_bytes(" in source
        and "render_html_bytes(" in source
        and "transparent,\n                    dpi," in source,
        "ok",
    ))

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += 0 if ok else 1
    print(f"export-products-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
