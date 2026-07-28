"""Run the real FastAPI app for local smoke tests without external startup refreshes."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock

import uvicorn

from src import app as app_module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5189)
    args = parser.parse_args()
    app_module.start_startup_refreshes = AsyncMock()
    uvicorn.run(app_module.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
