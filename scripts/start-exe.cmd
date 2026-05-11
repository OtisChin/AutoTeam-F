@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-exe.ps1" %*
exit /b %ERRORLEVEL%
