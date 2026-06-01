@echo off
setlocal
set N=%1
if "%N%"=="" set N=3
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-pool.ps1" -N %N% -ST
endlocal
