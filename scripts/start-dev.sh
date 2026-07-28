#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
API_PORT="${API_PORT:-5173}"
WEB_PORT="${WEB_PORT:-5174}"
VENV_DIR="${VENV_DIR:-.venv}"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to run the React frontend but was not found."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to run the FastAPI backend but was not found."
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

echo "Installing frontend dependencies..."
npm install

echo "Installing backend dependencies..."
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt

cleanup() {
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" 2>/dev/null; then
    echo
    echo "Stopping backend..."
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo
echo "Starting backend: http://localhost:${API_PORT}"
"$PYTHON" -m uvicorn src.app:app --host "$HOST" --port "$API_PORT" --reload --reload-dir src &
API_PID="$!"

sleep 1
if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "Backend failed to start."
  wait "$API_PID"
fi

echo "Starting frontend: http://localhost:${WEB_PORT}"
echo
echo "Open: http://localhost:${WEB_PORT}"
echo "Press Ctrl+C to stop frontend and backend."
echo

VITE_API_TARGET="http://127.0.0.1:${API_PORT}" npm run dev -- --host "$HOST" --port "$WEB_PORT"
