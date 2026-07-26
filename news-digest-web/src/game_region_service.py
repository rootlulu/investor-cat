from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import browser_service as bs
from .commodity_service import load_config, resolve_sqlite_path

ROOT_DIR = Path(__file__).resolve().parents[1]
REGION_WATCHLIST_PATH = ROOT_DIR / "config" / "game_region_watchlist.json"
GAME_REGION_SCHEMA_VERSION = 1
REGION_CACHE_LOCK = asyncio.Lock()
HTTP_TIMEOUT = 10.0

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

DEFAULT_REGIONS = [
    {"code": "global", "name": "全球"},
    {"code": "cn", "name": "中国"},
    {"code": "us", "name": "美国"},
    {"code": "jp", "name": "日本"},
    {"code": "kr", "name": "韩国"},
    {"code": "de", "name": "德国"},
    {"code": "gb", "name": "英国"},
    {"code": "fr", "name": "法国"},
    {"code": "ca", "name": "加拿大"},
    {"code": "tw", "name": "中国台湾"},
    {"code": "hk", "name": "中国香港"},
    {"code": "au", "name": "澳大利亚"},
    {"code": "br", "name": "巴西"},
    {"code": "mx", "name": "墨西哥"},
    {"code": "it", "name": "意大利"},
    {"code": "es", "name": "西班牙"},
    {"code": "sa", "name": "沙特"},
    {"code": "ae", "name": "阿联酋"},
    {"code": "tr", "name": "土耳其"},
    {"code": "in", "name": "印度"},
    {"code": "id", "name": "印尼"},
    {"code": "th", "name": "泰国"},
    {"code": "vn", "name": "越南"},
    {"code": "sg", "name": "新加坡"},
    {"code": "my", "name": "马来西亚"},
]

