#!/bin/sh
# List GoPay linked merchants for all slots (read-only, no SMS).
# Usage:
#   ./linkedapps.sh                  - check all slots
#   ./linkedapps.sh -slot slot-01    - check one slot
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
"$DIR/pool.sh" -config config.json -mode linkedapps "$@"
