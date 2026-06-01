#!/bin/sh
# Run this once after extracting on macOS/Linux.
# Makes all scripts and binaries executable.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
chmod +x pool-linux-x64 pool-mac-intel pool-mac-arm64 2>/dev/null
chmod +x pool.sh reg.sh harvest.sh rebind.sh status.sh codex.sh codex-st.sh setup.sh 2>/dev/null
echo "OK. Now edit:"
echo "  - config.json (proxy / hero / cpa)"
echo "  - codex_register/config.json (proxy / hero / cpa)"
echo "  - codex.sh / codex-st.sh (proxy URLs)"
echo "Then: cd codex_register && npm install"
