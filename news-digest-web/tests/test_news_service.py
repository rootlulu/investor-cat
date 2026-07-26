import unittest
from unittest.mock import AsyncMock, patch

from src.news_service import (
    looks_bad_translation,
    normalize_translated_title,
    safe_chinese_title,
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


if __name__ == "__main__":
    unittest.main()
