from __future__ import annotations

import unittest
from datetime import date

from src.stock_service import (
    PRIVATE_FUND_Q1_TOTAL_YUAN,
    build_institution_industry_payload,
    institution_category,
    latest_completed_disclosure_period,
    normalize_sw_industry,
    parse_etf_holdings_page,
    private_fund_category,
)


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


if __name__ == "__main__":
    unittest.main()
