"""Streamlit ``AppTest`` smoke test for the 5 migrated native modules (T2).

Run from the project root::

    .venv\\Scripts\\python.exe scripts/apptest_native_modules.py

For each module it clicks ``nav_<MODULES key>`` and asserts:

* no exception raised,
* at least one ``plotly_chart`` element,
* ``status_kind == "success"``,
* ``data`` is a ``DataFrame`` or a ``dict[str, DataFrame]``,
* the module-specific T2 trace budget (see ``TRACE_BUDGET``).

Then it replays a handful of sidebar variants and finally checks the
"no data uploaded" error path returns instead of raising.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_FILE = str(PROJECT_ROOT / "app.py")

MODULE_NAMES = [
    "BubbleViz",
    "Grouped Matrix Plotting",
    "CircleViz",
    "CircularBarPlot",
    "Genomic Variation Viewer",
]

# T2 acceptance §7/§8 + the architect's "trace <= 32" rule for polar figures.
TRACE_BUDGET: dict[str, int] = {
    "BubbleViz": 8,
    "Grouped Matrix Plotting": 12,
    "CircleViz": 32,
    "CircularBarPlot": 16,
    "Genomic Variation Viewer": 8,
}

SWITCH_KEYS: dict[str, str] = {
    "BubbleViz": "bubble_use_sample",
    "Grouped Matrix Plotting": "gmp_use_sample",
    "CircleViz": "circle_use_sample",
    "CircularBarPlot": "cbar_use_sample",
    "Genomic Variation Viewer": "genvar_use_sample",
}

VARIANTS: dict[str, list[tuple[str, dict]]] = {
    "BubbleViz": [
        ("static/aqi", {"bubble_sample_pick": "bubble_aqi", "bubble_col_frame": "无"}),
        ("animated/log-x", {"bubble_sample_pick": "bubble_country", "bubble_mode": "动画", "bubble_xlog": True}),
        ("no-title/single", {"bubble_hue_col": "(单色)", "bubble_add_title": False}),
    ],
    "Grouped Matrix Plotting": [
        ("double-border", {"gmp_double_border": True, "gmp_show_group_legend": False, "gmp_show_grid": False}),
        ("no-legend", {"gmp_show_cat_legend": False, "gmp_font_size": 14, "gmp_marker_size": 18}),
    ],
    "CircleViz": [
        ("group-sort", {"circle_sort_mode": "按分组名升序", "circle_h_bar": 2.0, "circle_show_legend": False}),
        ("big-rings", {"circle_h_inner": 0.2, "circle_h_mid": 0.2, "circle_h_outer": 0.2}),
    ],
    "CircularBarPlot": [
        ("faceted", {"cbar_view_mode": "条形图（分面）", "cbar_sort_mode": "降序"}),
        ("circular/asc", {"cbar_view_mode": "环形图（极坐标柱）", "cbar_sort_mode": "升序", "cbar_start_angle": 180}),
    ],
    "Genomic Variation Viewer": [
        ("dandelion", {"genvar_mode": "Dandelion（单层发散）", "genvar_show_label": True}),
        ("range", {"genvar_mode": "Lollipop（上下双层）", "genvar_range_start": 100.0, "genvar_range_end": 600.0}),
        ("flag-marker", {"genvar_marker_shape": "flag", "genvar_snp_palette_mode": "随机"}),
    ],
}


def _state(at: AppTest, key: str, default=None):
    """``AppTest.session_state`` is a proxy without ``.get``."""
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _has_plotly(at: AppTest) -> bool:
    try:
        return len(at.get("plotly_chart")) >= 1
    except Exception:
        return False


def open_module(name: str) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state["page"] = "home"
    at.run()
    at.button(key=f"nav_{name}").click().run()
    for _ in range(3):
        if _has_plotly(at):
            break
        at.run()
    return at


def check_payload(name: str, at: AppTest) -> list[str]:
    problems: list[str] = []
    if at.exception:
        problems.append(f"exception: {at.exception}")
        return problems

    fig = _state(at, "last_plotly")
    data = _state(at, "data")
    status = _state(at, "status")

    if fig is None:
        problems.append("no figure")
    else:
        try:
            size = len(fig.to_json())
            if size > 8 * 1024 * 1024:
                problems.append(f"figure JSON too large ({size} bytes)")
        except Exception as exc:
            problems.append(f"figure not serialisable: {exc}")
        budget = TRACE_BUDGET.get(name)
        if budget is not None and len(fig.data) > budget:
            problems.append(f"trace count {len(fig.data)} > budget {budget}")

    if _state(at, "status_kind") != "success":
        problems.append(f"status_kind={_state(at, 'status_kind')!r}")
    if not status or not any(character.isdigit() for character in str(status)):
        problems.append(f"status missing digits: {status!r}")

    if isinstance(data, pd.DataFrame):
        if data.empty:
            problems.append("data preview DataFrame is empty")
    elif isinstance(data, dict):
        if not data:
            problems.append("data preview dict is empty")
        for key, value in data.items():
            if not isinstance(value, pd.DataFrame):
                problems.append(f"data[{key!r}] is {type(value).__name__}")
    else:
        problems.append(f"data preview is {type(data).__name__}")
    return problems


def run_module(name: str) -> tuple[bool, str]:
    at = open_module(name)
    problems = check_payload(name, at)
    if problems:
        return False, "; ".join(problems)

    fig = _state(at, "last_plotly")
    data = _state(at, "data")
    rows = len(data) if isinstance(data, pd.DataFrame) else sum(len(value) for value in data.values())
    return True, f"traces={len(fig.data)} · rows={rows} · {_state(at, 'status')}"


def run_variant(name: str, overrides: dict) -> tuple[bool, str]:
    at = open_module(name)
    for key, value in overrides.items():
        at.session_state[key] = value
    try:
        at.button(key=f"generate_{name}").click().run()
    except Exception as exc:
        return False, f"generate click failed: {exc}"
    for _ in range(2):
        if _state(at, "last_plotly") is not None:
            break
        at.run()

    problems = check_payload(name, at)
    if problems:
        return False, "; ".join(problems)
    return True, f"traces={len(_state(at, 'last_plotly').data)} · {_state(at, 'status')}"


def run_empty_path(name: str) -> tuple[bool, str]:
    """T2 §5: no sample and no upload must return, not raise."""
    at = open_module(name)
    at.session_state[SWITCH_KEYS[name]] = False
    try:
        at.button(key=f"generate_{name}").click().run()
    except Exception as exc:
        return False, f"generate click failed: {exc}"
    at.run()

    if at.exception:
        return False, f"exception: {at.exception}"
    status = str(_state(at, "status") or "")
    if _state(at, "status_kind") != "warning":
        return False, f"status_kind={_state(at, 'status_kind')!r} status={status!r}"
    if "请先上传" not in status:
        return False, f"unexpected status text: {status!r}"
    return True, status


def main() -> int:
    failures = 0
    lines: list[str] = []

    for name in MODULE_NAMES:
        ok, message = run_module(name)
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}: {message}")
        failures += 0 if ok else 1

    lines.append("")
    variant_total = 0
    for name, cases in VARIANTS.items():
        for label, overrides in cases:
            variant_total += 1
            ok, message = run_variant(name, overrides)
            lines.append(f"[{'PASS' if ok else 'FAIL'}] {name} · {label}: {message}")
            failures += 0 if ok else 1

    lines.append("")
    for name in MODULE_NAMES:
        ok, message = run_empty_path(name)
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name} · empty-input: {message}")
        failures += 0 if ok else 1

    print("\n".join(lines))
    total = len(MODULE_NAMES) + variant_total + len(MODULE_NAMES)
    print()
    print(f"summary: {total - failures}/{total} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
