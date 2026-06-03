@echo off
REM Diagnose linking by stopping right after validate-pin (no charge / no money / no token consumed).
REM After it finishes run: linkedapps.cmd     to see if OpenAI link is really established.
REM
REM Usage:
REM   link-only.cmd                  - test all WALLET_READY slots
REM   link-only.cmd -slot slot-01    - test one slot
cd /d "%~dp0"
pool.exe -config config.json -mode link-only %*
