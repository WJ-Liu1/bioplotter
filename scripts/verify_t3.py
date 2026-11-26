"""T3 acceptance checks for the 6 new bio-informatics modules.

Two things are verified per module:

1. **Build contract** (architecture T3): ``build({})`` with only
   ``theme="Light"`` and ``<prefix>use_sample=True`` in ``session_state`` returns
   ``(Figure, DataFrame | dict[str, DataFrame], 中文 status, HELP_TEXT)`` without
   raising, and the figure survives ``to_json()`` (< 8 MB).
2. **Algorithm assertions**: PCA explained variance sums to ~1, Heatmap row
   z-scores average ~0, KM survival is monotonically non-increasing with
   ``p ∈ [0, 1]``, Manhattan ``cum_pos`` increases, UpSet bars descend, and the
   Volcano group counts add up to the total row count.

    .venv\\Scripts\\python.exe scripts/verify_t3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MODULES = {
    "volcano": ("volcano", "volcano_"),
    "pca": ("pca", "pca_"),
    "heatmap": ("heatmap", "heatmap_"),
    "upset": ("upset", "upset_"),
    "kaplan_meier": ("kaplan_meier", "km_"),
    "manhattan": ("manhattan", "manhattan_"),
}


def _build(name: str, prefix: str):
    """Call ``build({})`` with a minimal session state (bare mode)."""
    import streamlit as st

    module = __import__(f"app.modules.{name}", fromlist=["build"])
    st.session_state["theme"] = "Light"
    st.session_state[f"{prefix}use_sample"] = True
    return module, module.build({})


def check_contract(name: str, prefix: str) -> tuple[list[str], object]:
    problems: list[str] = []
    module, result = _build(name, prefix)

    for attribute in ("controls", "build", "render", "__call__"):
        if not hasattr(module, attribute) or not callable(getattr(module, attribute)):
            problems.append(f"missing callable {attribute}")
    if not getattr(module, "HELP_TEXT", ""):
        problems.append("missing HELP_TEXT")

    if not isinstance(result, tuple) or len(result) != 4:
        problems.append(f"build() returned {type(result).__name__}, expected a 4-tuple")
        return problems, None

    fig, data, status, help_text = result
    if fig is None:
        problems.append("figure is None")
    else:
        try:
            size = len(fig.to_json())
            if size > 8 * 1024 * 1024:
                problems.append(f"figure JSON too large ({size} bytes)")
        except Exception as exc:
            problems.append(f"figure not serialisable: {exc}")

    if isinstance(data, pd.DataFrame):
        if data.empty:
            problems.append("data DataFrame is empty")
    elif isinstance(data, dict):
        if not data or not all(isinstance(value, pd.DataFrame) for value in data.values()):
            problems.append("data dict is malformed")
    else:
        problems.append(f"data is {type(data).__name__}")

    if not status or not any(character.isdigit() for character in str(status)):
        problems.append(f"status missing digits: {status!r}")
    if not any("\u4e00" <= character <= "\u9fff" for character in str(status)):
        problems.append(f"status is not Chinese: {status!r}")
    if not help_text:
        problems.append("help_text is empty")
    return problems, result


def main() -> int:
    failures: list[str] = []
    lines: list[str] = []

    results: dict[str, object] = {}
    for name, (module_name, prefix) in MODULES.items():
        try:
            problems, result = check_contract(module_name, prefix)
        except Exception as exc:
            problems, result = [f"build() raised {type(exc).__name__}: {exc}"], None
        if problems:
            failures.extend(f"{name}: {problem}" for problem in problems)
            lines.append(f"[FAIL] {name}: {'; '.join(problems)}")
            continue
        results[name] = result
        fig, data, status, _ = result
        rows = len(data) if isinstance(data, pd.DataFrame) else sum(len(v) for v in data.values())
        lines.append(f"[PASS] {name}: traces={len(fig.data)} · rows={rows} · {status}")

    # ---- algorithm assertions ------------------------------------------
    lines.append("")

    def record(label: str, ok: bool, detail: str) -> None:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        if not ok:
            failures.append(f"{label}: {detail}")

    # PCA: explained variance ratio sums to 1 (recompute from the module helper)
    if "pca" in results:
        from app.modules.pca import _pca_scores, _split_frame

        frame = _read_sample("pca_samples")
        _, features, _ = _split_frame(frame, "group")
        _, explained = _pca_scores(features, "z-score 标准化")
        record("PCA 解释方差和≈1", abs(float(explained.sum()) - 1.0) < 1e-9, f"sum={explained.sum():.12f}")

    # Heatmap: row z-score means ≈ 0
    if "heatmap" in results:
        z_df = results["heatmap"][1].select_dtypes("number")
        row_means = z_df.mean(axis=1).abs()
        record("Heatmap 行 z-score 均值≈0", bool((row_means < 1e-9).all()), f"max |mean|={row_means.max():.3e}")

    # KM: survival monotone non-increasing, p ∈ [0, 1]
    if "kaplan_meier" in results:
        fig, data, status, _ = results["kaplan_meier"]
        curves = [trace for trace in fig.data if getattr(getattr(trace, "line", None), "shape", None) == "hv"]
        monotone = True
        for trace in curves:
            values = np.asarray(trace.y, dtype=float)
            if values.size > 1 and np.any(np.diff(values) > 1e-12):
                monotone = False
        record("KM S(t) 单调不增", bool(curves) and monotone, f"{len(curves)} 条曲线")
        p_text = str(status).split("log-rank p = ")[-1]
        try:
            p_value = float(p_text)
            ok = 0.0 <= p_value <= 1.0
        except ValueError:
            p_value, ok = float("nan"), False
        record("KM log-rank p∈[0,1]", ok, f"p={p_value:g}")

    # Manhattan: cum_pos strictly increasing
    if "manhattan" in results:
        df = results["manhattan"][1]
        diffs = np.diff(df["cum_pos"].to_numpy(dtype=float))
        record("Manhattan cum_pos 递增", bool((diffs > 0).all()), f"min diff={diffs.min():.3g}")

    # UpSet: intersection bars descending
    if "upset" in results:
        fig = results["upset"][0]
        bars = [trace for trace in fig.data if trace.type == "bar" and getattr(trace, "orientation", None) != "h"]
        values = np.asarray(bars[0].y, dtype=float) if bars else np.array([])
        record("UpSet 交集柱降序", values.size > 0 and bool((np.diff(values) <= 0).all()), f"n={values.size}")

    # Volcano: up + down + ns == total
    if "volcano" in results:
        df = results["volcano"][1]
        counts = df["group"].value_counts()
        total = int(df.shape[0])
        summed = int(counts.get("上调", 0) + counts.get("下调", 0) + counts.get("不显著", 0))
        record("Volcano 三组行数相加=总数", summed == total, f"{summed} / {total}")

    print("\n".join(lines))
    print()
    print(f"t3: {len(failures)} failure(s)")
    return 0 if not failures else 1


def _read_sample(key: str) -> pd.DataFrame:
    from app.core.io_utils import read_table
    from app.core.sample_utils import get_sample_path

    path = get_sample_path(key)
    return read_table(path, path.name)


if __name__ == "__main__":
    raise SystemExit(main())
