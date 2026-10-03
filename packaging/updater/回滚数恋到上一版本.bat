@echo off
chcp 65001 >nul
title 数恋 APP 回滚

powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0ShulianUpdater.ps1" ^
  -Rollback ^
  -AppDir "%~dp0dist"

if errorlevel 1 (
  echo.
  echo 回滚失败，请保留窗口内容并打开数恋诊断中心。
) else (
  echo.
  echo 已恢复上一版本。
)
pause
