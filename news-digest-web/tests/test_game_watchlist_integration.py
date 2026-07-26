from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src import game_provider_service as provider_svc
from src import game_region_service as region_svc
from src import game_service as game_svc
from src.game_watchlist_service import WatchlistNotFoundError, WatchlistValidationError


def catalog(games, revision="watchlist-new"):
    return {
        "schemaVersion": 2,
        "revision": revision,
        "games": games,
        "regions": [{"code": "global", "name": "全球"}],
        "importSchema": {},
    }


def heartopia_catalog(revision="watchlist-new"):
    return catalog(
        [
            {
                "id": "heartopia",
                "name": "Heartopia",
                "nameZh": "心动小镇",
                "publisher": "XD",
                "group": "cn",
                "platforms": ["steam", "mobile"],
                "aliases": ["心动小镇手游"],
                "appId": 4025700,
                "sourceIds": {
                    "steam": ["4025700"],
                    "sensorTower": ["st-heartopia"],
                    "qimai": ["qm-heartopia"],
                    "diandian": ["dd-heartopia"],
                },
            }
        ],
        revision=revision,
    )


def test_v93_v94_game_dashboard_filters_all_sources_without_rewriting_rank():
    revenue_rows = [
        {"rank": 50, "game": "Different ST Name", "appId": "st-heartopia", "sourceType": "sensor_tower"},
        {"rank": 1, "game": "Unwatched Revenue", "appId": "st-other", "sourceType": "sensor_tower"},
        {"rank": 51, "game": "心动小镇手游", "sourceType": "reported"},
    ]
    ranking_rows = [
        {"provider": "qimai", "rank": 9, "game": "Different Qimai Name", "appId": "qm-heartopia"},
        {"provider": "qimai", "rank": 1, "game": "Unwatched Ranking", "appId": "qm-other"},
        {"provider": "diandian", "rank": 42, "game": "心动小镇"},
    ]

    filtered_revenue, filtered_rankings, warnings = game_svc.filter_game_dashboard_rows(
        revenue_rows,
        ranking_rows,
        heartopia_catalog(),
    )

    assert [(row["rank"], row["watchlistId"]) for row in filtered_revenue] == [
        (50, "heartopia"),
        (51, "heartopia"),
    ]
    assert [(row["rank"], row["watchlistId"]) for row in filtered_rankings] == [
        (9, "heartopia"),
        (42, "heartopia"),
    ]
    assert any("Sensor Tower：排除 1 条" in warning for warning in warnings)
    assert any("七麦：排除 1 条" in warning for warning in warnings)


def test_v92_v95_game_payload_empty_watchlist_ignores_old_cache_and_filters_everything():
    empty_catalog = catalog([], revision="empty-revision")
    old_payload = {
        "schemaVersion": game_svc.GAME_SCHEMA_VERSION,
        "watchlistRevision": "old-revision",
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "markets": [{"top100": [{"game": "Old Game"}]}],
    }
    raw_revenue = [{"market": "global", "game": "Old Game", "sourceType": "sensor_tower", "revenue": 1}]
    raw_rankings = [{"provider": "qimai", "chart": "free", "countryCode": "cn", "game": "Old Game", "rank": 1}]

    with patch.object(game_svc, "GAME_CACHE", {"expires_at": datetime.now(UTC) + timedelta(days=1), "data": old_payload}), patch.object(
        game_svc, "load_watchlist", return_value=empty_catalog
    ), patch.object(game_svc, "load_latest_games", AsyncMock(return_value=old_payload)), patch.object(
        game_svc, "load_imported_data", return_value=(raw_revenue, raw_rankings, [], [])
    ) as imported, patch.object(
        game_svc, "fetch_public_sensor_tower_revenue", AsyncMock(return_value=([], [], None))
    ), patch.object(game_svc, "save_latest_games", AsyncMock()) as save:
        result = asyncio.run(game_svc.get_games())

    imported.assert_called_once()
    save.assert_awaited_once()
    assert result["watchlistRevision"] == "empty-revision"
    assert result["watchlistCount"] == 0
    assert result["hasData"] is False
    assert all(market["top100"] == [] for market in result["markets"])
    assert all(
        chart["rows"] == []
        for provider in result["rankProviders"]
        for country in provider["countries"]
        for chart in country["charts"]
    )


def test_v92_region_loader_respects_explicit_empty_catalog():
    assert region_svc.load_region_games({}, catalog([])) == []


