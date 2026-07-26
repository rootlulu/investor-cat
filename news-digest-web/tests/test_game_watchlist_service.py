from __future__ import annotations

import json

import pytest

from src import game_watchlist_service as svc


def write_seed(path, games):
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "description": "保留说明",
                "games": games,
                "regions": [{"code": "global", "name": "全球"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_v91_loads_legacy_seed_as_normalized_catalog_without_rewriting(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(
        path,
        [
            {
                "appId": 2358720,
                "name": "Black Myth: Wukong",
                "nameZh": "黑神话：悟空",
                "publisher": "Game Science",
                "group": "cn",
            }
        ],
    )
    before = path.read_bytes()

    catalog = svc.load_watchlist(path)

    assert catalog["schemaVersion"] == svc.WATCHLIST_SCHEMA_VERSION
    assert catalog["revision"]
    assert catalog["games"] == [
        {
            "id": "black-myth-wukong",
            "name": "Black Myth: Wukong",
            "nameZh": "黑神话：悟空",
            "publisher": "Game Science",
            "group": "cn",
            "platforms": [],
            "aliases": [],
            "appId": 2358720,
            "sourceIds": {
                "steam": ["2358720"],
                "sensorTower": [],
                "qimai": [],
                "diandian": [],
            },
        }
    ]
    assert catalog["regions"] == [{"code": "global", "name": "全球"}]
    assert path.read_bytes() == before


def test_v92_replace_with_empty_games_stays_empty(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "appId": 570}])

    result = svc.import_watchlist(
        content=json.dumps({"games": []}),
        data_format="json",
        mode="replace",
        path=path,
    )

    assert result["games"] == []
    assert result["operation"] == {"mode": "replace", "added": 0, "updated": 0, "total": 0}
    assert svc.load_watchlist(path)["games"] == []
    assert json.loads(path.read_text(encoding="utf-8"))["games"] == []


def test_v91_v96_json_merge_and_csv_replace_preserve_regions(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "nameZh": "刀塔 2", "appId": 570}])

    merged = svc.import_watchlist(
        content=json.dumps(
            {
                "games": [
                    {
                        "name": "Heartopia",
                        "nameZh": "心动小镇",
                        "appId": 4025700,
                        "aliases": ["心动小镇手游"],
                        "sourceIds": {"sensorTower": ["heartopia-global"]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        data_format="json",
        mode="merge",
        path=path,
    )

    assert merged["operation"] == {"mode": "merge", "added": 1, "updated": 0, "total": 2}
    assert [game["id"] for game in merged["games"]] == ["dota-2", "heartopia"]

    csv_content = (
        "id,name,nameZh,publisher,group,platforms,aliases,steamAppId,sensorTowerAppIds,qimaiAppIds,diandianAppIds\n"
        'heartopia,Heartopia,心动小镇,XD,cn,"steam|mobile","心动小镇手游|Heartopia Mobile",4025700,'
        'heartopia-global,123456,654321\n'
    )
    replaced = svc.import_watchlist(
        content=csv_content,
        data_format="csv",
        mode="replace",
        path=path,
    )

    assert replaced["operation"] == {"mode": "replace", "added": 1, "updated": 0, "total": 1}
    assert replaced["regions"] == [{"code": "global", "name": "全球"}]
    game = replaced["games"][0]
    assert game["platforms"] == ["steam", "mobile"]
    assert game["aliases"] == ["心动小镇手游", "Heartopia Mobile"]
    assert game["sourceIds"] == {
        "steam": ["4025700"],
        "sensorTower": ["heartopia-global"],
        "qimai": ["123456"],
        "diandian": ["654321"],
    }


@pytest.mark.parametrize(
    "games",
    [
        [
            {"id": "one", "name": "One", "sourceIds": {"qimai": ["same"]}},
            {"id": "two", "name": "Two", "sourceIds": {"qimai": ["same"]}},
        ],
        [
            {"id": "one", "name": "One", "aliases": ["shared"]},
            {"id": "two", "name": "Two", "aliases": ["shared"]},
        ],
        [{"id": "missing-name", "sourceIds": {"steam": ["1"]}}],
    ],
)
def test_v93_v96_invalid_identity_import_is_atomic(tmp_path, games):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "appId": 570}])
    before = path.read_bytes()

    with pytest.raises(svc.WatchlistValidationError):
        svc.import_watchlist(
            content=json.dumps({"games": games}),
            data_format="json",
            mode="replace",
            path=path,
        )

    assert path.read_bytes() == before


def test_v96_size_and_count_limits_are_atomic(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "appId": 570}])
    before = path.read_bytes()

    with pytest.raises(svc.WatchlistValidationError, match="1 MiB"):
        svc.import_watchlist(
            content="x" * (svc.MAX_IMPORT_BYTES + 1),
            data_format="json",
            mode="replace",
            path=path,
        )
    assert path.read_bytes() == before

    games = [{"id": f"game-{index}", "name": f"Game {index}"} for index in range(svc.MAX_GAMES + 1)]
    with pytest.raises(svc.WatchlistValidationError, match="500"):
        svc.import_watchlist(
            content=json.dumps({"games": games}),
            data_format="json",
            mode="replace",
            path=path,
        )
    assert path.read_bytes() == before


