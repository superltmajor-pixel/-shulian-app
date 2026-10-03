@echo off
cd /d "%~dp0"
echo ============================================
echo   Repacking Shulian.exe ...
echo   (run this after you change web/ or backend)
echo ============================================
venv\Scripts\python.exe -m PyInstaller --noconfirm shulian.spec
echo.
echo Done. Output file: dist\Shulian.exe
pause
