from __future__ import annotations

import asyncio
from pathlib import Path

from src import game_service as game_svc


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload


class FakeGachaClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []

    async def post(self, url: str, *, headers: dict) -> FakeResponse:
        self.posts.append((url, headers))
        if headers["X-Request-Path"] == "/":
            return FakeResponse({})
        return FakeResponse({"timestamp": "123", "signature": "signed", "nonce": "nonce-1"})

    async def get(self, url: str, *, headers: dict) -> FakeResponse:
        self.gets.append((url, headers))
        return FakeResponse({"current_table": "2026-06"})


def test_v128_gacharevenue_auth_initializes_session_and_signs_get_with_nonce():
    async def exercise() -> tuple[FakeGachaClient, dict]:
        client = FakeGachaClient()
        client_token = "client-token"
        await game_svc.establish_gacharevenue_session(client, client_token)
        payload = await game_svc.gacharevenue_api(client, "config", client_token=client_token)
        return client, payload

    client, payload = asyncio.run(exercise())

    assert payload == {"current_table": "2026-06"}
    assert client.posts[0][1]["X-Request-Path"] == "/"
    assert client.posts[0][1]["X-Request-Method"] == "POST"
    assert client.posts[1][1]["X-Request-Path"] == "/config"
    assert client.posts[1][1]["X-Request-Method"] == "GET"
    assert client.gets[0][1]["X-Nonce"] == "nonce-1"
    assert client.gets[0][1]["X-Request-Method"] == "GET"


def test_v127_authorized_sensor_tower_payload_is_parsed_in_dollars():
    payload = [
        {
            "app_id": "67ec0bf3e540b65904256cc4",
            "revenue_absolute": 123_456_789,
            "units_absolute": 45_678,
            "entities": [
                {
                    "app_id": "1234567890",
                    "name": "Example Game",
                    "publisher_name": "Example Studio",
                    "os": "ios",
                }
            ],
        }
    ]

    rows = game_svc.parse_sensor_tower_top_apps(payload, market="global", month="2026-06")

    assert rows[0]["rank"] == 1
    assert rows[0]["game"] == "Example Game"
    assert rows[0]["publisher"] == "Example Studio"
    assert rows[0]["revenue"] == 1_234_567.89
    assert rows[0]["downloads"] == 45_678
    assert rows[0]["method"] == "estimated"
    assert rows[0]["sourceType"] == "sensor_tower"


def test_v127_invalid_authorization_is_not_mislabeled_as_plain_public_fallback(monkeypatch):
    monkeypatch.setenv("SENSORTOWER_AUTH_TOKEN", "secret-token")
    statuses = game_svc.build_provider_status(
        {"games": {"sensor_tower": {"auth_token_env": "SENSORTOWER_AUTH_TOKEN"}}},
        [{"sourceType": "sensor_tower", "game": "Example Game"}],
        [],
        [{"kind": "publicSensorTowerRevenue", "rows": 1}],
    )

    sensor = next(status for status in statuses if status["id"] == "sensor_tower")
    assert sensor["status"] == "configuration_required"
    assert "公开" in sensor["message"]
    assert "secret-token" not in str(sensor)


def test_v129_official_row_overrides_sensor_tower_when_name_matches():
    rows = [
        {
            "market": "global",
            "month": "2026-06",
            "rank": 2,
            "game": "Example Game",
            "revenue": 1_000_000,
            "currency": "USD",
            "source": "Sensor Tower",
            "sourceType": "sensor_tower",
            "sourcePriority": 50,
        },
        {
            "market": "global",
            "month": "2026-06",
            "game": "Example Game",
            "appId": "official-app-id",
            "revenue": 1_200_000,
            "currency": "USD",
            "source": "Publisher report",
            "sourceType": "official",
            "sourcePriority": 10,
        },
    ]

    merged = game_svc.preferred_revenue_rows(rows)

    assert len(merged) == 1
    assert merged[0]["sourceType"] == "official"
    assert merged[0]["revenue"] == 1_200_000
    assert {item["sourceType"] for item in merged[0]["revenueAlternatives"]} == {"official", "sensor_tower"}


def test_v129_adopted_official_amount_participates_in_revenue_ranking():
    rows = [
        {"market": "global", "month": "2026-06", "rank": 1, "game": "Game A", "revenue": 100, "sourceType": "sensor_tower"},
        {"market": "global", "month": "2026-06", "rank": 2, "game": "Game B", "revenue": 90, "sourceType": "sensor_tower"},
        {"market": "global", "month": "2026-06", "game": "Game C", "revenue": 120, "sourceType": "official"},
    ]

    market = next(item for item in game_svc.build_markets(rows, [], [], 100) if item["id"] == "global")

    assert [(row["rank"], row["game"]) for row in market["top100"]] == [
        (1, "Game C"),
        (2, "Game A"),
        (3, "Game B"),
    ]


def test_v130_market_coverage_reports_real_gap_instead_of_fake_rows():
    markets = game_svc.build_markets(
        [
            {
                "market": "global",
                "month": "2026-06",
                "rank": 1,
                "game": "Example Game",
                "revenue": 1_000_000,
                "currency": "USD",
                "source": "GACHAREVENUE / Sensor Tower估算",
                "sourceType": "sensor_tower",
                "sourceUrl": game_svc.GACHAREVENUE_SOURCE_URL,
                "method": "estimated",
                "coverageStatus": "partial",
                "coverageNote": "仅移动端；PC/主机未统计。",
                "excluded": ["PC", "主机", "广告收入"],
            }
        ],
        [],
        [],
        100,
    )

    global_market = next(market for market in markets if market["id"] == "global")
    coverage = global_market["coverage"]
    assert coverage["targetCount"] == 100
    assert coverage["availableCount"] == 1
    assert coverage["missingCount"] == 99
    assert coverage["status"] == "partial"
    assert coverage["period"] == "2026-06"
    assert "PC" in coverage["excluded"]


def test_v130_row_count_can_be_complete_while_source_scope_remains_partial():
    rows = [
        {
            "market": "global",
            "month": "2026-06",
            "rank": rank,
            "game": f"Game {rank}",
            "revenue": 101 - rank,
            "sourceType": "sensor_tower",
            "coverageStatus": "partial",
            "coveredRegions": ["CN", "JP"],
            "excluded": ["PC", "主机", "广告收入"],
        }
        for rank in range(1, 101)
    ]

    market = next(item for item in game_svc.build_markets(rows, [], [], 100) if item["id"] == "global")

    assert market["coverage"]["availableCount"] == 100
    assert market["coverage"]["missingCount"] == 0
    assert market["coverage"]["status"] == "partial"
    assert "覆盖" in market["coverage"]["missingReason"]


def test_v130_public_china_formula_and_excluded_channels_are_explicit():
    rows = game_svc.aggregate_gacharevenue_rows(
        [
            {
                "id": "example-game",
                "name": "示例游戏",
                "name_en": "Example Game",
                "publisher": "Example Studio",
                "region": "CN",
                "monthly_data": {"06-2026": {"ios_revenue": 10_000, "ios_downloads": 100}},
            }
        ],
        "2026-06",
        "06-2026",
    )

    china = next(row for row in rows if row["market"] == "china")
    assert china["revenue"] == 275
    assert china["method"] == "estimated"
    assert "1.75" in china["coverageNote"]
    assert set(china["excluded"]) >= {"PC", "主机", "广告收入"}


def test_v130_sensor_tower_ui_exposes_exact_amount_and_coverage_gap():
    source = (Path(__file__).parents[1] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

    assert "formatRevenueExact" in source
    assert "缺口" in source
    assert "统计口径" in source
