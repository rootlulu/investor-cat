from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.stock_service import (
    BROWSER_USER_AGENT,
    INDUSTRY_FINANCING_SERIES,
    INDUSTRY_FINANCING_TITLE,
    PRIVATE_FUND_Q1_TOTAL_YUAN,
    build_etf_flow_signal,
    build_financing_momentum_signal,
    build_funding_signal,
    build_index_futures_signal,
    build_industry_financing_trend,
    build_institution_industry_payload,
    build_industrial_capital_signal,
    build_market_breadth_signal,
    classify_stock_diagnostics,
    calculate_option_skew,
    discover_industry_financing_group_definitions,
    eastmoney_headers,
    estimate_etf_flow_from_aum,
    etf_implied_share_change_is_plausible,
    fetch_eastmoney_a_share_rows_sync,
    fetch_stock_industry_map_sync,
    industry_financing_query_start,
    industry_financing_window_start,
    institution_category,
    latest_completed_disclosure_period,
    normalize_sw_industry,
    new_browser_session,
    parse_cffex_daily_rows,
    parse_etf_holdings_page,
    private_fund_category,
    load_industry_financing_group_cache_sync,
    save_industry_financing_group_cache_sync,
    upgrade_stock_snapshot,
    warm_browser_session,
)


def financing_row(
    code: str,
    trade_date: str,
    amount: float,
    name: str = "",
    balance: float | None = None,
) -> dict:
    row = {
        "BOARD_CODE": code,
        "BOARD_NAME": name or code,
        "TRADE_DATE": f"{trade_date} 00:00:00",
        "FIN_NETBUY_AMT": amount,
    }
    if balance is not None:
        row["FIN_BALANCE"] = balance
    return row


def series_by_code(payload: dict, code: str) -> dict:
    return next(item for item in payload["series"] if item["code"] == code)


class StockSnapshotMigrationTests(unittest.TestCase):
    def test_successful_fallback_warning_is_not_promoted_to_source_error(self) -> None:
        diagnostics = classify_stock_diagnostics(
            ["世界股票数据：timeout"],
            ["东方财富行业接口本轮断连，已启用同花顺行业资金流向备用。"],
        )

        self.assertEqual(diagnostics["errors"], ["世界股票数据：timeout"])
        self.assertEqual(
            diagnostics["warnings"],
            ["东方财富行业接口本轮断连，已启用同花顺行业资金流向备用。"],
        )

    def test_additive_schema_upgrade_keeps_legacy_market_snapshot_readable(self) -> None:
        legacy = {
            "schemaVersion": 15,
            "markets": [
                {
                    "id": "a_share",
                    "indices": [{"symbol": "000001", "name": "上证指数", "changePct": 1.2}],
                }
            ],
        }

        upgraded = upgrade_stock_snapshot(legacy)

        self.assertEqual(upgraded["schemaVersion"], 16)
        self.assertEqual(upgraded["legacySchemaVersion"], 15)
        self.assertIn("qualitySummary", upgraded)
        self.assertNotIn("qualitySummary", legacy)


