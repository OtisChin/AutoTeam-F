#!/bin/sh
# Refresh access/refresh tokens for all slots (no OTP, no SMS).
# Usage:
#   ./refresh.sh                  - refresh all slots
#   ./refresh.sh -slot slot-01    - refresh one slot
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
"$DIR/pool.sh" -config config.json -mode refresh "$@"
