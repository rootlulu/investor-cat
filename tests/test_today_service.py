from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from src.today_service import build_today_dashboard, get_today


NOW = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)


def sample_payloads() -> dict[str, dict]:
    return {
        "stocks": {
            "generatedAt": "2026-07-26T07:55:00+00:00",
            "hasData": True,
            "errors": [],
            "markets": [
                {
                    "id": "a_share",
                    "name": "A股",
                    "dataTimestamp": "2026-07-26T07:30:00+00:00",
                    "sourceUrl": "https://example.com/market",
                    "indices": [
                        {"symbol": "000001", "name": "上证指数", "changePct": 1.2},
                        {"symbol": "399006", "name": "创业板指", "changePct": -2.6},
                    ],
                }
            ],
            "marginalSignals": {
                "cards": [
                    {
                        "id": "breadth",
                        "title": "市场扩散",
                        "status": "ok",
                        "dataTimestamp": "2026-07-26",
                        "sourceUrl": "https://example.com/breadth",
                        "metrics": [{"label": "上涨占比", "value": 41.5, "format": "pct"}],
                    }
                ]
            },
        },
        "commodities": {
            "generatedAt": "2026-07-26T07:50:00+00:00",
            "hasData": True,
            "errors": ["一个库存来源超时"],
            "qualitySummary": {"invalid": 1, "estimated": 0, "proxy": 0},
            "items": [
                {
                    "id": "copper",
                    "name": "铜",
                    "sector": "有色金属",
                    "domesticFutureChangePct": 3.4,
                    "domesticFutureDate": "2026-07-26",
                    "basisQuality": {
                        "sourceUrl": "https://example.com/copper",
                        "status": "ok",
                    },
                    "inventoryChangePct": -1.1,
                    "inventoryDate": "2026-07-25",
                },
                {
                    "id": "glass",
                    "name": "玻璃",
                    "basis": None,
                    "basisQuality": {
                        "sourceUrl": "https://example.com/glass",
                        "status": "invalid",
                        "qualityFlags": ["现货与期货计价维度不可换算"],
                    },
                },
            ],
        },
        "energy": {
            "generatedAt": "2026-07-26T07:45:00+00:00",
            "hasData": True,
            "errors": [],
            "qualitySummary": {"estimated": 1, "invalid": 0},
            "summary": {"estimatedPointCount": 1},
            "rows": [
                {
                    "id": "raw_coal",
                    "name": "原煤产量",
                    "value": 100,
                    "unit": "万吨",
                    "yoy": 4.2,
                    "period": "2026-06",
                    "sourceUrl": "https://example.com/energy",
                    "quality": {"method": "observed", "status": "ok"},
                },
                {
                    "id": "power_estimate",
                    "name": "估算发电量",
                    "value": 120,
                    "unit": "亿千瓦时",
                    "yoy": 9.9,
                    "period": "2026-07",
                    "sourceUrl": "https://example.com/estimate",
                    "quality": {"method": "estimated", "status": "partial"},
                },
            ],
        },
        "ai_news": {
            "generatedAt": "2026-07-26T07:40:00+00:00",
            "hasData": True,
            "errors": [],
            "items": [
                {
                    "id": "ai-1",
                    "title": "模型公司发布新推理系统",
                    "category": "models",
                    "categoryLabel": "大模型",
                    "publishedAt": "2026-07-26T06:00:00+00:00",
                    "url": "https://example.com/ai",
                    "source": "Example News",
                }
            ],
        },
    }


