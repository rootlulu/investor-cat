from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src import game_region_service as svc
from src.game_region_service import (
    clean_html,
    load_region_games,
    load_region_regions,
    parse_int,
    parse_steamcharts_html,
    parse_topselling_appids,
    parse_topselling_payload,
    resolve_region,
)


def test_parse_int():
    assert parse_int("123,456") == 123456
    assert parse_int("  -7 ") == -7
    assert parse_int("n/a") is None
    assert parse_int(None) is None
    assert parse_int("") is None


def test_clean_html():
    assert clean_html("<td>Hello <b>World</b></td>") == "Hello World"
    assert clean_html("\n  spaced  \n") == "spaced"


def test_parse_topselling_appids_dedupes():
    html = '<div data-appid="730"></div><div data-appid="570"></div><div data-appid="730"></div>'
    assert parse_topselling_appids(html) == ["730", "570"]


def test_parse_topselling_appids_falls_back_to_app_path():
    html = '<a href="https://store.steampowered.com/app/440/">TF2</a>'
    assert parse_topselling_appids(html) == ["440"]


def test_parse_topselling_payload_extracts_ordered_appids():
    payload = {
        "response": {
            "ranks": [
                {"rank": 1, "appid": 730},
                {"rank": 2, "appid": "570"},
                {"rank": 3, "appid": 730},
            ]
        }
    }
    assert parse_topselling_payload(payload) == ["730", "570"]


def test_v50_live_topsellers_preserve_non_app_positions():
    payload = {
        "response": {
            "ids": [
                {"appid": 730},
                {"packageid": 886313},
                {"appid": 3240220},
                {"appid": 1974050},
            ]
        }
    }

    assert svc.parse_live_topselling_payload(payload) == {
        "730": 1,
        "3240220": 3,
        "1974050": 4,
    }


def test_v51_weekly_topsellers_keep_upstream_rank_gaps():
    payload = {
        "response": {
            "ranks": [
                {"rank": 9, "appid": 578080},
                {"rank": 16, "appid": 3240220},
                {"rank": 72, "appid": 1974050},
            ]
        }
    }

    assert svc.parse_weekly_topselling_payload(payload) == {
        "578080": 9,
        "3240220": 16,
        "1974050": 72,
    }


def test_v52_monthly_top_releases_keep_official_tiers():
    payload = {
        "response": {
            "top_dlc_releases": [{"appid": 999, "app_release_rank": 1}],
            "top_combined_app_and_dlc_releases": [
                {"appid": 730, "app_release_rank": 1},
                {"appid": 570, "app_release_rank": 2},
                {"appid": 1974050, "app_release_rank": 3},
                {"appid": 440, "app_release_rank": 9},
            ],
        }
    }

    assert svc.parse_monthly_top_releases_payload(payload) == {
        "730": 1,
        "570": 2,
        "1974050": 3,
    }


def test_v51_v52_periods_respect_steam_publish_cutoffs():
    assert svc.latest_completed_steam_week(
        datetime(2026, 7, 21, 7, 30, tzinfo=UTC)
    ).isoformat() == "2026-07-07"
    assert svc.latest_completed_steam_week(
        datetime(2026, 7, 21, 8, 30, tzinfo=UTC)
    ).isoformat() == "2026-07-14"
    assert svc.latest_published_steam_month(
        datetime(2026, 7, 15, 3, 0, tzinfo=UTC)
    ).isoformat() == "2026-05-01"
    assert svc.latest_published_steam_month(
        datetime(2026, 7, 15, 17, 0, tzinfo=UTC)
    ).isoformat() == "2026-06-01"


def test_parse_steamcharts_html_keeps_monthly_rows():
    html = """
    <table>
      <tr><td>Last 30 Days</td><td>120,000</td><td>+1,000</td><td>+1%</td><td>200,000</td></tr>
      <tr><td>July 2026</td><td>110,500</td><td>-5,000</td><td>-4%</td><td>190,000</td></tr>
      <tr><td>June 2026</td><td>115,000</td><td>-2,000</td><td>-2%</td><td>185,000</td></tr>
    </table>
    """
    series = parse_steamcharts_html(html)
    months = {row["month"] for row in series}
    assert months == {"2026-06", "2026-07"}
    july = next(row for row in series if row["month"] == "2026-07")
    assert july["avg"] == 110500
    assert july["peak"] == 190000


