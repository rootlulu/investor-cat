from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from src import browser_service as bs


def test_summarize_browser_error_maps_known_errors():
    assert "Playwright Chromium" in bs.summarize_browser_error(Exception("Executable doesn't exist"))
    assert "profile" in bs.summarize_browser_error(Exception("ProcessSingleton lock held"))
    assert "超时" in bs.summarize_browser_error(Exception("Timeout waiting for selector"))
    assert "主动断开" in bs.summarize_browser_error(Exception("net::ERR_CONNECTION_CLOSED at https://xueqiu.com"))
    assert "系统运行库" in bs.summarize_browser_error(Exception("error while loading shared libraries: libnss3.so"))


def test_summarize_browser_error_passthrough_unknown():
    msg = bs.summarize_browser_error(Exception("some weird thing happened"))
    assert "some weird thing happened" in msg


def test_browser_fetch_retries_only_transient_errors_with_policy_backoff(monkeypatch):
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("connection reset")
        return "ok"

    monkeypatch.setattr(bs, "_run_on_browser_thread", lambda callback: callback())
    monkeypatch.setattr(bs, "_safe_reset_session", lambda: None)
    sleep = patch.object(bs.time, "sleep").start()
    retry_delay = patch.object(bs.REQUEST_COORDINATOR, "retry_delay", return_value=0.25).start()
    try:
        assert bs._run_browser_fetch(fetch, "https://example.com", retries=1) == "ok"
    finally:
        patch.stopall()

    assert calls == 2
    retry_delay.assert_called_once_with("https://example.com", 0)
    sleep.assert_called_once_with(0.25)


def test_browser_fetch_does_not_retry_content_errors(monkeypatch):
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        raise ValueError("invalid response shape")

    monkeypatch.setattr(bs, "_run_on_browser_thread", lambda callback: callback())
    monkeypatch.setattr(bs, "_safe_reset_session", lambda: None)
    sleep = patch.object(bs.time, "sleep").start()
    try:
        with pytest.raises(ValueError, match="invalid response shape"):
            bs._run_browser_fetch(fetch, "https://example.com", retries=1)
    finally:
        patch.stopall()

    assert calls == 1
    sleep.assert_not_called()


def test_summarize_browser_error_interactive_login_hint_overrides():
    hint = "雪球需要可交互浏览器登录/滑块验证；请用 config/xueqiu_settings.json: browser.headless=false"
    # 命中「需要可交互浏览器」/「已打开浏览器等待」时直接返回业务方提示
    assert bs.summarize_browser_error(Exception("已打开浏览器等待 60 秒但仍未通过"), interactive_login_hint=hint) == hint
    assert bs.summarize_browser_error(Exception("雪球需要可交互浏览器登录"), interactive_login_hint=hint) == hint
    # 未命中时仍走通用映射（Timeout 仍返回超时信息，而非 hint）
    assert bs.summarize_browser_error(Exception("Timeout waiting for selector"), interactive_login_hint=hint) != hint


def test_summarize_browser_error_truncates_long_messages():
    long_msg = "x" * 500
    out = bs.summarize_browser_error(Exception(long_msg))
    assert out.endswith("...")
    assert len(out) <= 224


def test_is_risk_control_page_defaults_match_xueqiu():
    assert bs.is_risk_control_page("<html><body>aliyun_waf challenge</body></html>")
    assert bs.is_risk_control_page("<html>访问验证 请完成</html>")
    assert bs.is_risk_control_page("滑动验证 slider")
    assert bs.is_risk_control_page("")
    assert not bs.is_risk_control_page('{"response":{"player_count":123}}')


def test_is_risk_control_page_custom_tokens():
    assert bs.is_risk_control_page("<html>请输入图形验证码</html>", tokens=("图形验证码",))
    assert not bs.is_risk_control_page("plain json response", tokens=("图形验证码",))


def test_apply_browser_library_path_injects_env(monkeypatch):
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    bs.apply_browser_library_path(Path("/tmp/fake-lib"))
    assert "fake-lib" in os.environ["LD_LIBRARY_PATH"]


def test_apply_browser_library_path_skips_missing(monkeypatch):
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    bs.apply_browser_library_path(Path("/tmp/nope"))
    assert os.environ.get("LD_LIBRARY_PATH", "") == ""


def test_load_browser_settings_reads_config():
    settings = bs.load_browser_settings()
    assert isinstance(settings, dict)
    assert settings.get("headless") in (True, False)
    assert settings.get("channel") == "chromium"


def test_browser_available_returns_bool():
    assert isinstance(bs.browser_available(), bool)


class _FakePage:
    def __init__(self, html: str) -> None:
        self._html = html

    def goto(self, *args, **kwargs):
        return None

    def content(self):
        return self._html

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def close(self):
        return None


class _FakeContext:
    def __init__(self, html: str, json_data: dict) -> None:
        self._html = html
        self._json = json_data

    def set_default_timeout(self, *args, **kwargs):
        return None

    def set_extra_http_headers(self, *args, **kwargs):
        return None

    def new_page(self):
        return _FakePage(self._html)

    @property
    def request(self):
        json_data = self._json

        class _Resp:
            def json(self):
                return json_data

        class _Req:
            def get(self, url, timeout=None):
                return _Resp()

        return _Req()


