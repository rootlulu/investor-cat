from __future__ import annotations

import unittest

from src.investment_quality import (
    INVESTMENT_QUALITY_SCHEMA_VERSION,
    build_metric_quality,
    quality_summary,
)


class InvestmentQualityTests(unittest.TestCase):
    def test_builds_complete_observed_metric_metadata(self) -> None:
        quality = build_metric_quality(
            value=12.5,
            unit="亿元",
            as_of="2026-07-25",
            source_url="https://example.com/source",
            definition="最近交易日融资净买入",
            fetched_at="2026-07-26T08:00:00Z",
        )

        self.assertEqual(quality["schemaVersion"], INVESTMENT_QUALITY_SCHEMA_VERSION)
        self.assertEqual(quality["method"], "observed")
        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["qualityFlags"], [])
        self.assertEqual(quality["value"], 12.5)

    def test_missing_value_is_unavailable_not_zero(self) -> None:
        quality = build_metric_quality(
            value=None,
            unit="亿元",
            as_of="2026-07-25",
            source_url="https://example.com/source",
            definition="融资净买入",
        )

        self.assertIsNone(quality["value"])
        self.assertEqual(quality["status"], "unavailable")

    def test_proxy_requires_visible_explanation(self) -> None:
        with self.assertRaisesRegex(ValueError, "proxy.*formula"):
            build_metric_quality(
                value=1.2,
                unit="亿元",
                as_of="2026-07-25",
                source_url="https://example.com/source",
                definition="价格压力代理",
                method="proxy",
            )

    def test_rejects_unknown_method_or_status(self) -> None:
        common = {
            "value": 1,
            "unit": "点",
            "as_of": "2026-07-25",
            "source_url": "https://example.com/source",
            "definition": "测试指标",
        }
        with self.assertRaisesRegex(ValueError, "method"):
            build_metric_quality(**common, method="guessed")
        with self.assertRaisesRegex(ValueError, "status"):
            build_metric_quality(**common, status="fresh")

    def test_quality_summary_tolerates_legacy_payloads(self) -> None:
        summary = quality_summary(
            [
                {"value": 1},
                {"quality": {"status": "ok", "method": "observed"}},
                {"quality": {"status": "stale", "method": "estimated"}},
                {"quality": {"status": "invalid", "method": "derived"}},
            ]
        )

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["legacy"], 1)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual(summary["invalid"], 1)
        self.assertEqual(summary["estimated"], 1)


if __name__ == "__main__":
    unittest.main()
