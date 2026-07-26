from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.watchlist_service import (
    DETAIL_CACHE_VERSION,
    SINA_CAPITAL_FLOW_API,
    build_yahoo_capital_flow_proxy_result,
    fetch_capital_flow_sync,
    parse_tencent_quote,
    parse_tencent_quote_time,
    parse_yahoo_capital_flow_proxy_rows,
    read_cached_detail_sync,
)


class WatchlistQuoteTimeTests(unittest.TestCase):
    def test_tencent_a_share_time_is_local_then_converted_to_utc(self) -> None:
        self.assertEqual(parse_tencent_quote_time("2026/07/25 15:00:00", "a_share"), "2026-07-25T07:00:00+00:00")

    def test_tencent_us_time_honors_daylight_saving(self) -> None:
        self.assertEqual(parse_tencent_quote_time("2026-07-24 16:00:00", "us"), "2026-07-24T20:00:00+00:00")

    def test_tencent_valuation_and_market_cap_fields_are_market_specific(self) -> None:
        a_share = self._quote_parts({44: "194.42", 45: "195.75", 46: "1.97", 59: "37"})
        hk = self._quote_parts({44: "204.9218", 45: "204.9218", 46: "XD INC", 58: "5.69", 59: "0.33"})
        us = self._quote_parts({44: "48881.62430", 45: "48911.83295", 46: "Apple Inc.", 59: "-10.48"})

        a_quote = parse_tencent_quote(a_share, {"market": "a_share", "symbol": "603816"})
        hk_quote = parse_tencent_quote(hk, {"market": "hk", "symbol": "02400"})
        us_quote = parse_tencent_quote(us, {"market": "us", "symbol": "AAPL"})

        self.assertEqual(a_quote["pb"], 1.97)
        self.assertEqual(hk_quote["pb"], 5.69)
        self.assertIsNone(us_quote["pb"])
        self.assertEqual(a_quote["marketCap"], 19_575_000_000)
        self.assertEqual(a_quote["floatMarketCap"], 19_442_000_000)
        self.assertEqual(us_quote["marketCap"], 4_891_183_295_000)
        self.assertEqual(us_quote["floatMarketCap"], 4_888_162_430_000)

    def test_old_detail_cache_with_wrong_valuation_mapping_is_rejected(self) -> None:
        self.assertEqual(DETAIL_CACHE_VERSION, 3)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "stock_watch_details.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "details": {
                            "a-603816": {
                                "cachedAt": time.time(),
                                "cacheVersion": 2,
                                "data": {"stock": {"pb": 37}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("src.watchlist_service.WATCHLIST_DETAIL_CACHE_PATH", cache_path):
                self.assertIsNone(read_cached_detail_sync("a-603816"))

    @staticmethod
    def _quote_parts(overrides: dict[int, str]) -> str:
        parts = [""] * 70
        parts[1] = "测试公司"
        parts[3] = "10"
        parts[30] = "2026/07/25 15:00:00"
        parts[36] = "100"
        parts[37] = "200"
        parts[39] = "12"
        for index, value in overrides.items():
            parts[index] = value
        return "~".join(parts)


class WatchlistCapitalFlowProxyTests(unittest.TestCase):
    def test_yahoo_proxy_never_populates_observed_main_flow_fields(self) -> None:
        rows = parse_yahoo_capital_flow_proxy_rows(
            {
                "timestamp": [1_753_392_000, 1_753_478_400],
                "meta": {"currency": "HKD"},
                "indicators": {"quote": [{"close": [10, 11], "volume": [100, 200]}]},
            },
            15,
        )

        latest = rows[-1]
        self.assertIsNone(latest["mainNetInflow"])
        self.assertIsNone(latest["mainNetRatio"])
        self.assertEqual(latest["pricePressureProxy"], 220)
        self.assertEqual(latest["pricePressureRatio"], 10)
        self.assertEqual(latest["method"], "proxy")
        self.assertIn("成交额", latest["formula"])

    def test_yahoo_proxy_section_is_explicitly_typed(self) -> None:
        with patch(
            "src.watchlist_service.fetch_yahoo_capital_flow_proxy_items",
            return_value=[{"currency": "HKD", "pricePressureProxy": 10, "method": "proxy"}],
        ):
            result = build_yahoo_capital_flow_proxy_result({"symbol": "9988", "market": "hk"}, 15)

        self.assertEqual(result["method"], "proxy")
        self.assertEqual(result["kind"], "price_pressure_proxy")
        self.assertIn("不是主力净流入", result["note"])
        self.assertEqual(result["sourceUrl"], "https://finance.yahoo.com/quote/9988.HK/history")

    def test_observed_sina_capital_flow_exposes_clickable_source(self) -> None:
        with patch(
            "src.watchlist_service.fetch_sina_capital_flow_items",
            return_value=[{"date": "2026-07-25", "mainNetInflow": 100}],
        ):
            result = fetch_capital_flow_sync({"symbol": "603816", "market": "a_share"})

        self.assertEqual(result["sourceUrl"], f"{SINA_CAPITAL_FLOW_API}?daima=sh603816")


if __name__ == "__main__":
    unittest.main()
