@echo off
chcp 65001 >nul
echo WARNING: This exposes port 8000 to devices on your private LAN.
echo The API has no user authentication. Do not use this on public WiFi.
choice /M "Continue with a private-LAN-only firewall rule"
if errorlevel 2 exit /b 1
netsh advfirewall firewall delete rule name="Shulian 8000" >nul 2>&1
netsh advfirewall firewall add rule name="Shulian 8000" dir=in action=allow protocol=TCP localport=8000 profile=private remoteip=localsubnet
echo.
echo Done. The rule is limited to the local subnet on private networks.
echo To serve the LAN, you must also intentionally start uvicorn with --host 0.0.0.0.
pause
