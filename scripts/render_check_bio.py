"""Render the 6 new bio-informatics figures to PNG via headless Chrome.

The 6 new modules are **not registered in ``app.py`` yet** (phase-3 UI work owns
that file), so this helper calls ``build({})`` directly instead of driving
Streamlit.  Developer-only visual QA tool.

    .venv\\Scripts\\python.exe scripts/render_check_bio.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.io as pio  # noqa: E402
import streamlit as st  # noqa: E402

OUT_DIR = PROJECT_ROOT / "scripts" / "_render_out"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CASES: list[tuple[str, str, dict]] = [
    ("volcano", "volcano_", {}),
    ("pca", "pca_", {}),
    ("heatmap", "heatmap_", {}),
    ("heatmap", "heatmap_", {"heatmap_cluster_rows": True, "heatmap_cluster_cols": True, "heatmap_row_group_col": "group"}),
    ("upset", "upset_", {}),
    ("kaplan_meier", "km_", {}),
    ("kaplan_meier", "km_", {"km_show_ci": True}),
    ("manhattan", "manhattan_", {}),
]


def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no Chrome/Edge found for rendering")


def build_figure(module_name: str, prefix: str, overrides: dict):
    module = __import__(f"app.modules.{module_name}", fromlist=["build"])
    st.session_state["theme"] = "Light"
    st.session_state[f"{prefix}use_sample"] = True
    for key, value in overrides.items():
        st.session_state[key] = value
    fig, _, _, _ = module.build({})
    return fig


def main() -> int:
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for index, (module_name, prefix, overrides) in enumerate(CASES):
        fig = build_figure(module_name, prefix, overrides)
        label = module_name + ("_" + "_".join(overrides) if overrides else "")
        html_path = OUT_DIR / f"{index:02d}_{label}.html"
        png_path = OUT_DIR / f"{index:02d}_{label}.png"
        html_path.write_text(pio.to_html(fig, include_plotlyjs="inline", full_html=True), encoding="utf-8")

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
        size = png_path.stat().st_size // 1024 if png_path.exists() else 0
        print(f"{label} -> {png_path.name} ({size} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
