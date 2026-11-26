"""Option sweep: regenerate each migrated module for every risky widget option.

Guards against invalid Plotly property values (e.g. a marker symbol that this
Plotly version does not know) that only surface when a specific dropdown option
is picked.  Every case uses a fresh ``AppTest`` session: the sidebar value is
written to ``session_state`` and the 「生成图形」 button is clicked.

    .venv\\Scripts\\python.exe scripts/apptest_option_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_FILE = str(PROJECT_ROOT / "app.py")

SYMBOLS = ["circle", "square", "star", "triangle-up", "triangle-down", "diamond"]

SWEEP: dict[str, list[tuple[str, list]]] = {
    "BubbleViz": [
        ("bubble_sample_pick", ["bubble_country", "bubble_aqi"]),
        ("bubble_mode", ["静态", "动画"]),
        ("bubble_symbol", ["circle", "square", "triangle-up"]),
        ("bubble_aspect", ["16:9", "2:1", "4:3", "3:4"]),
        ("bubble_palette", ["Viridis", "Plasma", "Bluyl", "Sunset"]),
        ("bubble_hue_col", ["Continent", "(单色)", "Year"]),
    ],
    "Grouped Matrix Plotting": [
        ("gmp_layout_mode", ["长表（row/group/column/category）", "宽表（第 1 列为行名）"]),
        ("gmp_double_border", [False, True]),
        ("gmp_cat_symbol_1", SYMBOLS),
        ("gmp_cat_symbol_2", ["star", "square"]),
        ("gmp_cat_symbol_3", ["diamond", "triangle-down"]),
    ],
    "CircleViz": [
        (
            "circle_node_shape",
            ["圆形 (circle)", "方形 (square)", "菱形 (lozenge)", "上三角 (triangle-up)", "下三角 (triangle-down)"],
        ),
        ("circle_sort_mode", ["按 data4 升序", "按分组名升序"]),
        ("circle_show_center_text", [True, False]),
    ],
    "CircularBarPlot": [
        ("cbar_view_mode", ["环形图（极坐标柱）", "条形图（分面）"]),
        ("cbar_sort_mode", ["不排序", "降序", "升序"]),
        ("cbar_hole", [0.0, 0.35, 0.8]),
    ],
    "Genomic Variation Viewer": [
        ("genvar_mode", ["Lollipop（上下双层）", "Dandelion（单层发散）"]),
        ("genvar_marker_shape", ["circle", "flag", "pin"]),
        ("genvar_snp_size_mode", ["统一", "随机", "自定义"]),
        ("genvar_snp_palette_mode", ["单色", "随机"]),
        ("genvar_show_label", [True, False]),
    ],
}


def open_module(name: str) -> AppTest:
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
    return at


def main() -> int:
    failures: list[str] = []
    checked = 0

    for name, cases in SWEEP.items():
        for key, values in cases:
            for value in values:
                checked += 1
                label = f"{name} · {key}={value}"
                at = open_module(name)
                at.session_state[key] = value
                try:
                    at.button(key=f"generate_{name}").click().run()
                except Exception as exc:
                    failures.append(f"{label}: generate click failed ({exc})")
                    continue
                for _ in range(2):
                    if at.session_state["last_plotly"] is not None:
                        break
                    at.run()
                if at.exception:
                    failures.append(f"{label}: exception {at.exception}")
                    continue
                fig = at.session_state["last_plotly"]
                if fig is None:
                    failures.append(f"{label}: no figure")
                    continue
                try:
                    fig.to_json()
                except Exception as exc:
                    failures.append(f"{label}: invalid figure ({exc})")
                    continue
                if str(at.session_state["status_kind"]) != "success":
                    failures.append(f"{label}: status {at.session_state['status_kind']}")

    print()
    for item in failures:
        print(f"[FAIL] {item}")
    print(f"sweep: {checked} option combinations, {len(failures)} failures")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
