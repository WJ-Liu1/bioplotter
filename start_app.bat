@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

%PYTHON% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [BioPlotter] Installing requirements...
    %PYTHON% -m pip install -r requirements.txt
)

%PYTHON% -m streamlit run app.py %*
endlocal