def test_v95_region_cache_revision_mismatch_forces_rebuild():
    active_catalog = catalog([], revision="new-revision")
    cached = {
        "schemaVersion": region_svc.GAME_REGION_SCHEMA_VERSION,
        "watchlistRevision": "old-revision",
        "region": "global",
        "regionName": "全球",
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "games": [{"id": "old"}],
        "rankings": {},
        "errors": [],
    }
    rebuilt = {
        "schemaVersion": region_svc.GAME_REGION_SCHEMA_VERSION,
        "watchlistRevision": "new-revision",
        "region": "global",
        "regionName": "全球",
        "expiresAt": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "games": [],
        "rankings": {"live": {"status": "ok"}},
        "errors": [],
    }

    with patch.object(region_svc, "load_watchlist", return_value=active_catalog), patch.object(
        region_svc, "load_region_cache", AsyncMock(return_value=cached)
    ), patch.object(region_svc, "build_region_payload", AsyncMock(return_value=rebuilt)) as build, patch.object(
        region_svc, "save_region_cache", AsyncMock()
    ):
        result = asyncio.run(region_svc.get_region_games())

    build.assert_awaited_once()
    assert result["watchlistRevision"] == "new-revision"
    assert result["games"] == []


def test_v93_provider_crawl_persists_only_watched_rows_and_keeps_rank():
    rows = [
        {"provider": "qimai", "chart": "free", "countryCode": "cn", "rank": 1, "game": "Unwatched"},
        {
            "provider": "qimai",
            "chart": "grossing",
            "countryCode": "cn",
            "rank": 37,
            "game": "Different Name",
            "appId": "qm-heartopia",
        },
    ]
    with patch.object(provider_svc, "current_auth_session", return_value=None), patch.object(
        provider_svc, "load_state", return_value={}
    ), patch.object(provider_svc, "save_state"), patch.object(
        provider_svc, "enforce_crawl_policy"
    ), patch.object(provider_svc, "mark_attempt"), patch.object(
        provider_svc, "crawl_two_charts", return_value=rows
    ), patch.object(provider_svc, "load_watchlist", return_value=heartopia_catalog()), patch.object(
        provider_svc, "merge_ranking_rows"
    ) as merge:
        result = provider_svc.crawl_game_provider_rankings_sync("qimai", "cn")

    saved_rows = merge.call_args.args[0]
    assert [(row["rank"], row["watchlistId"]) for row in saved_rows] == [(37, "heartopia")]
    assert result["fetchedRows"] == 2
    assert result["rows"] == 1


def test_v93_provider_merge_clears_empty_scope_and_old_unwatched_rows(tmp_path):
    path = tmp_path / "rankings.json"
    path.write_text(
        json.dumps(
            [
                {"provider": "qimai", "country_code": "cn", "chart": "free", "rank": 1, "game": "Old"},
                {"provider": "diandian", "country_code": "us", "chart": "free", "rank": 2, "game": "Other"},
            ]
        ),
        encoding="utf-8",
    )

    provider_svc.merge_ranking_rows(
        [],
        path=path,
        replace_scopes={("qimai", "cn", "free")},
        catalog=heartopia_catalog(),
    )

    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_v91_v96_watchlist_api_maps_results_and_errors():
    app_module = importlib.import_module("src.app")
    expected = heartopia_catalog()

    with patch.object(app_module, "load_game_watchlist", return_value=expected):
        assert asyncio.run(app_module.api_game_watchlist()) == expected

    with patch.object(app_module, "import_game_watchlist", return_value=expected) as importer, patch.object(
        app_module, "invalidate_game_cache", AsyncMock()
    ) as invalidate:
        result = asyncio.run(
            app_module.api_import_game_watchlist(
                {"format": "json", "mode": "merge", "content": '{"games": []}'}
            )
        )
    assert result == expected
    importer.assert_called_once_with(content='{"games": []}', data_format="json", mode="merge")
    invalidate.assert_awaited_once()

    with patch.object(app_module, "delete_game_watchlist_item", side_effect=WatchlistNotFoundError("missing")):
        with pytest.raises(HTTPException) as error:
            asyncio.run(app_module.api_delete_game_watchlist_item("missing"))
    assert error.value.status_code == 404

    with patch.object(app_module, "import_game_watchlist", side_effect=WatchlistValidationError("bad import")):
        with pytest.raises(HTTPException) as error:
            asyncio.run(app_module.api_import_game_watchlist({"format": "json", "mode": "replace", "content": "bad"}))
    assert error.value.status_code == 400


