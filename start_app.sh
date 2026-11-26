#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python}"
if [ -x ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

if ! "$PYTHON" -c "import streamlit" >/dev/null 2>&1; then
    echo "[BioPlotter] 未检测到依赖，正在安装 requirements.txt ..."
    "$PYTHON" -m pip install -r requirements.txt
fi

exec "$PYTHON" -m streamlit run app.py "$@"
