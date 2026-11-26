"""Export preflight and journal-template acceptance tests.

    .venv\\Scripts\\python.exe -X utf8 scripts\\apptest_export_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.export_check import (  # noqa: E402
    JOURNAL_TEMPLATES,
    build_export_check,
    diagnose_static_export_error,
    figure_font_info,
)
from app.core.export_static import render_html_bytes  # noqa: E402


APP_FILE = str(PROJECT_ROOT / "app.py")


def _state(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _html(at: AppTest) -> str:
    return "\n".join(str(block.value) for block in at.markdown)


def _open_volcano() -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=240)
    at.session_state["page"] = "home"
    at.run()
    at.button(key="nav_Volcano Plot").click().run()
    for _ in range(3):
        if _state(at, "last_plotly") is not None:
            break
        at.run()
    return at


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    fig = go.Figure(go.Scatter(x=[1, 2], y=[2, 3], name="A"))
    fig.update_layout(
        title=dict(text="检查图", font=dict(size=14)),
        font=dict(family="Microsoft YaHei", size=12),
        legend=dict(font=dict(size=10)),
    )
    fig.update_xaxes(title_text="X", title_font=dict(size=11), tickfont=dict(size=9))
    fig.update_yaxes(title_text="Y", title_font=dict(size=11), tickfont=dict(size=8))
    family, min_font_px = figure_font_info(fig)
    checks.append((
        "读取字体族与最小可见字号",
        "Microsoft YaHei" in family and min_font_px == 8,
        f"family={family} min_px={min_font_px}",
    ))

    report = build_export_check(
        fmt="PNG",
        file_name="Figure 1",
        width_mm=89,
        height_mm=50,
        dpi=300,
        transparent=True,
        template_name="Nature 单栏 89mm",
        font_family=family,
        min_font_pt=6.0,
        static_ready=True,
    )
    report_text = "\n".join(f"{item.label}: {item.value}" for item in report.items)
    checks.append((
        "PNG 预计像素与 300 dpi 检查",
        "89.0 × 50.0 mm" in report_text
        and "1051 × 591 px" in report_text
        and "300 dpi" in report_text
        and "PNG 位图" in report_text
        and "透明背景" in report_text,
        report_text,
    ))
    checks.append((
        "模板、字号、颜色与文件名通过",
        report.warnings == 0
        and "宽度匹配" in report_text
        and "最小 6.0 pt" in report_text
        and "RGB" in report_text
        and "CMYK 暂不支持" in report_text
        and "Figure 1.png" in report_text,
        report.summary,
    ))

    mismatch = build_export_check(
        fmt="SVG",
        file_name="Figure 1",
        width_mm=85,
        height_mm=50,
        template_name="Nature 单栏 89mm",
        font_family="Arial",
        min_font_pt=5.2,
    )
    mismatch_text = "\n".join(item.value for item in mismatch.items)
    checks.append((
        "模板偏差与小字号产生提醒",
        mismatch.warnings == 2
        and "建议 89 mm" in mismatch_text
        and "建议 ≥6 pt" in mismatch_text,
        mismatch.summary,
    ))

    html_report = build_export_check(
        fmt="HTML",
        file_name="Figure 1",
        width_mm=None,
        height_mm=None,
        font_family="Arial",
        min_font_pt=9.0,
        html_offline=True,
    )
    html_text = "\n".join(item.value for item in html_report.items)
    checks.append((
        "离线 HTML 检查项",
        "完全离线" in html_text and "Plotly JS" in html_text,
        html_text,
    ))

    html_specs = render_html_bytes(fig, offline=True)
    cdn_specs = render_html_bytes(fig, offline=False)
    checks.append((
        "离线 HTML 内联 Plotly 且不依赖 CDN",
        len(html_specs) > 1_000_000
        and b'src="https://cdn.plot.ly' not in html_specs
        and b"Plotly.newPlot" in html_specs
        and b'src="https://cdn.plot.ly' in cdn_specs,
        f"offline={len(html_specs)} cdn={len(cdn_specs)}",
    ))

    browser_error = diagnose_static_export_error(
        RuntimeError("Failed to launch Chrome browser"), static_ready=True
    )
    kaleido_error = diagnose_static_export_error(
        RuntimeError("kaleido executable is missing"), static_ready=False
    )
    checks.append((
        "静态导出错误区分 Kaleido 与 Chrome",
        "Chrome/Chromium" in browser_error
        and "kaleido" in kaleido_error.lower()
        and "HTML" in kaleido_error,
        f"browser={browser_error}; kaleido={kaleido_error}",
    ))

    checks.append((
        "期刊模板覆盖 Nature/Cell/Science",
        all(name in JOURNAL_TEMPLATES for name in (
            "Nature 单栏 89mm",
            "Nature 双栏 183mm",
            "Cell 单栏 85mm",
            "Cell 双栏 174mm",
            "Science 单栏 55mm",
            "Science 双栏 121mm",
        )),
        str(JOURNAL_TEMPLATES),
    ))

    at = _open_volcano()
    preset_key = "export_preset_toolbar_Volcano Plot"
    at.selectbox(key=preset_key).set_value("Nature 单栏 89mm").run()
    panel_html = _html(at)
    checks.append((
        "面板显示模板、预计像素与 RGB 检查",
        "导出前检查" in panel_html
        and "Nature 单栏 89mm" in panel_html
        and "宽度匹配" in panel_html
        and " px" in panel_html
        and "CMYK 暂不支持" in panel_html,
        "ok" if "导出前检查" in panel_html else panel_html,
    ))

    at.selectbox(key=preset_key).set_value("自定义").run()
    custom_checkbox = [box for box in at.checkbox if box.key and "export_lock_aspect" in box.key]
    checks.append((
        "自定义尺寸提供锁定纵横比",
        any(
            box.key and "export_lock_aspect" in box.key and bool(box.value)
            for box in at.checkbox
        ),
        str(custom_checkbox),
    ))

    at.radio(key="export_fmt_toolbar_Volcano Plot").set_value("HTML").run()
    mode_key = "export_html_mode_toolbar_Volcano Plot"
    at.radio(key=mode_key).set_value("完全离线（内联 Plotly JS）").run()
    html_panel = _html(at)
    checks.append((
        "HTML 支持完全离线并写入检查结果",
        "HTML 资源" in html_panel
        and "完全离线" in html_panel
        and "Plotly JS 已内联" in html_panel,
        "ok" if "完全离线" in html_panel else html_panel,
    ))

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += 0 if ok else 1
    print(f"export-check-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
