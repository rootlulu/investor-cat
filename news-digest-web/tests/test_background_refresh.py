import unittest
from unittest.mock import AsyncMock, patch

from src.background_refresh import REFRESH_STATE, STARTUP_REFRESH_KINDS, start_startup_refreshes


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


if __name__ == "__main__":
    unittest.main()
