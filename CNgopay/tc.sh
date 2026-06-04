#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$arch" in
  x86_64) arch="amd64" ;;
  arm64|aarch64) arch="arm64" ;;
esac

bin="./pool-${os}-${arch}"
if [ ! -x "$bin" ]; then
  bin="./pool"
fi

exec "$bin" -config config.json -mode tc "$@"
