from __future__ import annotations

import unittest

from src.app import app


class TodayRouteTests(unittest.TestCase):
    def test_today_api_and_page_routes_are_registered(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/today", paths)
        self.assertIn("/today", paths)


if __name__ == "__main__":
    unittest.main()
