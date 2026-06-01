#!/bin/sh
# Auto-detect platform and pick the right pool binary
DIR="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -sm)" in
    "Linux x86_64")     BIN="$DIR/pool-linux-x64" ;;
    "Darwin arm64")     BIN="$DIR/pool-mac-arm64" ;;
    "Darwin x86_64")    BIN="$DIR/pool-mac-intel" ;;
    *) echo "Unsupported platform: $(uname -sm)"; exit 1 ;;
esac
chmod +x "$BIN" 2>/dev/null
exec "$BIN" "$@"