def test_v126_auto_global_region_counts_toward_limit():
    regions = [
        {
            "code": f"{chr(97 + index // 26)}{chr(97 + index % 26)}",
            "name": f"Region {index}",
        }
        for index in range(svc.MAX_REGIONS)
    ]

    with pytest.raises(svc.WatchlistValidationError, match="100"):
        svc._normalize_regions(regions)


def test_v91_delete_removes_exact_id_and_unknown_id_is_atomic(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "appId": 570}, {"name": "Counter-Strike 2", "appId": 730}])

    result = svc.delete_watchlist_game("dota-2", path=path)

    assert [game["id"] for game in result["games"]] == ["counter-strike-2"]
    before = path.read_bytes()
    with pytest.raises(svc.WatchlistNotFoundError):
        svc.delete_watchlist_game("missing", path=path)
    assert path.read_bytes() == before


def test_v93_v94_filter_prefers_source_id_then_unique_alias_without_reordering(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(
        path,
        [
            {
                "id": "heartopia",
                "name": "Heartopia",
                "nameZh": "心动小镇",
                "aliases": ["心动小镇手游"],
                "sourceIds": {"qimai": ["123"]},
            },
            {"id": "genshin-impact", "name": "Genshin Impact", "nameZh": "原神"},
        ],
    )
    catalog = svc.load_watchlist(path)
    rows = [
        {"rank": 9, "game": "Completely Different Name", "appId": "123"},
        {"rank": 42, "game": "原神"},
        {"rank": 3, "game": "Heartopia", "appId": "wrong-source-id"},
        {"rank": 1, "game": "Unwatched"},
    ]

    filtered, warnings = svc.filter_rows_for_watchlist(rows, source="qimai", catalog=catalog)

    assert [(row["rank"], row["watchlistId"]) for row in filtered] == [
        (9, "heartopia"),
        (42, "genshin-impact"),
    ]
    assert warnings == ["七麦：排除 2 条未关注记录。"]


def test_v113_game_update_and_region_crud_change_revision_and_persist(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "nameZh": "刀塔 2", "appId": 570}])
    initial = svc.load_watchlist(path)

    updated_game = svc.update_watchlist_game(
        "dota-2",
        {
            "name": "Dota 2 Updated",
            "nameZh": "刀塔 2（更新）",
            "publisher": "Valve",
            "steamAppId": 570,
        },
        path=path,
    )

    assert updated_game["revision"] != initial["revision"]
    assert updated_game["games"][0]["id"] == "dota-2"
    assert updated_game["games"][0]["name"] == "Dota 2 Updated"
    assert updated_game["operation"] == {"mode": "update", "updated": "dota-2", "total": 1}

    created_region = svc.create_watchlist_region({"code": "us", "name": "美国"}, path=path)
    assert created_region["revision"] != updated_game["revision"]
    assert created_region["regions"][-1] == {"code": "us", "name": "美国"}

    updated_region = svc.update_watchlist_region(
        "us",
        {"code": "jp", "name": "日本"},
        path=path,
    )
    assert updated_region["revision"] != created_region["revision"]
    assert updated_region["regions"][-1] == {"code": "jp", "name": "日本"}

    deleted_region = svc.delete_watchlist_region("jp", path=path)
    assert deleted_region["revision"] != updated_region["revision"]
    assert deleted_region["regions"] == [{"code": "global", "name": "全球"}]
    assert svc.load_watchlist(path) == {
        key: value
        for key, value in deleted_region.items()
        if key != "operation"
    }


def test_v116_invalid_game_and_region_mutations_are_atomic(tmp_path):
    path = tmp_path / "watchlist.json"
    write_seed(path, [{"name": "Dota 2", "appId": 570}])
    before = path.read_bytes()

    with pytest.raises(svc.WatchlistValidationError):
        svc.update_watchlist_game("dota-2", {}, path=path)
    assert path.read_bytes() == before

    with pytest.raises(svc.WatchlistValidationError):
        svc.create_watchlist_region({"code": "global", "name": "重复全球"}, path=path)
    assert path.read_bytes() == before

    with pytest.raises(svc.WatchlistValidationError):
        svc.delete_watchlist_region("global", path=path)
    assert path.read_bytes() == before

    with pytest.raises(svc.WatchlistNotFoundError):
        svc.update_watchlist_region("missing", {"code": "us", "name": "美国"}, path=path)
    assert path.read_bytes() == before
