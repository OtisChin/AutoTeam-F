@echo off
REM List GoPay linked merchants for all slots (read-only, no SMS).
REM Usage:
REM   linkedapps.cmd                  - check all slots
REM   linkedapps.cmd -slot slot-01    - check one slot
cd /d "%~dp0"
pool.exe -config config.json -mode linkedapps %*
