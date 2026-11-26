"""Run every Python recipe in the docs hub against the bundled sample data.

    .venv\\Scripts\\python.exe scripts/check_py_recipes.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import plotly.basedatatypes as basedatatypes  # noqa: E402

plt.show = lambda *args, **kwargs: None
basedatatypes.BaseFigure.show = lambda *args, **kwargs: None

from app.core.catalog import PLOTS  # noqa: E402
from app.core.py_recipes import MODULE_SOURCES, module_source_for, py_code_for  # noqa: E402

SAMPLE_DIR = PROJECT_ROOT / "sample_data"


def main() -> int:
    failures: list[tuple[str, str]] = []
    for name in PLOTS:
        code = py_code_for(name)
        if not code.strip():
            failures.append((name, "empty recipe"))
            continue
        previous = os.getcwd()
        os.chdir(SAMPLE_DIR)
        try:
            exec(compile(code, f"<{name}>", "exec"), {"__name__": "__main__"})
        except Exception:
            failures.append((name, traceback.format_exc(limit=4)))
        finally:
            os.chdir(previous)
            plt.close("all")

    missing_source = [name for name in PLOTS if module_source_for(name) is None]
    unmapped = [name for name in PLOTS if name not in MODULE_SOURCES]

    for name, detail in failures:
        print(f"[FAIL] {name}\n{detail}")
    print(f"recipes runnable: {len(PLOTS) - len(failures)}/{len(PLOTS)}")
    print(f"module sources found: {len(PLOTS) - len(missing_source)}/{len(PLOTS)}")
    if unmapped:
        print(f"unmapped: {unmapped}")
    return 0 if not failures and not missing_source else 1


if __name__ == "__main__":
    raise SystemExit(main())
