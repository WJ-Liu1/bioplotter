"""Render each native-fusion figure to PNG via headless Chrome for visual QA.

This is a developer-only helper (not part of the test suite): it uses Streamlit's
``AppTest`` to obtain the real figure object, writes a self-contained HTML file
with the bundled plotly.js, and screenshots it with headless Chrome.

    .venv\\Scripts\\python.exe scripts/render_check.py
"""

from __future__ import annotations

import subprocess
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.io as pio  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_FILE = str(PROJECT_ROOT / "app.py")
OUT_DIR = PROJECT_ROOT / "scripts" / "_render_out"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CASES = [
    ("BubbleViz", {}),
    ("BubbleViz", {"bubble_mode": "动画"}),
    ("Grouped Matrix Plotting", {}),
    ("CircleViz", {}),
    ("CircularBarPlot", {}),
    ("CircularBarPlot", {"cbar_view_mode": "条形图（分面）"}),
    ("Genomic Variation Viewer", {}),
    ("Genomic Variation Viewer", {"genvar_mode": "Dandelion（单层发散）", "genvar_show_label": True}),
]


def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no Chrome/Edge found for rendering")


def build_figure(name: str, overrides: dict):
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state["page"] = "home"
    at.run()
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        try:
            if len(at.get("plotly_chart")) >= 1:
                break
        except Exception:
            pass
        at.run()
    if overrides:
        for key, value in overrides.items():
            at.session_state[key] = value
        at.button(key=f"generate_{name}").click().run()
        for _ in range(2):
            if at.session_state["last_plotly"] is not None:
                break
            at.run()
    return at.session_state["last_plotly"]


def main() -> int:
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for index, (name, overrides) in enumerate(CASES):
        fig = build_figure(name, overrides)
        if fig is None:
            print(f"skip {name}: no figure")
            continue
        label = name.replace(" ", "_") + ("_" + "_".join(overrides) if overrides else "")
        html_path = OUT_DIR / f"{index:02d}_{label}.html"
        png_path = OUT_DIR / f"{index:02d}_{label}.png"
        html_path.write_text(
            pio.to_html(fig, include_plotlyjs="inline", full_html=True),
            encoding="utf-8",
        )

        width = int(fig.layout.width or 900) + 80
        height = int(fig.layout.height or 600) + 80
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-sandbox",
                f"--window-size={width},{height}",
                f"--screenshot={png_path}",
                "--virtual-time-budget=6000",
                html_path.resolve().as_uri(),
            ],
            check=False,
            capture_output=True,
            timeout=180,
        )
        print(f"{name} {overrides or ''} -> {png_path.name} ({img_size(png_path)})")

    return 0


def img_size(path: Path) -> str:
    if not path.exists():
        return "missing"
    return f"{path.stat().st_size // 1024} KB"


if __name__ == "__main__":
    raise SystemExit(main())
