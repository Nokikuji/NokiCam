@echo off
:: NokiCam Installer -- launches the graphical setup window
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_windows.ps1"
if %errorlevel% neq 0 pause