def test_v41_steamcharts_decimal_average_is_rounded_and_months_are_ascending():
    html = """
    <table>
      <tr><td>July 2026</td><td>916,654.5</td><td>+1,000</td><td>+1%</td><td>1,573,727</td></tr>
      <tr><td>June 2026</td><td>900,000.4</td><td>-5,000</td><td>-1%</td><td>1,500,000</td></tr>
    </table>
    """

    series = parse_steamcharts_html(html)

    assert series == [
        {"month": "2026-06", "avg": 900000, "peak": 1500000},
        {"month": "2026-07", "avg": 916655, "peak": 1573727},
    ]


def test_load_region_games_and_regions_from_config():
    # 注：从 //wsl.localhost 挂载读取可能有写后缓存波动，这里只做宽松结构校验；
    # 手游 null-appId 的精确行为由 test_load_region_games_handles_null_appid 用内存 config 验证。
    games = load_region_games({})
    assert len(games) >= 25
    assert all(game["appId"] is None or isinstance(game["appId"], int) for game in games)
    regions = load_region_regions({})
    assert len(regions) >= 30
    codes = [region["code"] for region in regions]
    assert codes[0] == "global"
    assert len(set(codes)) == len(codes)


def test_load_region_games_handles_null_appid(monkeypatch):
    # load_region_games 以磁盘 watchlist 为准，这里用内存数据绕过文件，验证 null-appId 逻辑
    my_games = [
        {"appId": 730, "name": "CS2", "nameZh": "反恐精英 2", "group": "global"},
        {"appId": None, "name": "Xindong Xiaozhen", "nameZh": "心动小镇", "group": "cn", "platforms": ["mobile"]},
        {"appId": 0, "name": "Zero", "nameZh": "零", "group": "cn"},
    ]
    monkeypatch.setattr(svc, "load_region_config_file", lambda: {"games": my_games})
    games = load_region_games({})
    assert len(games) == 3
    by_zh = {game["nameZh"]: game for game in games}
    # 无 appId 的手游保留为「未披露」行，并携带 platforms 标记
    assert by_zh["心动小镇"]["appId"] is None
    assert "mobile" in by_zh["心动小镇"]["platforms"]
    # appId=0 视为无效，同样作为未披露行保留（不丢弃）
    assert by_zh["零"]["appId"] is None
    # 有 appId 的 Steam 游戏正常
    assert by_zh["反恐精英 2"]["appId"] == 730


def test_resolve_region_normalizes_and_falls_back():
    regions = [
        {"code": "global", "name": "全球"},
        {"code": "us", "name": "美国"},
    ]
    assert resolve_region("US", regions) == ("us", "美国")
    assert resolve_region("unknown", regions) == ("global", "全球")


def test_get_region_games_builds_payload_with_mocks():
    store: dict[str, object] = {}

    def fake_load(db_path, region):
        return store.get(region)

    def fake_save(db_path, region, payload):
        store[region] = payload

    with patch.object(svc, "fetch_steam_live_topselling", return_value=({"730": 1, "570": 2}, None)) as live_fetch, patch.object(
        svc,
        "fetch_steam_weekly_topselling",
        return_value=({"570": 7, "730": 9}, None, "2026-07-14 至 2026-07-21"),
    ) as weekly_fetch, patch.object(
        svc,
        "fetch_steam_monthly_top_releases",
        return_value=({"730": 1}, None, "2026-06"),
    ) as monthly_fetch, patch.object(
        svc, "fetch_steam_current_players", return_value=100
    ), patch.object(
        svc,
        "fetch_steamcharts_history",
        return_value=([{"month": "2026-07", "avg": 50, "peak": 80}], None),
    ), patch.object(svc, "load_region_cache", side_effect=fake_load), patch.object(
        svc, "save_region_cache", side_effect=fake_save
    ):
        payload = asyncio.run(svc.get_region_games(cc="us", refresh=True))
        cached = asyncio.run(svc.get_region_games(cc="us"))

    live_fetch.assert_awaited_with("us", svc.STEAM_RANKING_TIMEOUT)
    weekly_fetch.assert_awaited_with("us", svc.STEAM_RANKING_TIMEOUT)
    monthly_fetch.assert_awaited_with(svc.STEAM_RANKING_TIMEOUT)

    assert payload["region"] == "us"
    assert payload["regionName"] == "美国"
    assert payload["schemaVersion"] == svc.GAME_REGION_SCHEMA_VERSION
    assert len(payload["games"]) >= 25

    ranked = [game for game in payload["games"] if game["rank"] is not None]
    assert ranked[0]["rank"] == 1
    assert ranked[0]["appId"] in (730, 570)
    assert ranked[0]["currentPlayers"] == 100
    assert ranked[0]["monthly"][0]["avg"] == 50
    assert ranked[0]["status"]["topselling"] == "ok"
    assert ranked[0]["liveRank"] == 1
    assert ranked[0]["weeklyRank"] == 9
    assert ranked[0]["monthlyTier"] == 1
    assert ranked[0]["status"]["players"] == "ok"
    assert payload["rankings"]["live"]["valueKind"] == "rank"
    assert payload["rankings"]["monthly"]["valueKind"] == "tier"

    assert cached["cached"] is True
    assert cached["stale"] is False
    assert cached["region"] == "us"
    assert len(cached["games"]) == len(payload["games"])