DEFAULT_GAMES = [
    {"appId": 2358720, "name": "Black Myth: Wukong", "nameZh": "黑神话：悟空", "publisher": "Game Science", "group": "cn"},
    {"appId": 1203220, "name": "Naraka: Bladepoint", "nameZh": "永劫无间", "publisher": "NetEase", "group": "cn"},
    {"appId": 2507950, "name": "Delta Force", "nameZh": "三角洲行动", "publisher": "Team Jade / TiMi", "group": "cn"},
    {"appId": 3564740, "name": "Where Winds Meet", "nameZh": "燕云十六声", "publisher": "NetEase (Everstone)", "group": "cn"},
    {"appId": 3513350, "name": "Wuthering Waves", "nameZh": "鸣潮", "publisher": "KURO GAMES", "group": "cn"},
    {"appId": 2767030, "name": "Marvel Rivals", "nameZh": "漫威争锋", "publisher": "NetEase", "group": "cn"},
    {"appId": 2139460, "name": "Once Human", "nameZh": "七日世界", "publisher": "NetEase", "group": "cn"},
    {"appId": 730, "name": "Counter-Strike 2", "nameZh": "反恐精英 2", "publisher": "Valve", "group": "global"},
    {"appId": 570, "name": "Dota 2", "nameZh": "刀塔 2", "publisher": "Valve", "group": "global"},
    {"appId": 578080, "name": "PUBG: BATTLEGROUNDS", "nameZh": "绝地求生", "publisher": "KRAFTON", "group": "global"},
    {"appId": 1172470, "name": "Apex Legends", "nameZh": "Apex 英雄", "publisher": "EA", "group": "global"},
    {"appId": 271590, "name": "Grand Theft Auto V", "nameZh": "侠盗猎车手 5", "publisher": "Rockstar", "group": "global"},
    {"appId": 252490, "name": "Rust", "nameZh": "腐蚀", "publisher": "Facepunch", "group": "global"},
    {"appId": 440, "name": "Team Fortress 2", "nameZh": "军团要塞 2", "publisher": "Valve", "group": "global"},
    {"appId": 236390, "name": "War Thunder", "nameZh": "战争雷霆", "publisher": "Gaijin", "group": "global"},
    {"appId": 107410, "name": "ARMA 3", "nameZh": "武装突袭 3", "publisher": "Bohemia", "group": "global"},
    {"appId": 393380, "name": "Squad", "nameZh": "战术小队", "publisher": "Offworld", "group": "global"},
    {"appId": 1085660, "name": "Destiny 2", "nameZh": "命运 2", "publisher": "Bungie", "group": "global"},
    {"appId": 1599340, "name": "Lost Ark", "nameZh": "失落方舟", "publisher": "Smilegate", "group": "global"},
    {"appId": 1063730, "name": "New World", "nameZh": "新世界", "publisher": "Amazon", "group": "global"},
    {"appId": 1086940, "name": "Baldur's Gate 3", "nameZh": "博德之门 3", "publisher": "Larian", "group": "global"},
    {"appId": 1245620, "name": "Elden Ring", "nameZh": "艾尔登法环", "publisher": "Bandai Namco", "group": "global"},
    {"appId": 1091500, "name": "Cyberpunk 2077", "nameZh": "赛博朋克 2077", "publisher": "CD Projekt", "group": "global"},
    {"appId": 1623730, "name": "Palworld", "nameZh": "幻兽帕鲁", "publisher": "Pocketpair", "group": "global"},
    {"appId": 553850, "name": "Helldivers 2", "nameZh": "地狱潜者 2", "publisher": "Sony", "group": "global"},
    {"appId": 2073850, "name": "The Finals", "nameZh": "决赛", "publisher": "Embark", "group": "global"},
    {"appId": 892970, "name": "Valheim", "nameZh": "英灵神殿", "publisher": "Iron Gate", "group": "global"},
    {"appId": 1203620, "name": "Enshrouded", "nameZh": "雾锁王国", "publisher": "Keen", "group": "global"},
    {"appId": 1326470, "name": "Sons of the Forest", "nameZh": "森林之子", "publisher": "Endnight", "group": "global"},
]


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = re.sub(r"[^0-9\-]", "", str(value))
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def load_region_config_file() -> dict[str, Any]:
    if REGION_WATCHLIST_PATH.exists():
        try:
            data = json.loads(REGION_WATCHLIST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def load_region_games(config: dict[str, Any]) -> list[dict[str, Any]]:
    data = load_region_config_file()
    games = data.get("games") or config.get("games", {}).get("regionWatchlist") or DEFAULT_GAMES
    out: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        raw_app_id = game.get("appId", game.get("app_id"))
        # 手游等无 Steam appId 的游戏保留为「未披露」行，但仍展示在线/热销占位
        if raw_app_id in (None, "", 0):
            app_id = None
        else:
            try:
                app_id = int(raw_app_id)
            except (TypeError, ValueError):
                continue
        out.append(
            {
                "appId": app_id,
                "name": clean_text(game.get("name")),
                "nameZh": clean_text(game.get("nameZh") or game.get("name_zh")),
                "publisher": clean_text(game.get("publisher")),
                "group": clean_text(game.get("group") or "global"),
                "platforms": list(game.get("platforms") or []),
            }
        )
    return out


def load_region_regions(config: dict[str, Any]) -> list[dict[str, Any]]:
    data = load_region_config_file()
    regions = data.get("regions") or DEFAULT_REGIONS
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for region in regions:
        code = clean_text(region.get("code")).lower()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": clean_text(region.get("name")) or code})
    return out


def resolve_region(cc: str, regions: list[dict[str, Any]]) -> tuple[str, str]:
    code = clean_text(cc).lower()
    codes = {region["code"] for region in regions}
    if code not in codes:
        code = "global"
    name = next((region["name"] for region in regions if region["code"] == code), "全球")
    return code, name


def parse_topselling_appids(html: str) -> list[str]:
    ids = re.findall(r'data-appid="(\d+)"', html)
    if not ids:
        ids = re.findall(r"/app/(\d+)", html)
    seen: set[str] = set()
    out: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_topselling_payload(payload: dict[str, Any]) -> list[str]:
    """Extract ordered app ids from Steam's weekly top-sellers JSON response."""
    seen: set[str] = set()
    app_ids: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("appid", "app_id", "appId"):
                app_id = parse_int(value.get(key))
                if app_id and str(app_id) not in seen:
                    seen.add(str(app_id))
                    app_ids.append(str(app_id))
                    break
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return app_ids


def parse_steamcharts_html(html: str) -> list[dict[str, Any]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    series: list[dict[str, Any]] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 5:
            continue
        month_raw = clean_html(cells[0])
        avg_raw = clean_html(cells[1])
        peak_raw = clean_html(cells[4])
        if not month_raw:
            continue
        match = re.match(r"([A-Za-z]+)\s+(\d{4})", month_raw)
        if not match:
            continue
        month_number = MONTHS.get(match.group(1).lower())
        if not month_number:
            continue
        month = f"{int(match.group(2))}-{month_number:02d}"
        avg = parse_int(avg_raw)
        peak = parse_int(peak_raw)
        if avg is None and peak is None:
            continue
        series.append({"month": month, "avg": avg, "peak": peak})
    return series


async def fetch_steam_topselling(cc: str, timeout: float) -> tuple[list[str], str | None]:
    url = f"https://store.steampowered.com/charts/topselling/{cc}"
    errors: list[str] = []
    try:
        payload = await asyncio.to_thread(
            bs.fetch_page_json_response_via_browser,
            url,
            "IStoreTopSellersService/GetWeeklyTopSellers",
            int(timeout * 1000),
        )
    except Exception as error:  # pragma: no cover - network/browser dependent
        errors.append(str(error))
    else:
        app_ids = parse_topselling_payload(payload)
        if app_ids:
            return app_ids, None
        errors.append("Steam weekly top-sellers 响应不含 appId")

    # Backward-compatible fallback for older server-rendered Steam pages.
    try:
        html = await asyncio.to_thread(bs.fetch_html_via_browser, url, int(timeout * 1000))
    except Exception as error:  # pragma: no cover - network/browser dependent
        errors.append(str(error))
    else:
        app_ids = parse_topselling_appids(html)
        if app_ids:
            return app_ids, None
        errors.append("Steam 榜单页面不含 appId")
    return [], "；".join(dict.fromkeys(errors))


async def fetch_steam_current_players(app_id: int | None, timeout: float) -> int | None:
    if not app_id:
        return None
    url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}"
    try:
        payload = await asyncio.to_thread(bs.fetch_json_via_browser, url, int(timeout * 1000))
    except Exception:  # pragma: no cover - network/browser dependent
        return None
    count = payload.get("response", {}).get("player_count")
    return int(count) if isinstance(count, int) else None


async def fetch_steamcharts_history(app_id: int | None, timeout: float) -> tuple[list[dict[str, Any]], str | None]:
    if not app_id:
        return [], None
    url = f"https://steamcharts.com/app/{app_id}"
    try:
        html = await asyncio.to_thread(bs.fetch_html_via_browser, url, int(timeout * 1000))
    except Exception as error:  # pragma: no cover - network/browser dependent
        return [], str(error)
    return parse_steamcharts_html(html), None


async def build_region_payload(
    config: dict[str, Any],
    region: str,
    region_name: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    games = load_region_games(config)
    regions = load_region_regions(config)
    semaphore = asyncio.Semaphore(6)
    errors: list[str] = []

    topselling_ids, ts_error = await fetch_steam_topselling(region, HTTP_TIMEOUT)
    topselling_status = "ok" if not ts_error and topselling_ids else ("partial" if topselling_ids else "unavailable")
    rank_map: dict[str, int] = {}
    for index, app_id in enumerate(topselling_ids):
        rank_map[str(app_id)] = index + 1
    if ts_error:
        errors.append(f"Steam 热销榜（{region_name}）获取失败：{ts_error}")

    async def fetch_game(game: dict[str, Any]) -> dict[str, Any]:
        app_id = game.get("appId")
        async with semaphore:
            current = await fetch_steam_current_players(app_id, HTTP_TIMEOUT)
            history, hist_error = await fetch_steamcharts_history(app_id, HTTP_TIMEOUT)
        if hist_error:
            errors.append(f"SteamCharts（{game.get('nameZh') or game.get('name')}）获取失败：{hist_error}")
        peak = max((row.get("peak") or 0 for row in history), default=None)
        players_status = "ok" if (current is not None or bool(history)) else "unavailable"
        return {
            **game,
            "rank": rank_map.get(str(app_id)),
            "currentPlayers": current,
            "peakPlayers": peak,
            "monthly": history,
            "status": {"topselling": topselling_status, "players": players_status},
        }

    results = await asyncio.gather(*(fetch_game(game) for game in games))
    results = sorted(
        results,
        key=lambda game: (game.get("rank") is None, game.get("rank") or 999999, game.get("name") or ""),
    )

    now = datetime.now(UTC)
    return {
        "schemaVersion": GAME_REGION_SCHEMA_VERSION,
        "region": region,
        "regionName": region_name,
        "generatedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "source": "Steam Charts（月度均值/峰值）、Steam 当前在线 API（实时并发）、Steam 热销榜（按地区）",
        "cadence": "半小时最多刷新一次；在线人数为全球并发（Steam 口径），热销榜按所选地区。",
        "regions": regions,
        "games": results,
        "errors": errors,
    }


def region_payload_has_data(payload: dict[str, Any]) -> bool:
    for game in payload.get("games") or []:
        status = game.get("status") or {}
        if status.get("topselling") in {"ok", "partial"} or status.get("players") == "ok":
            return True
    return False


async def get_region_games(
    cc: str = "global",
    refresh: bool = False,
    allow_stale: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    regions = load_region_regions(config)
    region, region_name = resolve_region(cc, regions)

    cached: dict[str, Any] | None = None
    async with REGION_CACHE_LOCK:
        cached = await load_region_cache(db_path, region)
        if not force and not refresh:
            if cached and cached.get("schemaVersion") == GAME_REGION_SCHEMA_VERSION:
                if parse_dt(cached.get("expiresAt", "")) > datetime.now(UTC):
                    cached = dict(cached)
                    cached["cached"] = True
                    cached["stale"] = False
                    return cached
                if allow_stale:
                    cached = dict(cached)
                    cached["cached"] = True
                    cached["stale"] = True
                    return cached

    payload = await build_region_payload(config, region, region_name, ttl_seconds)
    if not region_payload_has_data(payload):
        if allow_stale and cached and cached.get("schemaVersion") == GAME_REGION_SCHEMA_VERSION:
            fallback = dict(cached)
            fallback["cached"] = True
            fallback["stale"] = True
            fallback["errors"] = list(
                dict.fromkeys([*(cached.get("errors") or []), *(payload.get("errors") or [])])
            )
            return fallback
        payload["cached"] = False
        payload["stale"] = False
        return payload
    await save_region_cache(db_path, region, payload)
    payload["cached"] = False
    payload["stale"] = False
    return payload


async def load_region_cache(db_path: Path, region: str) -> dict[str, Any] | None:
    def sync() -> dict[str, Any] | None:
        ensure_region_table(db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM latest_games_region WHERE id = ?", (region,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    return await asyncio.to_thread(sync)


async def save_region_cache(db_path: Path, region: str, payload: dict[str, Any]) -> None:
    def sync() -> None:
        ensure_region_table(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO latest_games_region (id, generated_at, saved_at, expires_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    saved_at = excluded.saved_at,
                    expires_at = excluded.expires_at,
                    payload_json = excluded.payload_json
                """,
                (
                    region,
                    payload.get("generatedAt"),
                    payload.get("generatedAt"),
                    payload.get("expiresAt"),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()

    await asyncio.to_thread(sync)


def ensure_region_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_games_region (
                id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.commit()
