@echo off
REM Usage: codex-st.cmd [N]    N = serial run count (default 1)
REM Browser mode sentinel (stable but slower, requires playwright chromium).
REM
REM EDIT THE TWO PROXY URLS BELOW TO MATCH YOUR PROXY ACCOUNT (same format as codex.cmd).

setlocal
set N=%1
if "%N%"=="" set N=1
set SENTINEL_BROWSER_PROXY=http://USERNAME-region-US:PASSWORD@HOST:PORT
cd /d "%~dp0codex_register"
powershell -NoProfile -Command "for ($i = 1; $i -le %N%; $i++) { Write-Host ''; Write-Host ('========== [batch] ' + $i + ' / %N% ==========') -Foreground Cyan; & npm.cmd run dev -- --codex-cpa --st --gp-token-out ../pool_tokens.txt --probe-trial-jp 'socks5://USERNAME-region-JP:PASSWORD@HOST:PORT' }"
endlocal