class TodayDashboardTests(unittest.TestCase):
    def test_v124_all_unavailable_sources_report_no_data(self) -> None:
        dashboard = build_today_dashboard(
            stocks=None,
            commodities=None,
            energy=None,
            ai_news=None,
            generated_at=NOW,
        )

        self.assertEqual({item["status"] for item in dashboard["health"]}, {"unavailable"})
        self.assertFalse(dashboard["hasData"])

    def test_orders_observed_changes_by_absolute_magnitude_with_quality_metadata(self) -> None:
        dashboard = build_today_dashboard(**sample_payloads(), generated_at=NOW)

        self.assertEqual(dashboard["changes"][0]["label"], "原煤产量同比")
        self.assertEqual(dashboard["changes"][1]["label"], "铜国内期货")
        self.assertEqual(dashboard["changes"][2]["label"], "创业板指")
        self.assertTrue(all(item["quality"]["sourceUrl"] for item in dashboard["changes"]))
        self.assertTrue(all(item["quality"]["asOf"] for item in dashboard["changes"]))
        self.assertTrue(all(item["quality"]["method"] != "estimated" for item in dashboard["changes"]))

    def test_estimated_energy_is_excluded_from_changes_and_reported_as_risk(self) -> None:
        dashboard = build_today_dashboard(**sample_payloads(), generated_at=NOW)

        change_ids = {item["id"] for item in dashboard["changes"]}
        self.assertNotIn("energy-power_estimate", change_ids)
        self.assertTrue(any(item["id"] == "energy-estimated" for item in dashboard["risks"]))

    def test_health_distinguishes_partial_stale_and_unavailable_sources(self) -> None:
        payloads = sample_payloads()
        payloads["stocks"]["stale"] = True
        payloads["energy"] = None
        dashboard = build_today_dashboard(
            **payloads,
            failures={"energy": "timeout"},
            generated_at=NOW,
        )

        health = {item["id"]: item for item in dashboard["health"]}
        self.assertEqual(health["stocks"]["status"], "stale")
        self.assertEqual(health["commodities"]["status"], "partial")
        self.assertEqual(health["energy"]["status"], "error")
        self.assertIn("timeout", health["energy"]["note"])
        self.assertGreaterEqual(dashboard["qualitySummary"]["problemCount"], dashboard["healthSummary"]["problemCount"])
        self.assertGreaterEqual(dashboard["qualitySummary"]["partial"], 1)
        self.assertGreaterEqual(dashboard["qualitySummary"]["error"], 1)

    def test_invalid_basis_and_ai_news_are_kept_in_their_correct_sections(self) -> None:
        dashboard = build_today_dashboard(**sample_payloads(), generated_at=NOW)

        self.assertTrue(any(item["id"] == "commodity-basis-invalid" for item in dashboard["risks"]))
        self.assertEqual(dashboard["aiFocus"][0]["title"], "模型公司发布新推理系统")
        self.assertEqual(dashboard["aiFocus"][0]["quality"]["method"], "observed")
        self.assertTrue(dashboard["impacts"])
        self.assertTrue(all(item["method"] == "derived" for item in dashboard["impacts"]))

    def test_optional_invalid_basis_is_safely_blocked_without_marking_domain_failed(self) -> None:
        payloads = sample_payloads()
        payloads["commodities"]["errors"] = []

        dashboard = build_today_dashboard(**payloads, generated_at=NOW)

        commodity_health = next(item for item in dashboard["health"] if item["id"] == "commodities")
        self.assertEqual(commodity_health["status"], "ok")
        self.assertIn("1 项基差已安全禁算", commodity_health["note"])
        self.assertTrue(any(item["id"] == "commodity-basis-invalid" for item in dashboard["risks"]))

    def test_health_separates_successful_fallbacks_from_stale_subcomponents(self) -> None:
        payloads = sample_payloads()
        payloads["stocks"]["warnings"] = ["东方财富断连，已切换同花顺备用源"]
        payloads["stocks"]["qualitySummary"] = {"stale": 1}

        dashboard = build_today_dashboard(**payloads, generated_at=NOW)

        stock_health = next(item for item in dashboard["health"] if item["id"] == "stocks")
        self.assertEqual(stock_health["status"], "partial")
        self.assertIn("1 项来源已切换备用", stock_health["note"])
        self.assertIn("1 项子模块陈旧", stock_health["note"])
        self.assertEqual(stock_health["diagnostics"]["errors"], [])
        self.assertEqual(stock_health["diagnostics"]["warnings"], payloads["stocks"]["warnings"])


class TodaySnapshotLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_start_snapshot_timeout_degrades_one_domain_without_blocking_dashboard(self) -> None:
        payloads = sample_payloads()

        async def blocked_energy_snapshot() -> dict:
            await asyncio.sleep(1)
            return payloads["energy"]

        with (
            patch("src.today_service.TODAY_SOURCE_TIMEOUT_SECONDS", 0.01),
            patch("src.today_service.read_stock_snapshot", AsyncMock(return_value=payloads["stocks"])),
            patch("src.today_service.read_commodity_snapshot", AsyncMock(return_value=payloads["commodities"])),
            patch("src.today_service.read_energy_snapshot", AsyncMock(side_effect=blocked_energy_snapshot)),
            patch("src.today_service.read_ai_news_snapshot", AsyncMock(return_value=payloads["ai_news"])),
        ):
            dashboard = await asyncio.wait_for(get_today(), timeout=0.2)

        health = {item["id"]: item for item in dashboard["health"]}
        self.assertEqual(health["energy"]["status"], "error")
        self.assertIn("快照读取超时", health["energy"]["note"])
        self.assertTrue(any(risk["id"] == "source-energy" for risk in dashboard["risks"]))
        self.assertTrue(dashboard["changes"])


if __name__ == "__main__":
    unittest.main()
