#!/bin/bash
set -e

# Clean up stale Xvfb lock and start virtual display for Playwright.
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1280x800x24 &
export DISPLAY=:99

# Ensure persisted data directories exist and are writable.
mkdir -p /app/data /app/data/auths /app/data/screenshots
chmod -R 777 /app/data

# Persist runtime files under /app/data.
for f in .env accounts.json state.json; do
    [ -f "/app/data/$f" ] || touch "/app/data/$f"
    rm -f "/app/$f"
    ln -s "/app/data/$f" "/app/$f"
done

for d in auths screenshots; do
    rm -rf "/app/$d"
    ln -s "/app/data/$d" "/app/$d"
done

exec uv run autoteam "$@"
