@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-local.ps1" %*
exit /b %ERRORLEVEL%
