from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        "src/__pycache__/app.pyc",
        "data/news.sqlite",
        "data/news.sqlite-wal",
        "data/stock_watch_details.json",
        "data/browser-profile/state.json",
        "data/playwright-libs/usr/lib/runtime.so",
        "public/assets/app.js",
        ".env.local",
    ],
)
def test_v71_runtime_artifacts_are_ignored_for_future_additions(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT_DIR,
        check=False,
    )

    assert result.returncode == 0, f"runtime artifact is not ignored: {path}"


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "config/sources.json",
        "data/game_metrics.csv.example",
    ],
)
def test_v71_source_and_templates_remain_trackable(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT_DIR,
        check=False,
    )

    assert result.returncode == 1, f"source or template was accidentally ignored: {path}"
