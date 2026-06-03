#!/bin/sh
# Diagnose linking by stopping right after validate-pin (no charge / no money / no token consumed).
# After it finishes run: ./linkedapps.sh   to see if OpenAI link is really established.
# Usage:
#   ./link-only.sh                  - test all WALLET_READY slots
#   ./link-only.sh -slot slot-01    - test one slot
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
"$DIR/pool.sh" -config config.json -mode link-only "$@"