def test_fetch_html_via_browser_uses_session(monkeypatch):
    ctx = _FakeContext("<div data-appid='730'>x</div>", {})
    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: ctx)
    html = bs.fetch_html_via_browser("https://store.steampowered.com/charts/topselling/us")
    assert "data-appid" in html


def test_fetch_json_via_browser_uses_session(monkeypatch):
    ctx = _FakeContext("", {"response": {"player_count": 123}})
    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: ctx)
    data = bs.fetch_json_via_browser("https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=730")
    assert data["response"]["player_count"] == 123


def test_fetch_html_via_browser_retries_on_failure(monkeypatch):
    ctx = _FakeContext("<div data-appid='570'>y</div>", {})
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("browser crashed")
        return ctx

    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: flaky())
    html = bs.fetch_html_via_browser("https://store.steampowered.com/charts/topselling/global")
    assert "data-appid" in html
    assert calls["n"] == 2


def test_resolve_browser_proxy_only_matches_configured_hosts(monkeypatch):
    monkeypatch.delenv("BROWSER_PROXY_SERVER", raising=False)
    monkeypatch.setattr(
        bs,
        "_settings",
        lambda: {
            "proxy": {
                "enabled": True,
                "server": "http://172.19.128.1:7897",
                "hosts": ["store.steampowered.com"],
            }
        },
    )
    assert bs.resolve_browser_proxy("https://store.steampowered.com/charts/topselling/global") == {
        "server": "http://172.19.128.1:7897"
    }
    assert bs.resolve_browser_proxy("https://api.steampowered.com/test") is None
    assert bs.resolve_browser_proxy("https://steamcharts.com/app/730") is None


def test_resolve_browser_proxy_auto_detects_wsl_host(monkeypatch):
    monkeypatch.delenv("BROWSER_PROXY_SERVER", raising=False)
    monkeypatch.setattr(
        bs,
        "_settings",
        lambda: {
            "proxy": {
                "enabled": True,
                "autoDetectWslHost": True,
                "port": 7897,
                "hosts": ["store.steampowered.com"],
            }
        },
    )
    monkeypatch.setattr(bs, "_wsl_windows_host", lambda: "172.19.128.1")
    assert bs.resolve_browser_proxy("https://store.steampowered.com/charts/topselling/global") == {
        "server": "http://172.19.128.1:7897"
    }


def test_v37_fetch_calls_share_one_worker_thread():
    caller_ids: set[int] = set()

    def invoke(_: int) -> int:
        caller_ids.add(threading.get_ident())
        return bs._run_on_browser_thread(threading.get_ident)

    with ThreadPoolExecutor(max_workers=4) as callers:
        worker_ids = list(callers.map(invoke, range(12)))

    assert len(caller_ids) > 1
    assert len(set(worker_ids)) == 1
    assert worker_ids[0] not in caller_ids


def test_v38_automated_session_uses_non_persistent_context(monkeypatch, tmp_path):
    events: list[tuple[str, object]] = []

    class _Context:
        def set_extra_http_headers(self, headers):
            events.append(("headers", headers))

        def close(self):
            events.append(("context.close", None))

    context = _Context()

    class _Browser:
        def new_context(self, **kwargs):
            events.append(("new_context", kwargs))
            return context

        def close(self):
            events.append(("browser.close", None))

    class _Chromium:
        def launch(self, **kwargs):
            events.append(("launch", kwargs))
            return _Browser()

        def launch_persistent_context(self, *args, **kwargs):
            raise AssertionError("automated fetch must not use a persistent profile")

    class _Playwright:
        chromium = _Chromium()

        def stop(self):
            events.append(("playwright.stop", None))

    class _Manager:
        def start(self):
            return _Playwright()

    monkeypatch.setattr(bs, "_CONTEXT", None)
    monkeypatch.setattr(bs, "_BROWSER", None, raising=False)
    monkeypatch.setattr(bs, "_PLAYWRIGHT", None)
    monkeypatch.setattr(bs, "_CONTEXT_PROXY_KEY", None)
    monkeypatch.setattr(
        bs,
        "_settings",
        lambda: {
            "profileDir": str(tmp_path / "must-not-be-used"),
            "headless": True,
            "channel": "chromium",
        },
    )
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: _Manager())

    proxy = {"server": "http://172.19.128.1:7897"}
    assert bs._ensure_session(proxy) is context
    launch_options = next(value for name, value in events if name == "launch")
    assert launch_options["proxy"] == proxy
    assert any(name == "new_context" for name, _ in events)

    bs._safe_reset_session()
    assert ("context.close", None) in events
    assert ("browser.close", None) in events
    assert ("playwright.stop", None) in events


