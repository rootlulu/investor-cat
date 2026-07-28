import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from src import xueqiu_service as xueqiu
from src.xueqiu_service import (
    XUEQIU_AUTH_SESSION,
    XUEQIU_CACHE,
    XUEQIU_SEARCH_CACHE,
    fetch_xueqiu_json,
    get_xueqiu,
    get_xueqiu_auth_status_sync,
    normalize_xueqiu_avatar_url,
    search_user_profiles_sync,
    search_xueqiu_users,
)


class XueqiuSnapshotCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_cache_keeps_last_refreshed_activities_visible(self) -> None:
        previous_cache = dict(XUEQIU_CACHE)
        refreshed_activity = {"id": "activity-1", "text": "启动刷新抓到的动态"}
        XUEQIU_CACHE.update(
            {
                "expires_at": time.time() - 1,
                "data": {
                    "generatedAt": "2026-07-25T13:38:18+00:00",
                    "activities": [refreshed_activity],
                    "hasData": True,
                },
            }
        )

        try:
            with patch("src.xueqiu_service.build_xueqiu_snapshot") as build_empty_snapshot:
                data = await get_xueqiu()
        finally:
            XUEQIU_CACHE.clear()
            XUEQIU_CACHE.update(previous_cache)

        self.assertEqual(data["activities"], [refreshed_activity])
        self.assertTrue(data["cached"])
        self.assertTrue(data["stale"])
        build_empty_snapshot.assert_not_called()

    async def test_concurrent_refreshes_share_one_fetch(self) -> None:
        previous_cache = dict(XUEQIU_CACHE)
        fetch_count = 0

        def fetch_once() -> dict:
            nonlocal fetch_count
            fetch_count += 1
            time.sleep(0.05)
            return {"generatedAt": "now", "activities": [], "hasData": True}

        XUEQIU_CACHE.update({"expires_at": 0.0, "data": None})
        try:
            with patch.object(xueqiu, "fetch_xueqiu_sync", side_effect=fetch_once):
                results = await asyncio.gather(
                    get_xueqiu(refresh=True, force=True),
                    get_xueqiu(refresh=True, force=True),
                    get_xueqiu(refresh=True, force=True),
                )
        finally:
            XUEQIU_CACHE.clear()
            XUEQIU_CACHE.update(previous_cache)
            xueqiu.XUEQIU_REFRESH_TASK = None

        self.assertEqual(fetch_count, 1)
        self.assertEqual(results[0], results[1])

    async def test_identical_searches_share_one_fetch(self) -> None:
        previous_cache = dict(XUEQIU_SEARCH_CACHE)
        fetch_count = 0

        def search_once(_nickname: str, _limit: int):
            nonlocal fetch_count
            fetch_count += 1
            time.sleep(0.05)
            return ([{"userId": "1", "name": "测试"}], [])

        XUEQIU_SEARCH_CACHE.clear()
        try:
            with patch.object(xueqiu, "search_user_profiles_sync", side_effect=search_once):
                results = await asyncio.gather(
                    search_xueqiu_users("测试"),
                    search_xueqiu_users("测试"),
                )
        finally:
            XUEQIU_SEARCH_CACHE.clear()
            XUEQIU_SEARCH_CACHE.update(previous_cache)

        self.assertEqual(fetch_count, 1)
        self.assertEqual(results[0], results[1])

    async def test_cancelled_search_keeps_its_singleflight_fetch_running(self) -> None:
        previous_cache = dict(XUEQIU_SEARCH_CACHE)
        started = threading.Event()
        release = threading.Event()
        fetch_count = 0

        def search_once(_nickname: str, _limit: int):
            nonlocal fetch_count
            fetch_count += 1
            started.set()
            release.wait(timeout=1)
            return ([{"userId": "1", "name": "测试"}], [])

        XUEQIU_SEARCH_CACHE.clear()
        try:
            with patch.object(xueqiu, "search_user_profiles_sync", side_effect=search_once):
                first = asyncio.create_task(search_xueqiu_users("测试"))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release.set()
                result = await asyncio.wait_for(search_xueqiu_users("测试"), timeout=1)
        finally:
            release.set()
            XUEQIU_SEARCH_CACHE.clear()
            XUEQIU_SEARCH_CACHE.update(previous_cache)

        self.assertEqual(fetch_count, 1)
        self.assertEqual(result["suggestions"][0]["userId"], "1")


class XueqiuRequestProtectionTests(unittest.TestCase):
    def test_headed_browser_fallback_is_reachable(self) -> None:
        class Response:
            status_code = 200
            headers = {}
            text = "not-json"
            encoding = ""

        class Session:
            def get(self, *_args, **_kwargs):
                return Response()

        def run_request(_url, operation, **_kwargs):
            return operation()

        with (
            patch.object(xueqiu.REQUEST_COORDINATOR, "run_sync", side_effect=run_request),
            patch.object(xueqiu, "xueqiu_browser_enabled", return_value=True),
            patch.object(xueqiu, "xueqiu_browser_headless", return_value=False),
            patch.object(xueqiu, "get_recent_xueqiu_browser_failure", return_value=""),
            patch.object(
                xueqiu,
                "fetch_xueqiu_json_with_browser_sync",
                return_value={"statuses": []},
            ) as browser_fetch,
            patch.object(xueqiu, "apply_xueqiu_cookie_header"),
        ):
            payload = fetch_xueqiu_json(Session(), "https://api.xueqiu.com/test")

        self.assertEqual(payload, {"statuses": []})
        browser_fetch.assert_called_once()

    def test_qr_status_remote_probe_is_throttled_to_fifteen_seconds(self) -> None:
        previous_session = dict(XUEQIU_AUTH_SESSION)
        XUEQIU_AUTH_SESSION.clear()
        XUEQIU_AUTH_SESSION.update(
            {
                "context": object(),
                "qrDataUrl": "data:image/png;base64,abc",
                "startedAt": "now",
                "expiresAt": 1000.0,
                "lastRemoteProbeAt": 0.0,
                "message": "pending",
            }
        )
        try:
            with (
                patch.object(xueqiu.time, "time", side_effect=[100.0, 105.0, 115.0]),
                patch.object(xueqiu, "xueqiu_auth_probe_succeeded", return_value=False) as probe,
            ):
                first = get_xueqiu_auth_status_sync()
                second = get_xueqiu_auth_status_sync()
                third = get_xueqiu_auth_status_sync()
        finally:
            XUEQIU_AUTH_SESSION.clear()
            XUEQIU_AUTH_SESSION.update(previous_session)

        self.assertEqual([first["status"], second["status"], third["status"]], ["pending"] * 3)
        self.assertEqual(probe.call_count, 2)


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
