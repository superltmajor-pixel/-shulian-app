@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
echo ============================================
echo   Shulian Backend starting...
echo   App:  http://127.0.0.1:8000/
echo   Docs: http://127.0.0.1:8000/docs
echo   Close this window to stop the backend.
echo ============================================
venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
