from __future__ import annotations

import unittest
from unittest.mock import patch

from src.stock_research import build_portfolio_exposure_notice, build_stock_research_snapshot
from src.watchlist_service import fetch_stock_detail_sync, fetch_stock_watchlist_sync


class StockResearchSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stock = {
            "id": "a-603816",
            "market": "a_share",
            "marketLabel": "A股",
            "symbol": "603816",
            "name": "顾家家居",
            "quoteUrl": "https://quote.eastmoney.com/sh603816.html",
            "source": "腾讯行情",
            "sourceUrl": "https://qt.gtimg.cn/q=sh603816",
            "fieldSources": {
                "marketCap": {
                    "source": "腾讯行情",
                    "sourceUrl": "https://qt.gtimg.cn/q=sh603816",
                    "method": "derived",
                    "formula": "腾讯行情市值字段 × 100,000,000（按市场报价币种）",
                }
            },
            "updatedAt": "2026-07-25T07:00:00+00:00",
            "price": 23.5,
            "amount": 310_000_000,
            "marketCap": 19_575_000_000,
            "floatMarketCap": 19_442_000_000,
            "turnoverRate": 1.2,
            "pe": 12.3,
            "pb": 1.97,
        }
        self.sections = {
            "capitalFlow": {
                "method": "proxy",
                "kind": "price_pressure_proxy",
                "source": "Yahoo Finance",
                "note": "成交额价格压力代理，不是主力净流入。",
                "items": [{"date": "2026-07-25", "pricePressureProxy": 10, "method": "proxy"}],
            },
            "ratings": {
                "source": "东方财富研报",
                "items": [{"date": "2026-07-24", "rating": "增持", "url": "https://example.test/rating"}],
            },
            "announcements": {
                "source": "东方财富公告",
                "items": [{"publishedAt": "2026-07-23T00:00:00+00:00", "title": "董事会公告", "url": "https://example.test/notice"}],
            },
            "news": {"source": "Google News", "items": []},
            "shortInterest": {"source": "", "items": []},
            "fundHoldings": {"source": "", "items": []},
            "shareholders": {"source": "", "items": []},
            "shareholderDistribution": {"source": "", "items": []},
        }

    def test_research_checklist_marks_missing_fundamentals_instead_of_inferring_them(self) -> None:
        snapshot = build_stock_research_snapshot(
            self.stock,
            self.sections,
            generated_at="2026-07-26T00:00:00+00:00",
        )

        checklist = {item["id"]: item for item in snapshot["checklist"]}
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(checklist["fundamentals"]["status"], "unavailable")
        self.assertIn("free_cash_flow", checklist["fundamentals"]["missingMetricIds"])
        self.assertEqual(checklist["capital_flow"]["method"], "proxy")
        self.assertEqual(checklist["capital_flow"]["status"], "partial")

        metrics = {item["id"]: item for item in snapshot["valuationMetrics"]}
        self.assertEqual(metrics["market_cap"]["quality"]["method"], "derived")
        self.assertEqual(metrics["market_cap"]["quality"]["sourceUrl"], self.stock["sourceUrl"])
        self.assertEqual(metrics["pe"]["quality"]["status"], "partial")
        self.assertEqual(metrics["pb"]["quality"]["value"], 1.97)

    def test_unavailable_us_pb_is_preserved_as_unknown(self) -> None:
        stock = {**self.stock, "market": "us", "marketLabel": "美股", "symbol": "AAPL", "pb": None}
        snapshot = build_stock_research_snapshot(stock, {}, generated_at="2026-07-26T00:00:00+00:00")
        metrics = {item["id"]: item for item in snapshot["valuationMetrics"]}

        self.assertIsNone(metrics["pb"]["quality"]["value"])
        self.assertEqual(metrics["pb"]["quality"]["status"], "unavailable")

    def test_observed_capital_flow_without_source_link_is_partial(self) -> None:
        sections = {
            **self.sections,
            "capitalFlow": {
                "method": "observed",
                "source": "公开资金流",
                "items": [{"date": "2026-07-25", "mainNetInflow": 100}],
            },
        }
        snapshot = build_stock_research_snapshot(
            self.stock,
            sections,
            generated_at="2026-07-26T00:00:00+00:00",
        )
        capital_flow = next(item for item in snapshot["checklist"] if item["id"] == "capital_flow")

        self.assertEqual(capital_flow["status"], "partial")
        self.assertIn("缺少可点击来源", "；".join(capital_flow["qualityWarnings"]))

    def test_watchlist_without_positions_never_reports_portfolio_weights(self) -> None:
        notice = build_portfolio_exposure_notice(
            [
                {"market": "a_share", "marketLabel": "A股"},
                {"market": "a_share", "marketLabel": "A股"},
                {"market": "hk", "marketLabel": "港股"},
            ]
        )

        self.assertEqual(notice["status"], "unavailable")
        self.assertEqual(notice["basis"], "watchlist_only")
        self.assertEqual(notice["composition"], [{"market": "a_share", "label": "A股", "count": 2}, {"market": "hk", "label": "港股", "count": 1}])
        self.assertNotIn("weights", notice)


class StockResearchIntegrationTests(unittest.TestCase):
    def test_stock_detail_and_watchlist_expose_additive_research_contracts(self) -> None:
        configured = [{"id": "a-603816", "market": "a_share", "symbol": "603816", "name": "顾家家居", "secid": "1.603816"}]
        quote = {
            "price": 23.5,
            "amount": 310_000_000,
            "marketCap": 19_575_000_000,
            "floatMarketCap": 19_442_000_000,
            "turnoverRate": 1.2,
            "pe": 12.3,
            "pb": 1.97,
            "updatedAt": "2026-07-25T07:00:00+00:00",
            "source": "腾讯行情",
        }
        with (
            patch("src.watchlist_service.load_watchlist_config", return_value=configured),
            patch("src.watchlist_service.fetch_quotes_sync", return_value={"a-603816": quote}),
            patch("src.watchlist_service.safe_section", return_value={"source": "", "items": []}),
            patch("src.watchlist_service.detail_cache_meta", return_value={}),
        ):
            detail = fetch_stock_detail_sync("a-603816")
            watchlist = fetch_stock_watchlist_sync()

        self.assertEqual(detail["research"]["schemaVersion"], 1)
        self.assertEqual(watchlist["portfolioExposure"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