class IndustryFinancingTrendTests(unittest.TestCase):
    def test_builds_aligned_cumulative_series_in_billions_of_yuan(self) -> None:
        window_start = date(2023, 7, 20)
        payload = build_industry_financing_trend(
            [
                financing_row("1201", "2025-01-02", 100_000_000, "电子"),
                financing_row("1215", "2025-01-02", 200_000_000, "通信"),
                financing_row("1201", "2025-01-03", -50_000_000, "电子"),
            ],
            requested_start_date=window_start,
        )

        self.assertEqual(payload["dates"], ["2025-01-02", "2025-01-03"])
        self.assertEqual(payload["title"], INDUSTRY_FINANCING_TITLE)
        self.assertEqual(payload["requestedStartDate"], "2023-07-20")
        self.assertEqual(payload["unit"], "亿元")
        self.assertEqual(series_by_code(payload, "1201")["values"], [1.0, 0.5])
        self.assertEqual(series_by_code(payload, "1215")["values"], [2.0, 2.0])
        self.assertEqual(len(payload["series"]), len(INDUSTRY_FINANCING_SERIES))
        self.assertTrue(all(len(item["values"]) == len(payload["dates"]) for item in payload["series"]))

    def test_incremental_merge_replaces_the_overlapping_last_day(self) -> None:
        window_start = date(2023, 7, 20)
        previous = build_industry_financing_trend(
            [
                financing_row("1201", "2025-01-02", 100_000_000, "电子"),
                financing_row("1201", "2025-01-03", 200_000_000, "电子"),
            ],
            requested_start_date=window_start,
        )

        self.assertEqual(industry_financing_query_start(previous, window_start), date(2025, 1, 3))
        updated = build_industry_financing_trend(
            [
                financing_row("1201", "2025-01-03", 400_000_000, "电子"),
                financing_row("1201", "2025-01-06", -100_000_000, "电子"),
            ],
            previous,
            window_start,
        )

        self.assertEqual(updated["dates"], ["2025-01-02", "2025-01-03", "2025-01-06"])
        self.assertEqual(series_by_code(updated, "1201")["values"], [1.0, 5.0, 4.0])

    def test_invalid_previous_payload_forces_full_history_query(self) -> None:
        window_start = date(2023, 7, 20)
        self.assertEqual(industry_financing_query_start(None, window_start), window_start)
        self.assertEqual(
            industry_financing_query_start(
                {"requestedStartDate": "2023-07-20", "dates": ["bad-date"], "series": []},
                window_start,
            ),
            window_start,
        )

    def test_window_start_is_exactly_three_years_and_handles_leap_day(self) -> None:
        self.assertEqual(industry_financing_window_start(date(2026, 7, 20)), date(2023, 7, 20))
        self.assertEqual(industry_financing_window_start(date(2024, 2, 29)), date(2021, 2, 28))

    def test_rolling_window_drops_and_rebases_expired_history(self) -> None:
        previous = build_industry_financing_trend(
            [
                financing_row("1201", "2023-07-20", 100_000_000, "电子"),
                financing_row("1201", "2023-07-21", 200_000_000, "电子"),
                financing_row("1201", "2023-07-24", 300_000_000, "电子"),
            ],
            requested_start_date=date(2023, 7, 20),
        )

        next_window_start = date(2023, 7, 21)
        self.assertEqual(industry_financing_query_start(previous, next_window_start), date(2023, 7, 24))
        updated = build_industry_financing_trend(
            [
                financing_row("1201", "2023-07-24", 300_000_000, "电子"),
                financing_row("1201", "2023-07-25", 400_000_000, "电子"),
            ],
            previous,
            next_window_start,
        )

        self.assertEqual(updated["dates"], ["2023-07-21", "2023-07-24", "2023-07-25"])
        self.assertEqual(series_by_code(updated, "1201")["values"], [2.0, 5.0, 9.0])
        self.assertEqual(updated["requestedStartDate"], "2023-07-21")

    def test_financing_series_include_latest_balance_and_official_level(self) -> None:
        payload = build_industry_financing_trend(
            [
                financing_row("1201", "2026-07-23", 100_000_000, "电子", 25_000_000_000),
                financing_row("1201", "2026-07-24", -50_000_000, "电子", 26_000_000_000),
            ],
            requested_start_date=date(2023, 7, 25),
        )

        electronics = series_by_code(payload, "1201")
        self.assertEqual(electronics["level"], 1)
        self.assertEqual(electronics["latest"], 0.5)
        self.assertEqual(electronics["latestBalance"], 260)
        self.assertEqual(electronics["latestBalanceDate"], "2026-07-24")
        self.assertEqual(payload["balanceDate"], "2026-07-24")

    def test_group_discovery_uses_second_level_and_rejects_third_level(self) -> None:
        definitions = discover_industry_financing_group_definitions(
            "传媒",
            [
                {"BOARD_CODE": "101", "BOARD_NAME": "游戏Ⅱ"},
                {"BOARD_CODE": "102", "BOARD_NAME": "游戏Ⅲ"},
                {"BOARD_CODE": "103", "BOARD_NAME": "影视院线"},
                {"BOARD_CODE": "104", "BOARD_NAME": "短剧互动游戏"},
            ],
        )

        self.assertEqual(
            [(item["name"], item["code"]) for item in definitions],
            [("影视院线", "103"), ("游戏", "101")],
        )

    def test_group_cache_round_trip_preserves_payload(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "stocks.sqlite"
            payload = {"parentIndustry": "传媒", "savedAt": "2026-07-25T10:00:00+00:00", "series": []}

            save_industry_financing_group_cache_sync(db_path, "传媒", payload)

            self.assertEqual(load_industry_financing_group_cache_sync(db_path, "传媒"), payload)



class BrowserSessionTests(unittest.TestCase):
    def test_browser_session_keeps_one_fingerprint_and_uses_domain_coordinator(self) -> None:
        with new_browser_session() as session:
            self.assertEqual(session.headers["User-Agent"], BROWSER_USER_AGENT)
            retry = session.get_adapter("https://").max_retries
            self.assertEqual(retry.total, 0)
            self.assertTrue(session._domain_coordinator_wrapped)

    def test_eastmoney_xhr_origin_matches_the_landing_page(self) -> None:
        headers = eastmoney_headers("https://quote.eastmoney.com/center/gridlist.html#fund_etf")

        self.assertEqual(headers["Origin"], "https://quote.eastmoney.com")
        self.assertEqual(headers["Sec-Fetch-Mode"], "cors")

    @patch("src.stock_service.time.sleep")
    def test_browser_warmup_visits_each_host_once(self, sleep_mock) -> None:
        class Response:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def close(self) -> None:
                return None

        class Session:
            def __init__(self) -> None:
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return Response()

        session = Session()
        warm_browser_session(session, "https://example.com/source/a", 8)
        warm_browser_session(session, "https://example.com/source/b", 8)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["headers"]["Sec-Fetch-Mode"], "navigate")
        sleep_mock.assert_called_once()


