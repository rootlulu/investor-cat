from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from src.game_provider_service import (
    GameProviderError,
    build_provider_browser_command,
    enforce_crawl_policy,
    merge_ranking_rows,
    normalize_extracted_rows,
    prepare_provider_login_window,
    provider_rank_url,
)


class GameProviderServiceTests(unittest.TestCase):
    def test_login_browser_command_opens_a_visible_app_window(self) -> None:
        url = "https://example.test/login"
        command = build_provider_browser_command(
            "/opt/chromium",
            Path("/tmp/provider-profile"),
            url,
            port=9222,
            visible=True,
        )

        self.assertIn("--window-position=120,80", command)
        self.assertIn(f"--app={url}", command)
        self.assertNotIn("--window-position=-32000,-32000", command)

    def test_crawl_browser_command_stays_off_screen(self) -> None:
        url = "https://example.test/rank"
        command = build_provider_browser_command(
            "/opt/chromium",
            Path("/tmp/provider-profile"),
            url,
            port=9222,
            visible=False,
        )

        self.assertIn("--window-position=-32000,-32000", command)
        self.assertIn(url, command)
        self.assertNotIn(f"--app={url}", command)

    def test_diandian_login_switches_to_qr_code(self) -> None:
        page = MagicMock()
        qr_button = MagicMock()
        qr_button.count.return_value = 1
        qr_button.last.is_visible.return_value = True
        qr_image = MagicMock()
        qr_image.count.side_effect = [0, 1]
        qr_image.last.is_visible.return_value = True
        page.get_by_text.return_value = qr_button
        page.locator.return_value = qr_image

        self.assertTrue(prepare_provider_login_window(page, "diandian"))

        page.get_by_text.assert_called_once_with("QR Code", exact=True)
        qr_button.last.click.assert_called_once_with(timeout=3000)
        page.locator.assert_called_once_with("img.qr-img, img[src*='mp.weixin.qq.com/cgi-bin/showqrcode']")
        page.wait_for_timeout.assert_called_once_with(500)

    def test_provider_rank_urls_are_allowlisted(self) -> None:
        self.assertTrue(provider_rank_url("qimai", "us", "free").endswith("/brand/free/genre/6014/device/iphone/country/us"))
        self.assertTrue(provider_rank_url("diandian", "cn", "grossing").endswith("/1-2-172-75-4"))
        with self.assertRaises(GameProviderError):
            provider_rank_url("diandian", "de", "free")

    def test_normalize_extracted_rows_deduplicates_ranks(self) -> None:
        rows = normalize_extracted_rows(
            [
                {"rank": 1, "title": "游戏 A", "href": "https://example.test/app/demo/appid/123456", "lines": ["1", "游戏 A", "厂商 A"]},
                {"rank": 1, "title": "重复项", "href": "https://example.test/app/duplicate", "lines": ["1", "重复项"]},
                {"rank": 2, "title": "游戏 B", "href": "https://example.test/app/demo/appid/654321", "lines": ["2", "游戏 B", "厂商 B"]},
            ],
            "qimai",
            "cn",
            "free",
            "https://example.test/rank",
        )
        self.assertEqual([(row["rank"], row["game"]) for row in rows], [(1, "游戏 A"), (2, "游戏 B")])
        self.assertEqual(rows[0]["publisher"], "厂商 A")

    def test_merge_ranking_rows_replaces_only_matching_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rankings.json"
            path.write_text(
                json.dumps(
                    [
                        {"provider": "qimai", "country_code": "cn", "chart": "free", "rank": 1, "game": "旧数据"},
                        {"provider": "diandian", "country_code": "cn", "chart": "free", "rank": 1, "game": "保留数据"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            merge_ranking_rows(
                [{"provider": "qimai", "country_code": "cn", "chart": "free", "rank": 1, "game": "新数据"}],
                path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual({row["game"] for row in payload}, {"新数据", "保留数据"})

    def test_crawl_policy_rejects_immediate_repeat(self) -> None:
        state = {"providers": {"qimai": {"lastAttemptAt": datetime.now(UTC).isoformat()}}}
        with self.assertRaisesRegex(GameProviderError, "低频保护"):
            enforce_crawl_policy("qimai", state)


if __name__ == "__main__":
    unittest.main()
