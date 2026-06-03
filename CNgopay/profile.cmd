@echo off
REM Show current bound phone + email for all slots (read-only).
REM Compares state.json (expected) vs server (actual) — useful to verify rebind.
REM Usage:
REM   profile.cmd                  - check all slots
REM   profile.cmd -slot slot-01    - check one slot
cd /d "%~dp0"
pool.exe -config config.json -mode profile %*