class InstitutionIndustryAllocationTests(unittest.TestCase):
    def test_latest_completed_period_respects_disclosure_deadlines(self) -> None:
        self.assertEqual(latest_completed_disclosure_period(date(2026, 7, 22)), date(2026, 3, 31))
        self.assertEqual(latest_completed_disclosure_period(date(2026, 9, 1)), date(2026, 6, 30))
        self.assertEqual(latest_completed_disclosure_period(date(2026, 4, 29)), date(2025, 9, 30))

    def test_second_level_industries_are_normalized_to_sw_first_level(self) -> None:
        self.assertEqual(normalize_sw_industry("电池"), "电力设备")
        self.assertEqual(normalize_sw_industry("银行Ⅱ"), "银行")
        self.assertEqual(normalize_sw_industry("白酒Ⅱ"), "食品饮料")
        self.assertEqual(normalize_sw_industry("医疗服务"), "医药生物")
        self.assertEqual(normalize_sw_industry(None), "未分类")

    def test_etf_parser_selects_only_requested_report_period(self) -> None:
        page = """
        var apidata={ content:"
        <div class='box'><h4>截止至：<font>2026-06-30</font></h4>
          <table><tr><td>1</td><td>300001</td><td>示例甲</td><td>1.00</td></tr></table>
        </div>
        <div class='box'><h4>截止至：<font class='px12'>2026-03-31</font></h4>
          <table>
            <tr><th>序号</th><th>代码</th><th>名称</th><th>持仓市值</th></tr>
            <tr><td>1</td><td>600519</td><td>贵州茅台</td><td>730,579.89</td></tr>
            <tr><td>2*</td><td>300750</td><td>宁德时代</td><td>854,404.57</td></tr>
          </table>
        </div>",curyear:2026};
        """

        holdings = parse_etf_holdings_page(page, "2026-03-31")

        self.assertEqual([item["code"] for item in holdings], ["600519", "300750"])
        self.assertEqual(holdings[0]["marketValue"], 7_305_798_900)

    def test_etf_industry_map_retries_a_disconnected_large_batch_as_smaller_chunks(self) -> None:
        class Response:
            def __init__(self, codes: list[str]) -> None:
                self._codes = codes

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": {
                        "diff": [
                            {"f12": code, "f14": f"样本{code}", "f100": "电子"}
                            for code in self._codes
                        ]
                    }
                }

        class Session:
            def __init__(self) -> None:
                self.batch_sizes: list[int] = []
                self.urls: list[str] = []

            def get(self, url, *, params, **_kwargs):
                codes = [secid.split(".", 1)[1] for secid in params["secids"].split(",")]
                self.urls.append(url)
                self.batch_sizes.append(len(codes))
                if len(codes) > 20:
                    import requests

                    raise requests.ConnectionError("remote disconnected")
                return Response(codes)

        codes = {f"{index:06d}" for index in range(45)}
        session = Session()

        industry_map = fetch_stock_industry_map_sync(session, codes, 8)

        self.assertEqual(set(industry_map), codes)
        self.assertTrue(all("push2delay.eastmoney.com" in url for url in session.urls))
        self.assertEqual(session.batch_sizes[0], 45)
        self.assertTrue(all(size <= 20 for size in session.batch_sizes[1:]))

    def test_private_sample_keeps_published_total_and_groups_undisclosed_sectors(self) -> None:
        category = private_fund_category()

        self.assertEqual(category["totalMarketValue"], PRIVATE_FUND_Q1_TOTAL_YUAN)
        self.assertGreater(category["_industryValues"]["其他20个行业"], 0)

    def test_each_category_column_is_normalized_to_one_hundred_percent(self) -> None:
        category = institution_category(
            category_id="sample",
            label="样本",
            report_date="2026-03-31",
            values={"电子": 60, "银行": 40},
            sample_count=2,
            total_count=2,
            source="测试",
            source_url="https://example.com",
            note="测试口径",
            coverage_label="样本覆盖",
            coverage_pct=100,
        )

        payload = build_institution_industry_payload("2026-03-31", [category], [])
        share_sum = sum(row["values"].get("sample", {}).get("sharePct", 0) for row in payload["industries"])

        self.assertAlmostEqual(share_sum, 100)
        self.assertNotIn("_industryValues", payload["categories"][0])

    def test_hierarchy_reconciles_children_and_marks_missing_disclosure(self) -> None:
        public_fund = institution_category(
            category_id="public_fund",
            label="公募基金",
            report_date="2026-03-31",
            values={"传媒": 100},
            level_two_values={"传媒": {"影视院线": 40, "游戏": 60}},
            sample_count=2,
            total_count=2,
            source="测试",
            source_url="https://example.com/public",
            note="测试口径",
            coverage_label="样本覆盖",
            coverage_pct=100,
        )
        private_fund = institution_category(
            category_id="private_fund",
            label="百亿私募",
            report_date="2026-03-31",
            values={"传媒": 20},
            sample_count=1,
            total_count=1,
            source="测试",
            source_url="https://example.com/private",
            note="仅披露一级",
            coverage_label="样本覆盖",
            coverage_pct=None,
        )

        payload = build_institution_industry_payload(
            "2026-03-31",
            [public_fund, private_fund],
            [],
        )
        media = next(group for group in payload["industryGroups"] if group["name"] == "传媒")
        public_child_share = sum(
            child["values"].get("public_fund", {}).get("sharePct", 0)
            for child in media["children"]
        )

        self.assertEqual(media["values"]["public_fund"]["sharePct"], 100)
        self.assertEqual(public_child_share, 100)
        self.assertFalse(next(item for item in payload["categories"] if item["id"] == "private_fund")["hasLevel2Data"])
        self.assertTrue(all("private_fund" not in child["values"] for child in media["children"]))


