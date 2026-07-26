from __future__ import annotations

import inspect
import unittest

from src.energy_service import (
    build_fallback_history,
    build_summary,
    finalize_rows,
    get_energy,
    upgrade_energy_snapshot,
)


class EnergyObservationTests(unittest.TestCase):
    def test_additive_schema_upgrade_attaches_catalog_to_legacy_rows(self) -> None:
        legacy = {
            "schemaVersion": 4,
            "rows": [
                {
                    "id": "raw_coal",
                    "name": "原煤",
                    "category": "煤炭",
                    "unit": "万吨",
                    "period": "2026-06",
                    "sourceUrl": "https://example.com/nbs",
                    "history": [{"period": "2026-06", "value": 100}],
                }
            ],
        }

        upgraded = upgrade_energy_snapshot(legacy)

        self.assertEqual(upgraded["schemaVersion"], 5)
        self.assertEqual(upgraded["legacySchemaVersion"], 4)
        self.assertEqual(upgraded["rows"][0]["canonicalSeriesId"], "energy.cn.output.raw_coal.monthly")
        self.assertNotIn("canonicalSeriesId", legacy["rows"][0])

    def test_fallback_history_marks_observed_and_estimated_points(self) -> None:
        history = build_fallback_history(
            "raw_coal",
            [
                {"period": "2026-04", "periodLabel": "4月", "value": 100, "yoy": 2},
                {"period": "2026-05", "periodLabel": "5月", "value": 110, "yoy": 3},
            ],
        )

        observed = [point for point in history if point.get("period") in {"2026-04", "2026-05"}]
        estimated = [point for point in history if point.get("method") == "estimated"]
        self.assertTrue(observed)
        self.assertTrue(all(point.get("method") == "observed" for point in observed))
        self.assertTrue(estimated)
        self.assertTrue(all(point.get("formula") for point in estimated))

    def test_finalize_rows_never_synthesizes_ohlc_or_mom_from_estimates(self) -> None:
        rows = [
            {
                "id": "raw_coal",
                "name": "原煤",
                "unit": "万吨",
                "period": "2026-03",
                "source": "国家统计局",
                "sourceUrl": "https://example.com/nbs",
                "history": [
                    {"period": "2026-01", "periodLabel": "1月", "value": 90, "method": "estimated", "estimated": True, "formula": "interpolation"},
                    {"period": "2026-02", "periodLabel": "2月", "value": 100, "method": "observed"},
                    {"period": "2026-03", "periodLabel": "3月", "value": 110, "method": "observed"},
                ],
            }
        ]

        finalize_rows(rows)

        history = rows[0]["history"]
        self.assertFalse(any(any(key in point for key in ("open", "high", "low", "close")) for point in history))
        self.assertNotIn("mom", history[0])
        self.assertNotIn("mom", history[1])
        self.assertEqual(history[2]["mom"], 10.0)
        self.assertEqual(rows[0]["quality"]["method"], "observed")
        self.assertEqual(rows[0]["canonicalSeriesId"], "energy.cn.output.raw_coal.monthly")
        self.assertEqual(rows[0]["releaseCalendar"]["id"], "nbs.energy.monthly")
        self.assertEqual(rows[0]["historyLimit"], 18)

    def test_summary_counts_estimates_instead_of_kline_coverage(self) -> None:
        rows = [
            {
                "id": "raw_coal",
                "category": "煤炭",
                "period": "2026-03",
                "sourceUrl": "https://example.com/nbs",
                "history": [
                    {"period": "2026-02", "value": 100, "method": "estimated"},
                    {"period": "2026-03", "value": 110, "method": "observed"},
                ],
            }
        ]

        summary = build_summary(rows)

        self.assertEqual(summary["estimatedPointCount"], 1)
        self.assertEqual(summary["actualHistoryCount"], 1)
        self.assertEqual(summary["klineCount"], 0)

    def test_energy_http_client_keeps_tls_verification_enabled(self) -> None:
        source = inspect.getsource(get_energy)
        self.assertNotIn("verify=False", source)


if __name__ == "__main__":
    unittest.main()
