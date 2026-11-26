"""Render the 11 SCI-styled modules to PNG (light + dark) for visual QA.

Each figure is produced through the real app (AppTest), so the shots reflect the
actual sidebar defaults and SCI palette, then screenshotted with headless Chrome.

    .venv\\Scripts\\python.exe scripts/render_sci.py
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
OUT_DIR = PROJECT_ROOT / "scripts" / "_sci_shots"

MODULES = [
    "Volcano Plot",
    "PCA",
    "Heatmap",
    "UpSet Plot",
    "Kaplan-Meier",
    "Manhattan Plot",
    "BubbleViz",
    "Grouped Matrix Plotting",
    "CircleViz",
    "CircularBarPlot",
    "Genomic Variation Viewer",
]

LEGACY_MODULES = [
    "Arc Diagram",
    "Hierarchical Edge Bundling",
    "Chord Diagram",
    "Node-link Diagram",
    "Sankey",
    "Raincloud Plot",
    "Beeswarm",
    "Split Violin",
    "ScaBoxDen",
    "Pirate Plot",
    "Mantel Test",
    "GO Enrichment",
]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no Chrome/Edge found")


def build_figure(name: str, theme: str):
    at = AppTest.from_file(APP_FILE, default_timeout=200)
    at.session_state["page"] = "home"
    at.session_state["theme"] = theme
    at.run()
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        if len(at.get("plotly_chart")) >= 1:
            break
        at.run()
    fig = at.session_state["last_plotly"]
    if fig is None:
        raise RuntimeError(f"{name}: no figure ({at.session_state['status']})")
    return fig


def main() -> int:
    global OUT_DIR
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    # 可选：--out=DIR 指定输出目录；其余参数视为模块名（只渲染指定模块）
    out_arg = next((a for a in sys.argv[1:] if a.startswith("--out=")), None)
    if out_arg:
        OUT_DIR = PROJECT_ROOT / "scripts" / out_arg.split("=", 1)[1]
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    known = [a for a in names if a in MODULES or a in LEGACY_MODULES]
    targets = known or MODULES

    for theme in ("Light", "Dark"):
        for name in targets:
            fig = build_figure(name, theme)
            stem = f"{theme}_{name.replace(' ', '_')}"
            html_path = OUT_DIR / f"{stem}.html"
            png_path = OUT_DIR / f"{stem}.png"
            html_path.write_text(pio.to_html(fig, include_plotlyjs="inline", full_html=True), encoding="utf-8")

            width = int(fig.layout.width or 900) + 60
            height = int(fig.layout.height or 600) + 70
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
            size = png_path.stat().st_size // 1024 if png_path.exists() else 0
            count += 1
            print(f"{stem} -> {size} KB")

    print(f"total {count} shots in {OUT_DIR.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