def test_fetch_steam_current_players_none_skips_browser():
    # 无 appId 的纯手游不应触网，直接返回 None（UI 显示「未披露」）
    assert asyncio.run(svc.fetch_steam_current_players(None, 10)) is None


def test_fetch_steamcharts_history_none_skips_browser():
    rows, err = asyncio.run(svc.fetch_steamcharts_history(None, 10))
    assert rows == []
    assert err is None


def test_fetch_steam_live_topselling_uses_live_query_response(monkeypatch):
    monkeypatch.setattr(
        svc.bs,
        "fetch_page_json_response_via_browser",
        lambda url, response_url_contains, timeout_ms, **kwargs: {
            "response": {"ids": [{"appid": 730}, {"appid": 570}]}
        },
    )
    ranks, err = asyncio.run(svc.fetch_steam_live_topselling("global", 10))
    assert ranks == {"730": 1, "570": 2}
    assert err is None


def test_fetch_steam_weekly_topselling_uses_upstream_ranks(monkeypatch):
    monkeypatch.setattr(
        svc.bs,
        "fetch_page_json_response_via_browser",
        lambda url, response_url_contains, timeout_ms, **kwargs: {
            "response": {"ranks": [{"rank": 9, "appid": 730}, {"rank": 16, "appid": 570}]}
        },
    )
    ranks, err, period = asyncio.run(svc.fetch_steam_weekly_topselling("global", 10))
    assert ranks == {"730": 9, "570": 16}
    assert err is None
    assert "至" in period


def test_browser_failures_are_summarized_before_reaching_region_payload(monkeypatch):
    raw_error = (
        "BrowserType.launch_persistent_context: Failed to create a ProcessSingleton "
        "for profile.\nCall log:\n" + "x" * 500
    )

    def unavailable(*args, **kwargs):
        raise RuntimeError(raw_error)

    monkeypatch.setattr(svc.bs, "fetch_page_json_response_via_browser", unavailable)
    monkeypatch.setattr(svc.bs, "fetch_html_via_browser", unavailable)

    live_ranks, live_error = asyncio.run(svc.fetch_steam_live_topselling("global", 10))
    weekly_ranks, weekly_error, _ = asyncio.run(svc.fetch_steam_weekly_topselling("global", 10))
    monthly_tiers, monthly_error, _ = asyncio.run(svc.fetch_steam_monthly_top_releases(10))
    rows, history_error = asyncio.run(svc.fetch_steamcharts_history(730, 10))

    assert live_ranks == {}
    assert weekly_ranks == {}
    assert monthly_tiers == {}
    assert rows == []
    assert "profile" in live_error
    assert "profile" in weekly_error
    assert "profile" in monthly_error
    assert "profile" in history_error
    assert "Call log" not in live_error
    assert "Call log" not in history_error


