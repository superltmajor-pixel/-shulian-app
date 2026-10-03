@echo off
cd /d "%~dp0"
echo ============================================
echo   Shulian Backend starting...  http://localhost:8000
echo   Close this black window = stop backend
echo ============================================
venv\Scripts\python.exe -m uvicorn main:app --port 8000
pause
