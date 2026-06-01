@echo off
cd /d "%~dp0"
pool.exe -config config.json -mode status %*
