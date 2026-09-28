@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-dev.ps1" %*
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
  echo.
  echo Stop launcher exited with code %EXITCODE%.
  pause
)

exit /b %EXITCODE%