def test_v113_v116_watchlist_update_and_region_crud_api_contract():
    app_module = importlib.import_module("src.app")
    expected = heartopia_catalog(revision="watchlist-edited")

    with patch.object(app_module, "update_game_watchlist_item", return_value=expected) as updater, patch.object(
        app_module, "invalidate_game_cache", AsyncMock()
    ) as invalidate:
        result = asyncio.run(app_module.api_update_game_watchlist_item("heartopia", {"name": "Heartopia 2"}))
    assert result == expected
    updater.assert_called_once_with("heartopia", {"name": "Heartopia 2"})
    invalidate.assert_awaited_once()

    operations = [
        ("create_game_watchlist_region", "api_create_game_watchlist_region", ({"code": "us", "name": "美国"},)),
        (
            "update_game_watchlist_region",
            "api_update_game_watchlist_region",
            ("us", {"code": "jp", "name": "日本"}),
        ),
        ("delete_game_watchlist_region", "api_delete_game_watchlist_region", ("jp",)),
    ]
    for service_name, endpoint_name, args in operations:
        with patch.object(app_module, service_name, return_value=expected), patch.object(
            app_module, "invalidate_game_cache", AsyncMock()
        ) as invalidate:
            assert asyncio.run(getattr(app_module, endpoint_name)(*args)) == expected
        invalidate.assert_awaited_once()

    with patch.object(app_module, "delete_game_watchlist_region", side_effect=WatchlistValidationError("global")):
        with pytest.raises(HTTPException) as error:
            asyncio.run(app_module.api_delete_game_watchlist_region("global"))
    assert error.value.status_code == 400

    with patch.object(app_module, "update_game_watchlist_region", side_effect=WatchlistNotFoundError("missing")):
        with pytest.raises(HTTPException) as error:
            asyncio.run(app_module.api_update_game_watchlist_region("missing", {"code": "us", "name": "美国"}))
    assert error.value.status_code == 404


def test_v91_watchlist_routes_are_registered():
    app_module = importlib.import_module("src.app")
    routes = {
        (route.path, method)
        for route in app_module.app.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    assert ("/api/games/watchlist", "GET") in routes
    assert ("/api/games/watchlist/import", "POST") in routes
    assert ("/api/games/watchlist/{game_id}", "PUT") in routes
    assert ("/api/games/watchlist/{game_id}", "DELETE") in routes
    assert ("/api/games/watchlist/regions", "POST") in routes
    assert ("/api/games/watchlist/regions/{region_code}", "PUT") in routes
    assert ("/api/games/watchlist/regions/{region_code}", "DELETE") in routes


def test_v97_frontend_watchlist_management_contract():
    root = Path(__file__).resolve().parents[1]
    app_source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    styles = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "function GameWatchlistTab" in app_source
    assert "关注游戏" in app_source
    assert "/api/games/watchlist/import" in app_source
    assert "/api/games/watchlist/${encodeURIComponent(game.id)}" in app_source
    watchlist_start = app_source.index("function GameWatchlistTab")
    watchlist_source = app_source[watchlist_start : watchlist_start + 14000]
    assert watchlist_source.count("window.confirm") >= 2
    assert 'accept=".json,.csv,application/json,text/csv"' in watchlist_source
    assert 'value="merge"' in watchlist_source
    assert 'value="replace"' in watchlist_source
    assert ".game-watchlist-form-grid" in styles
    assert ".game-watchlist-card" in styles
    assert "@media (max-width: 900px)" in styles


def test_v114_v116_frontend_country_dropdown_and_dual_catalog_contract():
    root = Path(__file__).resolve().parents[1]
    app_source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    styles = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "关注配置" in app_source
    assert "关注国家" in app_source
    assert 'aria-label="关注国家"' in app_source
    assert "/api/games/watchlist/regions" in app_source
    assert "editingGameId" in app_source
    assert "editingRegionCode" in app_source
    assert "onManageRegions" in app_source
    assert "selectWatchlistView" in app_source
    assert "cancelGameEdit" in app_source
    assert "cancelRegionEdit" in app_source
    region_start = app_source.index("function GameRegionTab")
    region_source = app_source[region_start : region_start + 16000]
    assert "<select" in region_source
    assert ".game-region-select" in styles
    assert ".game-watchlist-switcher" in styles
    assert "--game-font-family" in styles
