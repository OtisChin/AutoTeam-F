#!/bin/sh
# Usage: ./codex-st.sh [N]    N = serial run count (default 1)
# Browser mode sentinel (stable, slower).
#
# EDIT THE TWO PROXY URLS BELOW TO MATCH YOUR PROXY ACCOUNT.

DIR="$(cd "$(dirname "$0")" && pwd)"
N="${1:-1}"
export SENTINEL_BROWSER_PROXY="http://USERNAME-region-US:PASSWORD@HOST:PORT"

cd "$DIR/codex_register" || exit 1
i=1
while [ "$i" -le "$N" ]; do
    echo
    echo "========== [batch] $i / $N =========="
    npm run dev -- --codex-cpa --st --gp-token-out ../pool_tokens.txt --probe-trial-jp 'socks5://USERNAME-region-JP:PASSWORD@HOST:PORT'
    i=$((i + 1))
done
