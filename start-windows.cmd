@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-test-windows.ps1"
if errorlevel 1 (
  echo.
  echo Windows service startup failed. Review the message above and logs under .tmp\windows-dev\logs.
  pause
)
