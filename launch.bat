@echo off
REM Learnfast Dashboard Launcher
REM Double-click this file to start the dashboard

cd /d "%~dp0"
echo Starting Learnfast Dashboard...
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Set PYTHONPATH to the project root so imports work
set PYTHONPATH=%~dp0

REM Launch streamlit
streamlit run src\web\dashboard.py --server.headless true

pause
