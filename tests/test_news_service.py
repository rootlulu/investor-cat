import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from src.news_service import (
    RequestState,
    SourceNoResultsError,
    build_stale_news_fallback,
    fetch_source,
    looks_bad_translation,
    normalize_news_issues,
    normalize_translated_title,
    safe_chinese_title,
    translate_titles_bounded,
    title_translation_succeeded,
    translate_one_title,
)


class NewsTranslationTests(unittest.IsolatedAsyncioTestCase):
    def test_original_proper_noun_is_allowed_in_chinese_translation(self) -> None:
        original = "China's Nexchip to raise $890 million in Hong Kong share sale"
        translated = "中国Nexchip将在香港发售股票，筹集8.9亿美元"

        self.assertFalse(looks_bad_translation(translated, original))
        self.assertTrue(title_translation_succeeded(original, translated))
        self.assertEqual(safe_chinese_title(original, translated, "china"), translated)

    def test_untranslated_english_prose_is_still_rejected(self) -> None:
        original = "China's Nexchip to raise $890 million in Hong Kong share sale"
        partial = "中国Nexchip to raise 890 million Hong Kong share sale"

        self.assertTrue(looks_bad_translation(partial, original))

    def test_normalization_does_not_merge_english_names_and_model_numbers(self) -> None:
        value = normalize_translated_title("中国将允许公司购买 Nvidia H200 芯片")

        self.assertEqual(value, "中国将允许公司购买Nvidia H200芯片")

    async def test_single_title_translation_retries_transient_failures(self) -> None:
        original = "China's Nexchip to raise $890 million in Hong Kong share sale"
        translated = "中国Nexchip将在香港发售股票，筹集8.9亿美元"

        with (
            patch(
                "src.news_service.translate_batch",
                new=AsyncMock(side_effect=[RuntimeError("rate limited"), {original: translated}]),
            ) as translate_batch,
            patch("src.news_service.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            result = await translate_one_title(original, object(), object())

        self.assertEqual(result, translated)
        self.assertEqual(translate_batch.await_count, 2)
        self.assertEqual(sleep.await_count, 1)


class NewsRefreshIssueTests(unittest.IsolatedAsyncioTestCase):
    def request_state(self, *, days: int = 7) -> RequestState:
        return RequestState(
            max_concurrency=3,
            per_domain_concurrency=1,
            timeout=1,
            retries=0,
            source_timeout=1,
            enable_gdelt_fallback=False,
            days=days,
        )

    async def test_v153_all_profile_failures_keep_source_and_real_cause(self) -> None:
        source = {"name": "Reuters", "domains": ["reuters.com"]}
        since = datetime.now(UTC) - timedelta(days=7)

        with patch(
            "src.news_service.fetch_text",
            new=AsyncMock(side_effect=RuntimeError("news.google.com 请求失败: ReadTimeout('')")),
        ) as fetch_text:
            with self.assertRaisesRegex(RuntimeError, "Reuters：请求超时"):
                await fetch_source(source, since, object(), self.request_state())

        self.assertEqual(fetch_text.await_count, 3)

    async def test_v153_valid_empty_feed_is_warning_not_fetch_error(self) -> None:
        source = {"name": "Returns", "domains": ["returns.news"]}
        since = datetime.now(UTC) - timedelta(days=7)

        with patch("src.news_service.fetch_google_news", new=AsyncMock(return_value=[])):
            with self.assertRaisesRegex(SourceNoResultsError, "Returns：近7天无匹配新闻"):
                await fetch_source(source, since, object(), self.request_state())

    async def test_v153_translation_timeout_keeps_news_usable(self) -> None:
        with patch(
            "src.news_service.translate_titles",
            new=AsyncMock(side_effect=TimeoutError),
        ):
            translated, warnings = await translate_titles_bounded(
                [{"title": "Markets rise", "_candidateSection": "world"}],
                object(),
                self.request_state(),
                timeout_seconds=0.01,
            )

        self.assertEqual(translated, {})
        self.assertEqual(warnings, ["标题翻译：超时，已使用本地标题"])

    def test_v153_legacy_blank_errors_are_removed_and_empty_feed_is_warning(self) -> None:
        payload = {
            "errors": [
                "Returns: 最近7天没有抓到 Google News RSS 新闻",
                "",
                "Reuters: news.google.com 请求失败: ReadTimeout('')",
            ]
        }

        normalize_news_issues(payload)

        self.assertEqual(payload["errors"], ["Reuters：请求超时"])
        self.assertEqual(payload["warnings"], ["Returns：近7天无匹配新闻"])

    def test_v153_stale_fallback_reports_current_attempt_not_old_snapshot(self) -> None:
        stored = {
            "generatedAt": "2026-07-27T00:00:00+00:00",
            "errors": ["Returns: 最近7天没有抓到 Google News RSS 新闻", ""],
            "china": [],
            "world": [],
        }

        fallback = build_stale_news_fallback(
            stored,
            errors=["Reuters：抓取超时"],
            warnings=["Returns：近7天无匹配新闻"],
        )

        self.assertTrue(fallback["stale"])
        self.assertEqual(fallback["errors"], ["Reuters：抓取超时"])
        self.assertEqual(fallback["warnings"], ["Returns：近7天无匹配新闻"])


if __name__ == "__main__":
    unittest.main()
