@echo off
REM Usage: codex.cmd [N]    N = serial run count (default 1)
REM VM mode sentinel (fast, may occasionally hit invalid_auth_step). Use codex-st.cmd if unstable.
REM
REM EDIT THE TWO PROXY URLS BELOW TO MATCH YOUR PROXY ACCOUNT:
REM   - SENTINEL_BROWSER_PROXY: http(s) proxy for playwright (must use http://, not socks5://)
REM   - --probe-trial-jp:        japan proxy for trial probe (socks5:// supported)

setlocal
set N=%1
if "%N%"=="" set N=1
set SENTINEL_BROWSER_PROXY=http://USERNAME-region-US:PASSWORD@HOST:PORT
cd /d "%~dp0codex_register"
powershell -NoProfile -Command "for ($i = 1; $i -le %N%; $i++) { Write-Host ''; Write-Host ('========== [batch] ' + $i + ' / %N% ==========') -Foreground Cyan; & npm.cmd run dev -- --codex-cpa --gp-token-out ../pool_tokens.txt --probe-trial-jp 'socks5://USERNAME-region-JP:PASSWORD@HOST:PORT' }"
endlocal
