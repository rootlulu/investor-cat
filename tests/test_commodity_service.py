from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import httpx

from src.commodity_service import (
    build_commodity_item,
    classify_shfe_inventory_diagnostic,
    decode_sina_response,
    fetch_commodity_sources,
    merge_inventory_series,
    parse_smm_lme_inventory_rows,
    select_primary_inventory,
    upgrade_commodity_snapshot,
)


class CommodityComparabilityTests(unittest.TestCase):
    def test_sina_gbk_decode_still_works_after_coordinator_reads_response_text(self) -> None:
        response = httpx.Response(200, content="铜期货".encode("gbk"))
        _ = response.text

        self.assertEqual(decode_sina_response(response), "铜期货")

    def test_additive_schema_upgrade_keeps_legacy_snapshot_immediately_readable(self) -> None:
        legacy = {
            "schemaVersion": 11,
            "items": [
                {
                    "id": "copper",
                    "name": "铜",
                    "sector": "有色金属",
                    "spotPrice": 80_000,
                    "inventorySeries": [{"inventoryType": "exchange_receipt"}],
                }
            ],
        }

        upgraded = upgrade_commodity_snapshot(legacy)

        self.assertEqual(upgraded["schemaVersion"], 13)
        self.assertEqual(upgraded["legacySchemaVersion"], 11)
        self.assertEqual(upgraded["items"][0]["canonicalId"], "commodity.copper")
        self.assertIn("power_grid", upgraded["items"][0]["tags"]["chains"])
        self.assertNotIn("canonicalId", legacy["items"][0])

    def test_item_exposes_canonical_series_and_multi_chain_tags(self) -> None:
        item = build_commodity_item(
            {
                "id": "copper",
                "name": "铜",
                "sector": "有色金属",
                "domesticFuture": "nf_CU0",
                "globalFuture": "hf_CAD",
                "spotNames": ["SMM 1#电解铜"],
                "unit": "元/吨",
            },
            {},
            {},
            {},
            {},
        )

        self.assertEqual(item["canonicalId"], "commodity.copper")
        self.assertEqual(item["seriesIds"]["spot"], "commodity.copper.price.spot")
        self.assertIn("power_grid", item["tags"]["chains"])
        self.assertEqual(item["releaseCalendars"]["futures"]["frequency"], "trading_daily")

    def test_rejects_basis_without_grade_location_and_explicit_contract(self) -> None:
        item = build_commodity_item(
            {
                "id": "polysilicon",
                "name": "多晶硅",
                "sector": "新能源材料",
                "domesticFuture": "nf_PS0",
                "domesticFutureUnit": "元/吨",
                "globalFuture": "",
                "spotNames": ["多晶硅"],
                "unit": "元/千克",
            },
            {"nf_PS0": {"symbol": "PS0", "price": 33_365, "date": "2026-07-25", "source": "新浪期货"}},
            {},
            {"多晶硅": {"name": "多晶硅", "price": 28, "unit": "元/千克", "date": "2026-07-25", "source": "SMM"}},
            {},
        )

        self.assertIsNone(item["basis"])
        self.assertIsNone(item["basisPct"])
        self.assertFalse(item["basisComparison"]["comparable"])
        self.assertIn("交割品级未核验", item["basisComparison"]["reasons"])
        self.assertIn("交割地点未核验", item["basisComparison"]["reasons"])
        self.assertIn("未对应具体交割合约", item["basisComparison"]["reasons"])
        self.assertEqual(item["basisQuality"]["status"], "invalid")

    def test_rejects_dimensionally_incompatible_units(self) -> None:
        item = build_commodity_item(
            {
                "id": "glass",
                "name": "玻璃",
                "sector": "玻璃链",
                "domesticFuture": "nf_FG0",
                "domesticFutureUnit": "元/吨",
                "globalFuture": "",
                "spotNames": ["玻璃"],
                "unit": "元/吨",
            },
            {"nf_FG0": {"symbol": "FG0", "price": 1_400, "date": "2026-07-25", "source": "新浪期货"}},
            {},
            {"玻璃": {"name": "玻璃", "price": 20, "unit": "元/平方米", "date": "2026-07-25", "source": "生意社"}},
            {},
        )

        self.assertIsNone(item["basis"])
        self.assertIn("现货与期货计价维度不可换算", item["basisComparison"]["reasons"])

    def test_relation_labels_do_not_call_driver_or_substitute_same_product(self) -> None:
        fuel_oil = build_commodity_item(
            {
                "id": "fuel_oil",
                "name": "燃料油",
                "sector": "大宗能源",
                "domesticFuture": "",
                "globalFuture": "hf_HO",
                "globalRelation": "substitute",
                "spotNames": [],
                "unit": "元/吨",
            },
            {"hf_HO": {"symbol": "HO", "price": 2.5, "date": "2026-07-25", "source": "新浪外盘"}},
            {},
            {},
            {},
        )
        lpg = build_commodity_item(
            {
                "id": "lpg",
                "name": "液化石油气",
                "sector": "大宗能源",
                "domesticFuture": "",
                "globalFuture": "",
                "benchmarkFuture": "hf_NG",
                "benchmarkRelation": "upstream_driver",
                "spotNames": [],
                "unit": "元/吨",
            },
            {"hf_NG": {"symbol": "NG", "price": 3.1, "date": "2026-07-25", "source": "新浪外盘"}},
            {},
            {},
            {},
        )

        self.assertEqual(fuel_oil["globalFutureRelation"], "substitute")
        self.assertEqual(lpg["benchmarkFutureRelation"], "upstream_driver")
        self.assertIsNone(fuel_oil["crossMarketSpread"])
        self.assertIsNone(lpg["crossMarketSpread"])


class CommoditySourceConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_source_groups_start_concurrently(self) -> None:
        started = 0
        all_started = asyncio.Event()

        async def source(_client):
            nonlocal started
            started += 1
            if started == 9:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=0.2)
            return {}, ""

        with (
            patch("src.commodity_service.fetch_sina_futures", side_effect=source),
            patch("src.commodity_service.fetch_sina_future_histories", side_effect=source),
            patch("src.commodity_service.fetch_smm_spots", side_effect=source),
            patch("src.commodity_service.fetch_sina_precious_spots", side_effect=source),
            patch("src.commodity_service.fetch_sunsirs_basis_spots", side_effect=source),
            patch("src.commodity_service.fetch_shfe_precious_inventories", side_effect=source),
            patch("src.commodity_service.fetch_smm_inventories", side_effect=source),
            patch("src.commodity_service.fetch_eastmoney_inventories", side_effect=source),
            patch("src.commodity_service.fetch_smm_lme_inventories", side_effect=source),
        ):
            results = await fetch_commodity_sources(object())

        self.assertEqual(started, 9)
        self.assertEqual(len(results), 9)


class CommodityInventoryTests(unittest.TestCase):
    def test_v151_lme_inventory_parser_marks_rows_international(self) -> None:
        parsed = parse_smm_lme_inventory_rows(
            [
                {
                    "date": "2026-07-28",
                    "newsId": 104028940,
                    "title": "7月27日LME多数金属库存减少镍增",
                    "profile": (
                        "【铜库存】7月27日LME铜库存减4200吨至268775吨。\n"
                        "【铝库存】7月27日LME铝库存减1975吨至269300吨。\n"
                        "【锌库存】7月27日LME锌库存减1225吨至102500吨。\n"
                        "【锡库存】7月27日LME锡库存减300吨至6410吨。\n"
                        "【镍库存】7月27日LME镍库存增180吨至267522吨。"
                    ),
                },
                {
                    "date": "2026-07-27",
                    "newsId": 104026458,
                    "title": "7月24日LME多数金属库存减少镍持平",
                    "profile": (
                        "【铜库存】7月24日LME铜库存减3800吨至272975吨。\n"
                        "【铝库存】7月24日LME铝库存减1500吨至271275吨。\n"
                        "【锌库存】7月24日LME锌库存减2075吨至103725吨。\n"
                        "【锡库存】7月24日LME锡库存减375吨至6710吨。\n"
                        "【镍库存】7月24日LME镍库存持平吨至267342吨。"
                    ),
                },
            ]
        )

        copper = parsed["copper"]
        self.assertEqual(copper["market"], "international")
        self.assertEqual(copper["exchange"], "LME")
        self.assertEqual(copper["inventory"], 268_775)
        self.assertEqual(copper["inventoryChange"], -4_200)
        self.assertEqual([row["date"] for row in copper["inventoryHistory"]], ["2026-07-24", "2026-07-27"])
        self.assertEqual(parsed["nickel"]["inventoryChange"], 180)

    def test_v150_inventory_selection_never_cross_fills_markets(self) -> None:
        merged = merge_inventory_series(
            {
                "copper": {
                    "inventory": 26_924,
                    "inventoryUnit": "吨",
                    "inventoryDate": "2026-07-28",
                    "inventorySource": "东方财富期货库存（CU仓单）",
                    "market": "domestic",
                }
            },
            {
                "copper": {
                    "inventory": 268_775,
                    "inventoryUnit": "吨",
                    "inventoryDate": "2026-07-27",
                    "inventorySource": "LME注册仓库库存（SMM转录）",
                    "market": "international",
                    "exchange": "LME",
                }
            },
        )

        domestic = select_primary_inventory("copper", merged["copper"], market="domestic")
        international = select_primary_inventory("copper", merged["copper"], market="international")

        self.assertEqual(domestic["inventory"], 26_924)
        self.assertEqual(international["inventory"], 268_775)

        item = build_commodity_item(
            {
                "id": "copper",
                "name": "铜",
                "sector": "有色金属",
                "domesticFuture": "nf_CU0",
                "globalFuture": "hf_CAD",
                "spotNames": [],
                "unit": "元/吨",
            },
            {},
            {},
            {},
            {"copper": merged["copper"]},
        )

        self.assertEqual(item["inventory"], 26_924)
        self.assertEqual(item["inventoryByMarket"]["domestic"]["inventory"], 26_924)
        self.assertEqual(item["inventoryByMarket"]["international"]["inventory"], 268_775)

    def test_shfe_unavailable_is_warning_when_precious_inventory_fallback_is_complete(self) -> None:
        errors, warnings = classify_shfe_inventory_diagnostic(
            "SHFE贵金属库存接口暂不可用",
            {
                "gold": {"inventory": 112_641, "inventoryDate": "2026-07-24"},
                "silver": {"inventory": 978_934, "inventoryDate": "2026-07-24"},
            },
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("备用源已补位", warnings[0])

    def test_shfe_unavailable_remains_error_without_complete_fallback(self) -> None:
        errors, warnings = classify_shfe_inventory_diagnostic(
            "SHFE贵金属库存接口暂不可用",
            {"gold": {"inventory": 112_641, "inventoryDate": "2026-07-24"}},
        )

        self.assertEqual(errors, ["SHFE贵金属库存接口暂不可用"])
        self.assertEqual(warnings, [])

    def test_inventory_types_are_retained_instead_of_overwritten(self) -> None:
        merged = merge_inventory_series(
            {
                "iron_ore": {
                    "inventory": 150,
                    "inventoryUnit": "万吨",
                    "inventoryDate": "2026-07-24",
                    "inventorySource": "SMM 35港铁矿石库存",
                    "inventoryType": "port_stock",
                }
            },
            {
                "iron_ore": {
                    "inventory": 25,
                    "inventoryUnit": "万吨",
                    "inventoryDate": "2026-07-25",
                    "inventorySource": "东方财富期货库存",
                    "inventoryType": "exchange_receipt",
                }
            },
        )

        self.assertEqual({row["inventoryType"] for row in merged["iron_ore"]}, {"port_stock", "exchange_receipt"})
        primary = select_primary_inventory("iron_ore", merged["iron_ore"])
        self.assertEqual(primary["inventoryType"], "port_stock")
        self.assertEqual(primary["inventory"], 150)


if __name__ == "__main__":
    unittest.main()
