from __future__ import annotations

import unittest

from src.stock_service import (
    build_index_futures_signal,
    build_stock_quality_summary,
    merge_marginal_signals_with_previous,
    merge_markets_with_previous,
)


class IndexFuturesTrustTests(unittest.TestCase):
    def test_uses_notional_exposure_and_annualized_contract_basis(self) -> None:
        signal = build_index_futures_signal(
            [
                {"symbol": "IF", "instrumentId": "IF2607", "tradeDate": "2026-07-01", "close": 4040, "openInterest": 10, "previousOpenInterest": 8, "volume": 4},
                {"symbol": "IC", "instrumentId": "IC2607", "tradeDate": "2026-07-01", "close": 6060, "openInterest": 10, "previousOpenInterest": 9, "volume": 5},
            ],
            {
                "IF": {"date": "2026-07-01", "close": 4000},
                "IC": {"date": "2026-07-01", "close": 6000},
            },
        )

        contracts = {item["symbol"]: item for item in signal["contracts"]}
        self.assertEqual(contracts["IF"]["multiplier"], 300)
        self.assertEqual(contracts["IC"]["multiplier"], 200)
        self.assertEqual(contracts["IF"]["notionalExposure"], 12_000_000)
        self.assertEqual(contracts["IC"]["notionalExposure"], 12_000_000)
        self.assertGreater(contracts["IF"]["annualizedBasisPct"], contracts["IF"]["basisPct"])
        labels = [metric["label"] for metric in signal["metrics"]]
        self.assertIn("名义持仓合计", labels)
        self.assertNotIn("四合约平均基差", labels)
        self.assertNotIn("主力持仓合计", labels)


class StockLastKnownGoodTests(unittest.TestCase):
    def test_market_failure_retains_previous_component_as_stale(self) -> None:
        current = [{"id": "a_share", "marketCap": None, "indices": [], "note": "fetch failed"}]
        previous = [{"id": "a_share", "marketCap": 100, "indices": [{"symbol": "000001"}], "dataTimestamp": "2026-07-25"}]

        merged = merge_markets_with_previous(current, previous, "timeout")

        self.assertEqual(merged[0]["marketCap"], 100)
        self.assertEqual(merged[0]["status"], "stale")
        self.assertIn("timeout", merged[0]["staleReason"])

    def test_failed_signal_card_retains_previous_card_only(self) -> None:
        current = {"cards": [{"id": "funding", "status": "unavailable", "metrics": []}], "errors": ["timeout"], "notes": []}
        previous = {
            "cards": [
                {"id": "funding", "status": "ok", "metrics": [{"label": "FR007", "value": 1.5}]},
                {"id": "breadth", "status": "ok", "metrics": [{"label": "上涨", "value": 1000}]},
            ]
        }

        merged = merge_marginal_signals_with_previous(current, previous)

        cards = {card["id"]: card for card in merged["cards"]}
        self.assertEqual(cards["funding"]["metrics"][0]["value"], 1.5)
        self.assertEqual(cards["funding"]["status"], "stale")
        self.assertNotIn("breadth", cards)


class StockPageHealthTests(unittest.TestCase):
    def test_summarizes_market_and_signal_component_health(self) -> None:
        summary = build_stock_quality_summary(
            {
                "markets": [
                    {"id": "a_share", "marketCap": 100, "indices": [], "sourceUrl": "https://example.com/a"},
                    {"id": "hk", "marketCap": 80, "indices": [], "status": "stale", "sourceUrl": "https://example.com/hk"},
                    {"id": "us", "marketCap": None, "indices": []},
                ],
                "marginalSignals": {
                    "cards": [
                        {"id": "breadth", "status": "ok", "metrics": [{"value": 50}]},
                        {"id": "funding", "status": "unavailable", "metrics": []},
                    ]
                },
                "industryFinancingTrend": {"status": "stale", "dates": ["2026-07-25"]},
                "institutionIndustryAllocation": {"categories": [], "errors": ["timeout"]},
            }
        )

        self.assertEqual(summary["total"], 7)
        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["stale"], 2)
        self.assertEqual(summary["unavailable"], 2)
        self.assertEqual(summary["error"], 1)
        self.assertEqual(summary["problemCount"], 5)


if __name__ == "__main__":
    unittest.main()
