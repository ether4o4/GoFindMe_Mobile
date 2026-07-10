#!/usr/bin/env bash
# GoFindMe launcher. Reads .env if present, then starts the server.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

BIND="${GOFINDME_BIND:-127.0.0.1}"
PORT="${GOFINDME_PORT:-8000}"

echo "GoFindMe → http://${BIND}:${PORT}  (vault mode: ${GOFINDME_VAULT_MODE:-encrypted})"
if [ "$BIND" = "0.0.0.0" ]; then
  echo "WARNING: binding to 0.0.0.0 exposes the dashboard to your network."
  echo "         Only do this behind Tailscale/WireGuard or a TLS reverse proxy with auth."
fi

exec uvicorn app.main:app --host "$BIND" --port "$PORT" "$@"
