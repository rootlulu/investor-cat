import unittest
import asyncio
import time
from unittest.mock import AsyncMock, patch

from src.background_refresh import (
    REFRESH_STATE,
    STARTUP_REFRESH_KINDS,
    execute_refresh,
    run_refresh,
    start_startup_refreshes,
    startup_refresh_slot,
)


class StartupRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_forces_every_registered_page_to_refresh_once(self) -> None:
        with patch("src.background_refresh.start_background_refresh", new_callable=AsyncMock) as start_refresh:
            await start_startup_refreshes()

        self.assertEqual(STARTUP_REFRESH_KINDS, tuple(REFRESH_STATE))
        self.assertEqual(start_refresh.await_count, len(REFRESH_STATE))
        self.assertEqual(
            start_refresh.await_args_list,
            [unittest.mock.call(kind, "startup", force=True) for kind in REFRESH_STATE],
        )

    async def test_startup_refreshes_include_every_data_page(self) -> None:
        self.assertEqual(
            STARTUP_REFRESH_KINDS,
            (
                "news",
                "ai-news",
                "ai-projects",
                "stocks",
                "commodities",
                "energy",
                "consumption",
                "macro",
                "games",
                "games-region",
                "xueqiu",
            ),
        )

    async def test_startup_gate_limits_active_jobs_to_two(self) -> None:
        active = 0
        max_active = 0
        release = asyncio.Event()

        async def worker() -> None:
            nonlocal active, max_active
            async with startup_refresh_slot():
                active += 1
                max_active = max(max_active, active)
                await release.wait()
                active -= 1

        with patch("src.background_refresh.STARTUP_STAGGER_SECONDS", 0):
            tasks = [asyncio.create_task(worker()) for _index in range(5)]
            await asyncio.sleep(0.05)
            self.assertEqual(active, 2)
            release.set()
            await asyncio.gather(*tasks)

        self.assertEqual(max_active, 2)

    async def test_startup_gate_staggers_job_starts(self) -> None:
        starts: list[float] = []

        async def worker() -> None:
            async with startup_refresh_slot():
                starts.append(time.monotonic())

        with patch("src.background_refresh.STARTUP_STAGGER_SECONDS", 0.03):
            await asyncio.gather(*(worker() for _index in range(3)))

        self.assertEqual(len(starts), 3)
        self.assertGreaterEqual(starts[1] - starts[0], 0.02)
        self.assertGreaterEqual(starts[2] - starts[1], 0.02)

    async def test_games_region_refresh_uses_global_region_and_force(self) -> None:
        payload = {"generatedAt": "now", "games": []}
        with patch(
            "src.background_refresh.get_region_games",
            new=AsyncMock(return_value=payload),
        ) as get_region_games:
            result = await execute_refresh("games-region", "startup", True)

        self.assertEqual(result, payload)
        get_region_games.assert_awaited_once_with(
            cc="global",
            refresh=True,
            allow_stale=False,
            force=True,
        )

    async def test_v123_empty_games_region_refresh_is_not_marked_done(self) -> None:
        state = REFRESH_STATE["games-region"]
        original = dict(state)
        state.update({"runId": 123, "version": 7})
        payload = {
            "generatedAt": "now",
            "games": [],
            "rankings": {
                "live": {"status": "unavailable"},
                "weekly": {"status": "unavailable"},
                "monthly": {"status": "unavailable"},
            },
            "errors": ["all sources failed"],
            "cached": False,
            "stale": False,
            "throttled": False,
        }
        try:
            with (
                patch("src.background_refresh.STARTUP_STAGGER_SECONDS", 0),
                patch("src.background_refresh.execute_refresh", new=AsyncMock(return_value=payload)),
            ):
                await run_refresh("games-region", "startup", 123, force=True)

            self.assertEqual(state["status"], "error")
            self.assertFalse(state["refreshed"])
            self.assertEqual(state["version"], 7)
        finally:
            state.clear()
            state.update(original)


if __name__ == "__main__":
    unittest.main()
