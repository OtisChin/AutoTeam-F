#!/bin/sh
# Show current bound phone + email for all slots (read-only).
# Compares state.json (expected) vs server (actual) to verify rebind.
# Usage:
#   ./profile.sh                  - check all slots
#   ./profile.sh -slot slot-01    - check one slot
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
"$DIR/pool.sh" -config config.json -mode profile "$@"