class MarginalSignalTests(unittest.TestCase):
    @patch("src.stock_service.time.sleep")
    @patch("src.stock_service.warm_browser_session")
    def test_eastmoney_breadth_fallback_keeps_vendor_total_and_units(self, warm_mock, sleep_mock) -> None:
        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": {
                        "total": 2,
                        "diff": [
                            {
                                "f12": "600000",
                                "f14": "样本甲",
                                "f2": 10.5,
                                "f3": 1.25,
                                "f6": 120_000_000,
                                "f124": int(datetime(2026, 7, 24, 7, tzinfo=UTC).timestamp()),
                            },
                            {
                                "f12": "000001",
                                "f14": "样本乙",
                                "f2": 12.3,
                                "f3": -0.75,
                                "f6": 80_000_000,
                                "f124": int(datetime(2026, 7, 24, 7, tzinfo=UTC).timestamp()),
                            },
                        ],
                    }
                }

        class Session:
            def get(self, url, **kwargs):
                return Response()

        rows, total = fetch_eastmoney_a_share_rows_sync(Session(), 8)

        self.assertEqual(total, 2)
        self.assertEqual(rows[0]["changePct"], 1.25)
        self.assertEqual(rows[0]["turnover"], 120_000_000)
        self.assertEqual(rows[0]["date"], "2026-07-24")
        signal = build_market_breadth_signal(
            rows,
            total,
            source="东方财富 A 股行情列表",
            source_url="https://example.com/a-share",
            source_badge="东方财富扫描 · 覆盖率可见",
        )
        self.assertEqual(signal["source"], "东方财富 A 股行情列表")
        self.assertEqual(signal["sourceBadge"], "东方财富扫描 · 覆盖率可见")
        self.assertEqual(signal["dataTimestamp"], "2026-07-24")
        warm_mock.assert_called_once()
        sleep_mock.assert_called_once()

    def test_financing_signal_uses_rolling_flow_and_acceleration(self) -> None:
        records = [
            {
                "date": f"2026-07-{index:02d}",
                "netBuy": float(index * 100_000_000),
                "floatMarketCap": 100_000_000_000,
                "shortBalance": index * 10_000_000,
            }
            for index in range(1, 21)
        ]

        signal = build_financing_momentum_signal(records)

        self.assertEqual(signal["status"], "ok")
        self.assertEqual(signal["metrics"][0]["value"], sum(range(16, 21)) * 100_000_000)
        self.assertEqual(signal["metrics"][1]["value"], (sum(range(16, 21)) - sum(range(11, 16))) * 100_000_000)
        self.assertEqual(len(signal["charts"][0]["series"][0]["points"]), 20)

    def test_etf_flow_aggregates_broad_and_industry_samples(self) -> None:
        samples = [
            {
                "name": "沪深300ETF",
                "bucket": "broad",
                "marketValue": 600,
                "points": [
                    {"date": "2026-07-23", "flow": 100_000_000},
                    {"date": "2026-07-24", "flow": 200_000_000},
                ],
            },
            {
                "name": "半导体ETF",
                "bucket": "industry",
                "marketValue": 200,
                "points": [
                    {"date": "2026-07-23", "flow": -50_000_000},
                    {"date": "2026-07-24", "flow": 100_000_000},
                ],
            },
        ]

        signal = build_etf_flow_signal(samples, eligible_market_value=1_000)

        self.assertEqual(signal["status"], "ok")
        self.assertEqual(signal["metrics"][0]["value"], 300_000_000)
        self.assertEqual(signal["metrics"][5]["value"], 80)
        self.assertEqual(signal["charts"][0]["series"][0]["points"][-1]["value"], 2)

    def test_etf_flow_removes_price_return_from_official_aum_change(self) -> None:
        flow = estimate_etf_flow_from_aum(
            previous_aum=10_000_000_000,
            current_aum=11_200_000_000,
            previous_close=10,
            current_close=11,
        )

        self.assertEqual(flow, 200_000_000)
        self.assertFalse(
            etf_implied_share_change_is_plausible(
                previous_aum=53_623_770_000,
                current_aum=162_545_150_000,
                previous_close=3.613,
                current_close=3.539,
            )
        )

    def test_index_futures_basis_is_calculated_against_matching_spot(self) -> None:
        rows = [
            {
                "symbol": "IF",
                "instrumentId": "IF2609",
                "tradeDate": "2026-07-24",
                "close": 99,
                "volume": 10,
                "openInterest": 20,
                "previousOpenInterest": 15,
            }
        ]
        spots = {"IF": {"date": "2026-07-24", "close": 100}}

        signal = build_index_futures_signal(rows, spots)

        self.assertEqual(signal["status"], "ok")
        self.assertAlmostEqual(signal["contracts"][0]["basisPct"], -1)
        self.assertAlmostEqual(signal["charts"][0]["series"][0]["points"][0]["value"], -6.518)
        metrics = {metric["label"]: metric["value"] for metric in signal["metrics"]}
        self.assertEqual(metrics["名义持仓合计"], 600_000)
        self.assertEqual(metrics["名义持仓日变动"], 150_000)

    def test_cffex_parser_uses_official_open_interest_difference(self) -> None:
        rows = parse_cffex_daily_rows(
            b"""<?xml version='1.0' encoding='UTF-8'?><dailydatas><dailydata>
            <instrumentid>IF2609</instrumentid><tradingday>20260724</tradingday>
            <closeprice>4578.2</closeprice><volume>74354</volume>
            <preopeninterest>152466</preopeninterest><openinterest>156427</openinterest>
            </dailydata></dailydatas>"""
        )

        self.assertEqual(rows[0]["instrumentId"], "IF2609")
        self.assertEqual(rows[0]["openInterest"] - rows[0]["previousOpenInterest"], 3961)

    def test_option_skew_selects_nearest_twenty_five_delta_pair(self) -> None:
        rows = [
            {"CONTRACT_ID": "510050C2608M03000", "DELTA_VALUE": "0.26", "IMPLC_VOLATLTY": "0.20"},
            {"CONTRACT_ID": "510050P2608M03000", "DELTA_VALUE": "-0.24", "IMPLC_VOLATLTY": "0.25"},
            {"CONTRACT_ID": "510050C2609M03000", "DELTA_VALUE": "0.25", "IMPLC_VOLATLTY": "0.30"},
            {"CONTRACT_ID": "510050P2609M03000", "DELTA_VALUE": "-0.25", "IMPLC_VOLATLTY": "0.31"},
        ]

        result = calculate_option_skew(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["expiry"], "2608")
        self.assertAlmostEqual(result[0]["skewPp"], 5)

    def test_industrial_capital_separates_plan_midpoint_from_disclosed_buyback(self) -> None:
        plans = [
            {
                "DIM_TRADEDATE": "2026-07-24",
                "REPURCODE": "1",
                "REPURAMOUNT": 1_000_000,
                "REPURAMOUNTLOWER": 4_000_000,
                "REPURAMOUNTLIMIT": 6_000_000,
                "ZJJE": 1_000_000,
                "SECURITYSHORTNAME": "样本公司",
            }
        ]
        changes = [
            {"TRADE_DATE": "2026-07-24", "SECURITY_CODE": "1", "HOLDER_NAME": "甲", "DIRECTION": "增持", "CHANGE_NUM": 10, "CLOSE_PRICE": 10},
            {"TRADE_DATE": "2026-07-24", "SECURITY_CODE": "2", "HOLDER_NAME": "乙", "DIRECTION": "减持", "CHANGE_NUM": 5, "CLOSE_PRICE": 10},
        ]

        signal = build_industrial_capital_signal(plans, changes, market_cap=100_000_000)

        self.assertEqual(signal["metrics"][0]["value"], 1_000_000)
        self.assertEqual(signal["metrics"][1]["value"], 5_000_000)
        self.assertEqual(signal["metrics"][2]["value"], 500_000)
        self.assertEqual(signal["metrics"][3]["value"], 1_500_000)

    def test_breadth_and_funding_signals_keep_their_published_units(self) -> None:
        breadth = build_market_breadth_signal(
            [
                {"changePct": 1, "turnover": 100},
                {"changePct": -1, "turnover": 50},
                {"changePct": 10, "turnover": 25},
            ]
        )
        funding = build_funding_signal(
            [
                {"frValueMap": {"date": "2026-07-24", "FR007": "1.4100", "FDR007": "1.4000"}}
            ]
        )

        self.assertEqual(breadth["metrics"][0]["value"], 66.67)
        self.assertEqual(funding["metrics"][2]["format"], "bp")
        self.assertAlmostEqual(funding["metrics"][2]["value"], 1)


if __name__ == "__main__":
    unittest.main()
