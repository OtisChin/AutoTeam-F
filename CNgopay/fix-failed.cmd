@echo off
REM Recover FAILED slots back to WALLET_READY (only if wallet+token still alive and error is "no money was charged" type).
REM Usage:
REM   fix-failed.cmd                  - check all slots
REM   fix-failed.cmd -slot slot-02    - check one slot
cd /d "%~dp0"
pool.exe -config config.json -mode fix-failed %*
