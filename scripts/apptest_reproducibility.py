from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.layout_guard import prevent_label_clipping
from app.core.project_io import build_project_bundle, restore_project_bundle
from app.core.catalog import meta_for
from app.modules.beeswarm import _apply_priority, _swarm_offsets


APP_FILE = str(PROJECT_ROOT / "app.py")


def open_plot(name: str) -> AppTest:
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state["page"] = "home"
    at.run()
    at.button(key=f"nav_{name}").click().run()
    return at


def points(fig) -> list[list[float]]:
    return [list(trace.x) for trace in fig.data if "markers" in str(trace.mode)]


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    at = open_plot("Pirate Plot")
    at.session_state["pir_seed"] = 123
    at.button(key="generate_Pirate Plot").click().run()
    first = at.session_state["last_plotly"]
    at.button(key="generate_Pirate Plot").click().run()
    checks.append((
        "Pirate same seed reproduces jitter",
        points(first) == points(at.session_state["last_plotly"]),
        "point coordinates identical",
    ))
    first = at.session_state["last_plotly"]
    at.session_state["pir_seed"] = 124
    at.button(key="generate_Pirate Plot").click().run()
    checks.append((
        "Pirate different seed changes jitter",
        points(first) != points(at.session_state["last_plotly"]),
        "point coordinates differ",
    ))

    values = np.array([1.0, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0])
    checks.append((
        "Beeswarm random priority is deterministic",
        np.array_equal(
            _apply_priority(values, "random", np.random.default_rng(42)),
            _apply_priority(values, "random", np.random.default_rng(42)),
        ),
        "permutations identical",
    ))

    args = dict(priority="random", side=0, corral="random", diameter_px=2.0,
                width_px=15.0, px_per_y=10.0, height_px=80.0)
    at = open_plot("Beeswarm")
    at.session_state["bee_seed"] = 9
    first_offsets = _swarm_offsets(values, **args)
    at.session_state["bee_seed"] = 9
    second_offsets = _swarm_offsets(values, **args)
    checks.append((
        "Beeswarm same seed reproduces layout",
        np.array_equal(first_offsets[0], second_offsets[0])
        and np.array_equal(first_offsets[1], second_offsets[1]),
        "offsets identical",
    ))

    fig = go.Figure(go.Scatter(x=[1], y=[1]))
    fig.update_yaxes(ticktext=["这是一个很长的纵轴标签"], tickvals=[1], tickfont={"size": 14})
    fig.update_xaxes(ticktext=["很长的横轴标签"], tickvals=[1], tickangle=90, tickfont={"size": 14})
    fig.update_layout(margin=dict(l=10, b=10))
    prevent_label_clipping(fig)
    checks.append((
        "Layout guard reserves long CJK label margins",
        fig.layout.margin.l > 100 and fig.layout.margin.b > 60,
        f"left={fig.layout.margin.l}, bottom={fig.layout.margin.b}",
    ))
    composite_fig = go.Figure([
        go.Sankey(node={"label": ["A", "B"]}, link={"source": [0], "target": [1], "value": [1]}),
        go.Table(header={"values": ["group"]}, cells={"values": [["A"]]}),
    ])
    prevent_label_clipping(composite_fig)
    checks.append((
        "Layout guard supports traces without showlegend",
        len(composite_fig.data) == 2,
        "Sankey and Table retained",
    ))

    at = open_plot("Pirate Plot")
    at.session_state["pir_seed"] = 456
    at.button(key="generate_Pirate Plot").click().run()
    bundle, _, _ = build_project_bundle("Pirate Plot", meta_for("Pirate Plot"), at.session_state)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    checks.append((
        "Project stores seed",
        manifest["params"].get("pir_seed") == 456,
        str({"seed": manifest["params"].get("pir_seed")}),
    ))
    fresh = AppTest.from_file(APP_FILE, default_timeout=180)
    fresh.session_state["page"] = "home"
    restore_project_bundle(bundle, fresh.session_state, {"Pirate Plot"})
    fresh.query_params["page"] = "plot"
    fresh.query_params["plot"] = "Pirate Plot"
    fresh.run()
    checks.append((
        "Project restores seed",
        fresh.session_state["pir_seed"] == 456,
        f"seed={fresh.session_state['pir_seed']}",
    ))

    failures = 0
    for label, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += 0 if ok else 1
    print(f"reproducibility-apptest: {len(checks) - failures}/{len(checks)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