def test_ensure_session_stops_partial_playwright_on_launch_failure(monkeypatch, tmp_path):
    stopped = {"value": False}

    class _Chromium:
        def launch(self, *args, **kwargs):
            raise RuntimeError("libnspr4.so: cannot open shared object file")

    class _Playwright:
        chromium = _Chromium()

        def stop(self):
            stopped["value"] = True

    class _Manager:
        def start(self):
            return _Playwright()

    monkeypatch.setattr(bs, "_CONTEXT", None)
    monkeypatch.setattr(bs, "_BROWSER", None)
    monkeypatch.setattr(bs, "_PLAYWRIGHT", None)
    monkeypatch.setattr(bs, "_CONTEXT_PROXY_KEY", None)
    monkeypatch.setattr(bs, "_settings", lambda: {"profileDir": str(tmp_path / "profile")})
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: _Manager())

    with pytest.raises(RuntimeError, match="libnspr4"):
        bs._ensure_session()
    assert stopped["value"] is True
    assert bs._PLAYWRIGHT is None
    assert bs._CONTEXT is None


def test_fetch_page_json_response_via_browser(monkeypatch):
    payload = {"response": {"ranks": [{"rank": 1, "appid": 730}]}}

    class _Response:
        url = "https://api.steampowered.com/IStoreTopSellersService/GetWeeklyTopSellers/v1"
        ok = True
        status = 200
        headers = {"content-type": "application/json; charset=UTF-8"}

        def json(self):
            return payload

    class _ResponseInfo:
        value = _Response()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class _ResponsePage(_FakePage):
        def expect_response(self, predicate, timeout=None):
            assert predicate(_Response())
            return _ResponseInfo()

    class _ResponseContext(_FakeContext):
        def new_page(self):
            return _ResponsePage("")

    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: _ResponseContext("", {}))
    result = bs.fetch_page_json_response_via_browser(
        "https://store.steampowered.com/charts/topselling/global",
        "IStoreTopSellersService/GetWeeklyTopSellers",
    )
    assert result == payload


def test_v40_binary_service_response_is_refetched_as_json(monkeypatch):
    payload = {"response": {"ranks": [{"rank": 1, "appid": 730}]}}
    requested_urls: list[str] = []

    class _BinaryResponse:
        url = (
            "https://api.steampowered.com/"
            "IStoreTopSellersService/GetWeeklyTopSellers/v1?input_protobuf_encoded=abc%3D"
        )
        ok = True
        status = 200
        headers = {"content-type": "application/octet-stream"}

        def json(self):
            raise AssertionError("protobuf response must not be decoded as UTF-8 JSON")

    class _JsonResponse:
        url = _BinaryResponse.url + "&format=json"
        ok = True
        status = 200
        headers = {"content-type": "application/json; charset=UTF-8"}

        def json(self):
            return payload

    class _ResponseInfo:
        value = _BinaryResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class _ResponsePage(_FakePage):
        def expect_response(self, predicate, timeout=None):
            assert predicate(_BinaryResponse())
            return _ResponseInfo()

    class _ResponseContext(_FakeContext):
        def new_page(self):
            return _ResponsePage("")

        @property
        def request(self):
            class _Request:
                def get(self, url, timeout=None):
                    requested_urls.append(url)
                    return _JsonResponse()

            return _Request()

    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: _ResponseContext("", {}))
    result = bs.fetch_page_json_response_via_browser(
        "https://store.steampowered.com/charts/topselling/global",
        "IStoreTopSellersService/GetWeeklyTopSellers",
    )

    assert result == payload
    assert requested_urls == [_BinaryResponse.url + "&format=json"]


def test_page_json_response_can_select_and_transform_matching_service_call(monkeypatch):
    payload = {"response": {"ids": [{"appid": 3240220}]}}
    requested_urls: list[str] = []

    class _WrongResponse:
        url = "https://api.steampowered.com/IStoreTopSellersService/GetWeeklyTopSellers/v1?scope=SG"

    class _TargetResponse:
        url = "https://api.steampowered.com/IStoreTopSellersService/GetWeeklyTopSellers/v1?scope=global&count=20"
        ok = True
        status = 200
        headers = {"content-type": "application/octet-stream"}

    class _JsonResponse:
        url = _TargetResponse.url
        ok = True
        status = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return payload

    class _ResponseInfo:
        value = _TargetResponse()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class _ResponsePage(_FakePage):
        def expect_response(self, predicate, timeout=None):
            assert predicate(_WrongResponse()) is False
            assert predicate(_TargetResponse()) is True
            return _ResponseInfo()

    class _ResponseContext(_FakeContext):
        def new_page(self):
            return _ResponsePage("")

        @property
        def request(self):
            class _Request:
                def get(self, url, timeout=None):
                    requested_urls.append(url)
                    return _JsonResponse()

            return _Request()

    monkeypatch.setattr(bs, "_ensure_session", lambda proxy=None: _ResponseContext("", {}))

    result = bs.fetch_page_json_response_via_browser(
        "https://store.steampowered.com/charts/topsellers/global/2026-7-14",
        "IStoreTopSellersService/GetWeeklyTopSellers",
        response_url_predicate=lambda url: "scope=global" in url,
        response_url_transform=lambda url: url.replace("count=20", "count=100"),
    )

    assert result == payload
    assert requested_urls == [
        "https://api.steampowered.com/IStoreTopSellersService/GetWeeklyTopSellers/v1?scope=global&count=100&format=json"
    ]
