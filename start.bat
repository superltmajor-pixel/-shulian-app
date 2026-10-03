@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Shulian backend starting...
echo   Open http://localhost:8000/ to use
echo   Open http://localhost:8000/docs to test
echo   Keep this window open. Close it to stop.
echo ============================================
"%~dp0venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
