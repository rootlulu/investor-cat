#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5173}"
VENV_DIR="${VENV_DIR:-.venv}"
SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-0}"

if [ "$SKIP_FRONTEND_BUILD" != "1" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to build the React frontend but was not found."
    exit 1
  fi

  npm install
  npm run build
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found."
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  rm -rf "$VENV_DIR"
  if ! python3 -m venv --system-site-packages --without-pip "$VENV_DIR"; then
    echo
    echo "Failed to create virtual environment."
    echo "On Ubuntu, install the venv package first, then run this script again:"
    echo "  sudo apt install python3.14-venv"
    exit 1
  fi
fi

PYTHON="$VENV_DIR/bin/python"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt

exec "$PYTHON" -m uvicorn src.app:app --host "$HOST" --port "$PORT"
