@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-chunks.ps1" %*
if errorlevel 1 exit /b %errorlevel%
