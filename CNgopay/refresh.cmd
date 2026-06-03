@echo off
REM Refresh access/refresh tokens for all slots (no OTP, no SMS).
REM Usage:
REM   refresh.cmd                  - refresh all slots
REM   refresh.cmd -slot slot-01    - refresh one slot
cd /d "%~dp0"
pool.exe -config config.json -mode refresh %*
