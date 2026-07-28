from __future__ import annotations

import unittest
from datetime import UTC, datetime

from src.investment_catalog import (
    bounded_history,
    build_commodity_metadata,
    build_energy_metadata,
    build_macro_metadata,
    is_canonical_series_id,
)
from src.macro_service import build_macro_countries, upgrade_macro_snapshot


NOW = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)


class InvestmentCatalogTests(unittest.TestCase):
    def test_macro_additive_schema_upgrade_namespaces_legacy_rows(self) -> None:
        legacy = {
            "schemaVersion": 6,
            "countries": [
                {
                    "id": "china",
                    "groups": [
                        {
                            "name": "价格",
                            "items": [{"id": "cpi", "name": "CPI", "value": "1.2", "unit": "%", "period": "2026-06", "history": []}],
                        }
                    ],
                }
            ],
        }

        upgraded = upgrade_macro_snapshot(legacy)

        row = upgraded["countries"][0]["groups"][0]["items"][0]
        self.assertEqual(upgraded["schemaVersion"], 7)
        self.assertEqual(upgraded["legacySchemaVersion"], 6)
        self.assertEqual(row["canonicalSeriesId"], "macro.cn.cpi")
        self.assertEqual(row["quality"]["method"], "observed")
        self.assertEqual(row["quality"]["status"], "stale")
        self.assertTrue(row["quality"]["sourceUrl"])
        self.assertGreater(upgraded["qualitySummary"]["stale"], 0)
        self.assertNotIn("canonicalSeriesId", legacy["countries"][0]["groups"][0]["items"][0])

    def test_commodity_metadata_supports_multi_chain_tags_and_inventory_series(self) -> None:
        metadata = build_commodity_metadata(
            {"id": "copper", "sector": "有色金属", "domesticFuture": "nf_CU0", "globalFuture": "hf_CAD"},
            [{"inventoryType": "exchange_receipt"}, {"inventoryType": "social_stock"}],
            as_of=NOW,
        )

        self.assertEqual(metadata["canonicalId"], "commodity.copper")
        self.assertEqual(metadata["seriesIds"]["domesticFuture"], "commodity.copper.price.future.domestic")
        self.assertEqual(
            metadata["seriesIds"]["inventories"],
            {
                "exchange_receipt": "commodity.copper.inventory.exchange_receipt",
                "social_stock": "commodity.copper.inventory.social_stock",
            },
        )
        self.assertTrue({"base_metals", "power_grid", "construction"}.issubset(metadata["tags"]["chains"]))
        self.assertTrue(all(is_canonical_series_id(value) for value in metadata["seriesIds"].values() if isinstance(value, str)))

    def test_energy_series_uses_verified_nbs_2026_calendar(self) -> None:
        metadata = build_energy_metadata("thermal_power", "电力", as_of=NOW)

        self.assertEqual(metadata["canonicalSeriesId"], "energy.cn.generation.thermal.monthly")
        self.assertEqual(metadata["releaseCalendar"]["id"], "nbs.energy.monthly")
        self.assertEqual(metadata["releaseCalendar"]["nextScheduledAt"], "2026-08-17T10:00:00+08:00")
        self.assertEqual(metadata["historyLimit"], 18)

    def test_macro_country_namespace_prevents_cpi_collision(self) -> None:
        china = build_macro_metadata("china", {"id": "cpi", "name": "CPI 同比", "period": "2026-06", "source": "NBS"}, as_of=NOW)
        us = build_macro_metadata("us", {"id": "cpi", "name": "CPI 同比", "period": "2026-06", "source": "BLS"}, as_of=NOW)

        self.assertEqual(china["canonicalSeriesId"], "macro.cn.cpi")
        self.assertEqual(us["canonicalSeriesId"], "macro.us.cpi")
        self.assertNotEqual(china["canonicalSeriesId"], us["canonicalSeriesId"])
        self.assertEqual(china["releaseCalendar"]["id"], "nbs.price.monthly")
        self.assertEqual(china["releaseCalendar"]["nextScheduledAt"], "2026-08-09T09:30:00+08:00")

    def test_dynamic_nbs_material_id_is_stable_across_row_order(self) -> None:
        first = build_macro_metadata(
            "china",
            {"id": "nbs_material_01", "name": "电解铜（1#）", "category": "有色金属", "period": "2026-07中旬", "source": "NBS"},
            as_of=NOW,
        )
        reordered = build_macro_metadata(
            "china",
            {"id": "nbs_material_42", "name": "电解铜（1#）", "category": "有色金属", "period": "2026-07中旬", "source": "NBS"},
            as_of=NOW,
        )

        self.assertEqual(first["canonicalSeriesId"], reordered["canonicalSeriesId"])
        self.assertEqual(first["releaseCalendar"]["id"], "nbs.materials.tenday")

    def test_bounded_history_deduplicates_and_keeps_latest_points(self) -> None:
        points = [
            {"period": "2026-01", "value": 1},
            {"period": "2026-02", "value": 2},
            {"period": "2026-02", "value": 20},
            {"period": "2026-03", "value": 3},
        ]

        bounded = bounded_history(points, limit=2)

        self.assertEqual(bounded, [{"period": "2026-02", "value": 20}, {"period": "2026-03", "value": 3}])

    def test_macro_payload_attaches_collision_free_canonical_ids_and_bounded_history(self) -> None:
        countries = build_macro_countries()
        rows = [row for country in countries for group in country["groups"] for row in group["items"]]
        canonical_ids = [row["canonicalSeriesId"] for row in rows]

        self.assertEqual(len(canonical_ids), len(set(canonical_ids)))
        self.assertTrue(all(is_canonical_series_id(value) for value in canonical_ids))
        self.assertTrue(all(len(row["history"]) <= row["historyLimit"] for row in rows))
        self.assertTrue(all(row["quality"]["unit"] for row in rows))
        self.assertTrue(all(row["quality"]["asOf"] for row in rows))
        self.assertTrue(all(row["quality"]["sourceUrl"] for row in rows))
        self.assertTrue(all(row["quality"]["method"] == "observed" for row in rows))


if __name__ == "__main__":
    unittest.main()
