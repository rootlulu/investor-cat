from __future__ import annotations

import os
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


def test_ensure_session_stops_partial_playwright_on_launch_failure(monkeypatch, tmp_path):
    stopped = {"value": False}

    class _Chromium:
        def launch_persistent_context(self, *args, **kwargs):
            raise RuntimeError("libnspr4.so: cannot open shared object file")

    class _Playwright:
        chromium = _Chromium()

        def stop(self):
            stopped["value"] = True

    class _Manager:
        def start(self):
            return _Playwright()

    monkeypatch.setattr(bs, "_CONTEXT", None)
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
