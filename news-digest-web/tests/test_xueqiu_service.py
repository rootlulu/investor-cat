import unittest
from unittest.mock import patch

from src.xueqiu_service import normalize_xueqiu_avatar_url, search_user_profiles_sync


class XueqiuUserSearchTests(unittest.TestCase):
    def test_avatar_url_selects_medium_image_and_adds_host(self) -> None:
        raw = (
            "community/20234/avatar.jpeg,"
            "community/20234/avatar.jpeg!180x180.png,"
            "community/20234/avatar.jpeg!50x50.png"
        )

        self.assertEqual(
            normalize_xueqiu_avatar_url(raw),
            "https://xavatar.imedao.com/community/20234/avatar.jpeg!180x180.png",
        )

    def test_search_returns_deduplicated_candidates_and_imported_state(self) -> None:
        imported = {
            "userId": "100001",
            "name": "雪球老张",
            "description": "已关注用户",
            "followersCount": 1200,
        }
        payload = {
            "users": [
                {
                    "id": "100002",
                    "screen_name": "老张投资笔记",
                    "description": "记录投资研究",
                    "followers_count": 3456,
                    "verified": True,
                    "profile_image_url": "https://example.com/avatar.jpg",
                },
                {"id": "100002", "screen_name": "重复结果"},
            ]
        }

        with (
            patch("src.xueqiu_service.create_xueqiu_session", return_value=object()),
            patch("src.xueqiu_service.load_influencers_config", return_value=[imported]),
            patch("src.xueqiu_service.fetch_user_profile_by_nickname_url_sync", return_value={}),
            patch("src.xueqiu_service.fetch_xueqiu_json", return_value=payload),
        ):
            suggestions, errors = search_user_profiles_sync("老张", 6)

        self.assertEqual(errors, [])
        self.assertEqual([item["userId"] for item in suggestions], ["100001", "100002"])
        self.assertTrue(suggestions[0]["imported"])
        self.assertFalse(suggestions[1]["imported"])
        self.assertTrue(suggestions[1]["verified"])
        self.assertEqual(suggestions[1]["avatarUrl"], "https://example.com/avatar.jpg")

    def test_direct_user_id_returns_single_profile(self) -> None:
        profile = {"userId": "1234567890", "name": "测试用户"}
        with (
            patch("src.xueqiu_service.create_xueqiu_session", return_value=object()),
            patch("src.xueqiu_service.load_influencers_config", return_value=[]),
            patch("src.xueqiu_service.fetch_user_profile_sync", return_value=profile),
        ):
            suggestions, errors = search_user_profiles_sync("1234567890", 6)

        self.assertEqual(errors, [])
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["name"], "测试用户")


if __name__ == "__main__":
    unittest.main()
