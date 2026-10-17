@echo off
title ArchIntel Studio - Architectural Design Workstation
color 0B
echo ======================================================================
echo          ARCHINTEL STUDIO: ARCHITECTURAL DESIGN WORKSTATION           
echo ======================================================================
echo.
echo Activating Python virtual environment...
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment (.venv) not found.
    echo Please make sure the project dependencies are installed.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Starting Streamlit Studio UI on http://localhost:8501 ...
echo Press Ctrl+C in this terminal window to stop the server anytime.
echo.

streamlit run streamlit_app.py --server.port 8501

pause
