import unittest
from unittest.mock import AsyncMock, patch

from src import energy_service


class CrawlProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_energy_release_index_pages_are_reused_across_keywords(self) -> None:
        pages = [
            (
                "https://www.stats.gov.cn/sj/zxfb/index.html",
                '<a href="energy.html">2026年6月份能源生产情况</a>',
            ),
            (
                "https://www.stats.gov.cn/sj/zxfb/index_1.html",
                '<a href="industry.html">2026年6月份规模以上工业增加值增长</a>',
            ),
        ]
        with patch.object(
            energy_service,
            "fetch_nbs_release_index_pages",
            new=AsyncMock(return_value=pages),
        ) as fetch_indexes:
            shared_pages = await energy_service.fetch_nbs_release_index_pages(object())
            energy = await energy_service.find_nbs_release_links(
                object(),
                "能源生产情况",
                index_pages=shared_pages,
            )
            industry = await energy_service.find_nbs_release_links(
                object(),
                "规模以上工业增加值增长",
                index_pages=shared_pages,
            )

        fetch_indexes.assert_awaited_once()
        self.assertEqual(len(energy), 1)
        self.assertEqual(len(industry), 1)


if __name__ == "__main__":
    unittest.main()
