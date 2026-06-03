#!/bin/sh
# Recover FAILED slots back to WALLET_READY (only if wallet+token still alive
# and error is "no money was charged" type).
# Usage:
#   ./fix-failed.sh                  - check all slots
#   ./fix-failed.sh -slot slot-02    - check one slot
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
"$DIR/pool.sh" -config config.json -mode fix-failed "$@"
