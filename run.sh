#!/usr/bin/env bash
# Levanta el servicio: ./run.sh  (PORT y DATA_DIR opcionales; carga .env si existe)
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export DATA_DIR="${DATA_DIR:-./data}"
exec python3 -m kipu serve --port "${PORT:-9000}"
