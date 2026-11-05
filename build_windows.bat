@echo off
rem Avvia la build senza modificare la politica di esecuzione di PowerShell del sistema.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build_windows.ps1"
echo.
pause
