@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
echo ============================================
echo   Legacy one-file Shulian build
echo   Formal releases use shulian-onedir.spec.
echo ============================================
venv\Scripts\python.exe -m PyInstaller --noconfirm packaging\legacy\shulian-onefile.spec
echo.
echo Done. Check the dist directory for the legacy artifact.
pause
