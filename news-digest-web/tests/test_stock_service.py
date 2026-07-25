import unittest
from datetime import date

from src.stock_service import (
    INDUSTRY_FINANCING_SERIES,
    INDUSTRY_FINANCING_TITLE,
    build_industry_financing_trend,
    industry_financing_query_start,
    industry_financing_window_start,
)


def financing_row(code: str, trade_date: str, amount: float, name: str = "") -> dict:
    return {
        "BOARD_CODE": code,
        "BOARD_NAME": name or code,
        "TRADE_DATE": f"{trade_date} 00:00:00",
        "FIN_NETBUY_AMT": amount,
    }


def series_by_code(payload: dict, code: str) -> dict:
    return next(item for item in payload["series"] if item["code"] == code)


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


if __name__ == "__main__":
    unittest.main()