def test_failed_refresh_keeps_last_valid_region_snapshot():
    active_catalog = {
        "revision": "same-watchlist",
        "games": [],
        "regions": [{"code": "global", "name": "全球"}, {"code": "us", "name": "美国"}],
    }
    cached = {
        "schemaVersion": svc.GAME_REGION_SCHEMA_VERSION,
        "watchlistRevision": "same-watchlist",
        "region": "us",
        "regionName": "美国",
        "generatedAt": "2026-07-25T00:00:00+00:00",
        "expiresAt": "2026-07-25T00:30:00+00:00",
        "games": [
            {
                "appId": 730,
                "rank": 1,
                "currentPlayers": 100,
                "monthly": [],
                "status": {"topselling": "ok", "players": "ok"},
            }
        ],
        "errors": [],
    }
    failed = {
        "schemaVersion": svc.GAME_REGION_SCHEMA_VERSION,
        "watchlistRevision": "same-watchlist",
        "region": "us",
        "regionName": "美国",
        "generatedAt": "2026-07-26T00:00:00+00:00",
        "expiresAt": "2026-07-26T00:30:00+00:00",
        "games": [
            {
                "appId": 730,
                "rank": None,
                "currentPlayers": None,
                "monthly": [],
                "status": {"topselling": "unavailable", "players": "unavailable"},
            }
        ],
        "errors": ["Steam unavailable"],
    }

    with patch.object(svc, "load_watchlist", return_value=active_catalog), patch.object(
        svc, "load_region_cache", return_value=cached
    ), patch.object(
        svc, "build_region_payload", return_value=failed
    ), patch.object(svc, "save_region_cache") as save:
        result = asyncio.run(svc.get_region_games(cc="us", refresh=True))

    assert result["stale"] is True
    assert result["cached"] is True
    assert result["games"][0]["currentPlayers"] == 100
    assert "Steam unavailable" in result["errors"]
    save.assert_not_called()


def test_v53_old_single_ranking_cache_is_not_reused():
    old_cache = {
        "schemaVersion": 1,
        "region": "global",
        "regionName": "全球",
        "generatedAt": "2026-07-26T00:00:00+00:00",
        "expiresAt": "2099-07-26T00:30:00+00:00",
        "games": [{"appId": 1974050, "rank": 16}],
        "errors": [],
    }
    rebuilt = {
        "schemaVersion": svc.GAME_REGION_SCHEMA_VERSION,
        "region": "global",
        "regionName": "全球",
        "generatedAt": "2026-07-26T01:00:00+00:00",
        "expiresAt": "2026-07-26T01:30:00+00:00",
        "rankings": {"live": {"status": "ok"}},
        "games": [{"appId": 1974050, "rank": 72, "liveRank": 72}],
        "errors": [],
    }

    with patch.object(svc, "load_region_cache", return_value=old_cache), patch.object(
        svc, "build_region_payload", return_value=rebuilt
    ) as build, patch.object(svc, "save_region_cache"):
        result = asyncio.run(svc.get_region_games(cc="global"))

    build.assert_awaited_once()
    assert result["schemaVersion"] == 2
    assert result["games"][0]["liveRank"] == 72


def test_fetch_steam_current_players_delegates_to_browser(monkeypatch):
    monkeypatch.setattr(
        svc.bs,
        "fetch_json_via_browser",
        lambda url, timeout_ms: {"response": {"player_count": 42}},
    )
    assert asyncio.run(svc.fetch_steam_current_players(730, 10)) == 42


def test_fetch_steamcharts_history_delegates_to_browser(monkeypatch):
    html = '<tr><td>July 2026</td><td>110,500</td><td>-5,000</td><td>-4%</td><td>190,000</td></tr>'
    monkeypatch.setattr(svc.bs, "fetch_html_via_browser", lambda url, timeout_ms: html)
    rows, err = asyncio.run(svc.fetch_steamcharts_history(730, 10))
    assert rows[0]["month"] == "2026-07"
    assert rows[0]["peak"] == 190000
    assert err is None


def test_watchlist_has_real_steam_appids_for_cn_games():
    import json
    import pathlib

    data = json.loads(
        pathlib.Path("config/game_region_watchlist.json").read_text(encoding="utf-8")
    )
    by_zh = {g["nameZh"]: g for g in data["games"]}

    # 心动小镇 / 燕云十六声 实际有 Steam 版本：必须用真实 appId，不能为 null
    assert by_zh["心动小镇"]["appId"] == 4025700
    assert by_zh["心动小镇"]["name"] == "Heartopia"
    assert by_zh["心动小镇"]["publisher"] == "XD International"
    assert "steam" in by_zh["心动小镇"]["platforms"]

    assert by_zh["燕云十六声"]["appId"] == 3564740
    assert "steam" in by_zh["燕云十六声"]["platforms"]

    # 全球实时榜中的 GTA V 条目是 Enhanced（appid 3240220），不是旧版 271590。
    assert by_zh["侠盗猎车手 5 增强版"]["appId"] == 3240220

    # 原神 / 王者荣耀 确认无 Steam 版本：保持 null「未披露」
    assert by_zh["原神"]["appId"] in (None, "", 0)
    assert by_zh["王者荣耀"]["appId"] in (None, "", 0)
