from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .commodity_service import load_config, resolve_sqlite_path
from .game_watchlist_service import filter_rows_for_watchlist, load_watchlist
from .request_coordinator import coordinate_httpx_client

ROOT_DIR = Path(__file__).resolve().parents[1]
GAME_CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
GAME_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
GAME_SCHEMA_VERSION = 5
CN_TZ = timezone(timedelta(hours=8))

SENSOR_TOWER_REVENUE_JSON = ROOT_DIR / "data" / "game_sensor_tower_revenue.json"
SENSOR_TOWER_REVENUE_CSV = ROOT_DIR / "data" / "game_sensor_tower_revenue.csv"
REPORTED_REVENUE_JSON = ROOT_DIR / "data" / "game_reported_revenue.json"
REPORTED_REVENUE_CSV = ROOT_DIR / "data" / "game_reported_revenue.csv"
GAME_RANKINGS_JSON = ROOT_DIR / "data" / "game_rankings.json"
GAME_RANKINGS_CSV = ROOT_DIR / "data" / "game_rankings.csv"
LEGACY_GAME_DATA_JSON = ROOT_DIR / "data" / "game_metrics.json"
LEGACY_GAME_DATA_CSV = ROOT_DIR / "data" / "game_metrics.csv"
GACHAREVENUE_API_BASE = "https://revenue.ennead.cc/api"
GACHAREVENUE_SOURCE_URL = "https://revenue.ennead.cc/revenue"
SENSOR_TOWER_API_BASE = "https://api.sensortower.com/v1"
SENSOR_TOWER_TOP_APPS_PATH = "unified/sales_report_estimates_comparison_attributes"
SENSOR_TOWER_SOURCE_URL = "https://app.sensortower.com/market-analysis/top-apps"
SENSOR_TOWER_GAMES_CATEGORY = "6014"
SENSOR_TOWER_MARKET_REGIONS = {"global": "WW", "china": "CN"}
REVENUE_EXCLUDED_CHANNELS = ["PC", "主机", "广告收入"]

DEFAULT_RANK_LIMIT = 100
MAX_MAJOR_COUNTRIES = 30

MARKET_DEFS = [
    {"id": "global", "name": "全球", "description": "官方/媒体披露优先，Sensor Tower 估算兜底"},
    {"id": "china", "name": "中国", "description": "官方/媒体披露优先，Sensor Tower 估算兜底"},
]

RANK_PROVIDER_DEFS = [
    {
        "id": "diandian",
        "name": "点点数据",
        "role": "主要国家免费榜 / 畅销榜",
        "homeUrl": "https://app.diandian.com/rank/global/ios",
    },
    {
        "id": "qimai",
        "name": "七麦数据",
        "role": "主要国家免费榜 / 畅销榜",
        "homeUrl": "https://www.qimai.cn/rank",
    },
]

CHART_DEFS = [
    {"id": "free", "name": "免费榜 Top 100"},
    {"id": "grossing", "name": "畅销榜 Top 100"},
]

DEFAULT_MAJOR_GAME_COUNTRIES = [
    {"code": "cn", "name": "中国", "marketRank": 1},
    {"code": "us", "name": "美国", "marketRank": 2},
    {"code": "jp", "name": "日本", "marketRank": 3},
    {"code": "kr", "name": "韩国", "marketRank": 4},
    {"code": "de", "name": "德国", "marketRank": 5},
    {"code": "gb", "name": "英国", "marketRank": 6},
    {"code": "fr", "name": "法国", "marketRank": 7},
    {"code": "ca", "name": "加拿大", "marketRank": 8},
    {"code": "tw", "name": "中国台湾", "marketRank": 9},
    {"code": "hk", "name": "中国香港", "marketRank": 10},
    {"code": "au", "name": "澳大利亚", "marketRank": 11},
    {"code": "br", "name": "巴西", "marketRank": 12},
    {"code": "mx", "name": "墨西哥", "marketRank": 13},
    {"code": "it", "name": "意大利", "marketRank": 14},
    {"code": "es", "name": "西班牙", "marketRank": 15},
    {"code": "sa", "name": "沙特", "marketRank": 16},
    {"code": "ae", "name": "阿联酋", "marketRank": 17},
    {"code": "tr", "name": "土耳其", "marketRank": 18},
    {"code": "in", "name": "印度", "marketRank": 19},
    {"code": "id", "name": "印尼", "marketRank": 20},
    {"code": "th", "name": "泰国", "marketRank": 21},
    {"code": "vn", "name": "越南", "marketRank": 22},
    {"code": "sg", "name": "新加坡", "marketRank": 23},
    {"code": "my", "name": "马来西亚", "marketRank": 24},
    {"code": "ph", "name": "菲律宾", "marketRank": 25},
    {"code": "nl", "name": "荷兰", "marketRank": 26},
    {"code": "ch", "name": "瑞士", "marketRank": 27},
    {"code": "se", "name": "瑞典", "marketRank": 28},
    {"code": "pl", "name": "波兰", "marketRank": 29},
    {"code": "no", "name": "挪威", "marketRank": 30},
]

COUNTRY_CODE_ALIASES = {
    "usa": "us",
    "unitedstates": "us",
    "unitedstatesofamerica": "us",
    "uk": "gb",
    "unitedkingdom": "gb",
    "uae": "ae",
    "unitedarabemirates": "ae",
    "ksa": "sa",
    "saudiarabia": "sa",
    "southkorea": "kr",
    "korea": "kr",
    "taiwan": "tw",
    "hongkong": "hk",
}

GAME_ZH_OVERRIDES = {
    "afk-journey": "剑与远征：启程",
    "arknights": "明日方舟",
    "blue-archive": "蔚蓝档案",
    "dragon-ball-z-dokkan-battle": "龙珠Z 爆裂大战",
    "fate-grand-order": "命运-冠位指定",
    "genshin-impact": "原神",
    "goddess-of-victory-nikke": "胜利女神：妮姬",
    "honkai-impact": "崩坏3",
    "honkai-impact-3rd": "崩坏3",
    "honkai-star-rail": "崩坏：星穹铁道",
    "love-and-deepspace": "恋与深空",
    "naruto-mobile": "火影忍者",
    "neverness-to-everness": "异环",
    "nikke": "胜利女神：妮姬",
    "punishing-gray-raven": "战双帕弥什",
    "reverse-1999": "重返未来：1999",
    "shadowverse-worlds-beyond": "影之诗：世代超越",
    "umamusume": "赛马娘",
    "wuthering-waves": "鸣潮",
    "zenless-zone-zero": "绝区零",
}

FIELD_ALIASES = {
    "market": ["market", "scope", "region", "市场", "范围", "榜单范围"],
    "month": ["month", "period", "date", "年月", "月份", "统计月份"],
    "rank": ["rank", "ranking", "top", "名次", "排名", "排行", "流水排名", "sensor_tower_rank"],
    "game": ["game", "app", "name", "app_name", "product", "游戏", "游戏名称", "产品", "应用"],
    "gameZh": ["game_zh", "game_cn", "name_zh", "zh_name", "chinese_name", "localized_name", "中文名", "中文名称", "游戏中文名"],
    "publisher": ["publisher", "developer", "company", "厂商", "发行商", "开发商", "公司"],
    "genre": ["genre", "category", "品类", "类型", "分类"],
    "platform": ["platform", "store", "os", "平台", "商店"],
    "appId": ["app_id", "appid", "appId", "apple_id", "ios_app_id", "itunes_id", "应用id", "app id"],
    "country": ["country", "countries", "market_country", "国家", "国家地区", "地区"],
    "countryCode": ["country_code", "countrycode", "cc", "storefront", "国家代码", "地区代码"],
    "provider": ["provider", "source", "data_source", "平台来源", "数据源", "来源"],
    "chart": ["chart", "brand", "type", "rank_type", "榜单", "榜单类型"],
    "revenue": [
        "sensor_tower_revenue_usd",
        "sensor_tower_revenue",
        "sensor tower revenue",
        "reported_revenue_usd",
        "official_revenue_usd",
        "media_revenue_usd",
        "estimated_revenue_usd",
        "revenue_usd",
        "revenue",
        "流水",
        "预估流水",
        "收入",
    ],
    "currency": ["currency", "revenue_currency", "sensor_tower_currency", "币种"],
    "downloads": ["downloads", "download", "estimated_downloads", "下载", "预估下载"],
    "url": ["url", "app_url", "source_url", "链接", "来源链接"],
    "sourceName": ["source_name", "source", "reported_by", "reportedby", "publisher_source", "media", "来源名称", "披露方", "公布方", "媒体"],
    "sourceType": ["source_type", "revenue_source_type", "disclosure_type", "来源类型", "数据类型", "披露类型"],
    "sourcePriority": ["source_priority", "priority", "优先级"],
    "artworkUrl": ["artwork_url", "icon", "icon_url", "logo", "图片"],
    "updatedAt": ["updated_at", "updated", "fetched_at", "date", "更新时间", "抓取时间"],
    "note": ["note", "memo", "remark", "备注", "说明"],
}


async def get_games(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    catalog = await asyncio.to_thread(load_watchlist)
    watchlist_revision = catalog.get("revision", "")
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    timeout = float(fetch_config.get("request_timeout_seconds", 8))
    db_path = resolve_sqlite_path(config)

    async with GAME_CACHE_LOCK:
        if (
            not force
            and not refresh
            and GAME_CACHE["data"]
            and GAME_CACHE["data"].get("schemaVersion") == GAME_SCHEMA_VERSION
            and GAME_CACHE["data"].get("watchlistRevision") == watchlist_revision
            and datetime.now(UTC) < GAME_CACHE["expires_at"]
        ):
            cached = dict(GAME_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = await load_latest_games(db_path)
    stored_schema_valid = bool(
        stored
        and stored.get("schemaVersion") == GAME_SCHEMA_VERSION
        and stored.get("watchlistRevision") == watchlist_revision
    )
    stored_is_fresh = bool(stored_schema_valid and parse_dt(stored.get("expiresAt", "")) > datetime.now(UTC))
    if not force and stored and stored_schema_valid and ((allow_stale and not refresh) or stored_is_fresh):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with GAME_CACHE_LOCK:
            GAME_CACHE["data"] = stored
            GAME_CACHE["expires_at"] = parse_dt(stored.get("expiresAt", ""))
        return stored

    countries = configured_game_countries(config)
    rank_limit = configured_rank_limit(config)
    revenue_rows, ranking_rows, errors, source_files = await asyncio.to_thread(load_imported_data)
    source_warnings: list[str] = []
    imported_sensor_rows = [row for row in revenue_rows if row.get("sourceType") == "sensor_tower"]

    authorized_rows, authorized_errors, authorized_source = await fetch_authorized_sensor_tower_revenue(
        config,
        timeout,
        rank_limit=rank_limit,
    )
    revenue_rows.extend(authorized_rows)
    source_warnings.extend(authorized_errors)
    if authorized_source:
        source_files.append(authorized_source)

    sensor_market_counts = {
        market: len([row for row in [*imported_sensor_rows, *authorized_rows] if row.get("market") == market])
        for market in SENSOR_TOWER_MARKET_REGIONS
    }
    fallback_markets = {market for market, count in sensor_market_counts.items() if count < rank_limit}
    if fallback_markets:
        public_rows, public_errors, public_source = await fetch_public_sensor_tower_revenue(max(timeout, 30))
        selected_public_rows = [row for row in public_rows if row.get("market") in fallback_markets]
        revenue_rows.extend(selected_public_rows)
        if selected_public_rows:
            source_warnings.extend(public_errors)
        else:
            errors.extend(public_errors)
        if public_source:
            source_files.append({**public_source, "rows": len(selected_public_rows)})
    revenue_rows, ranking_rows, watchlist_warnings = filter_game_dashboard_rows(
        revenue_rows,
        ranking_rows,
        catalog,
    )
    markets = build_markets(revenue_rows, ranking_rows, countries, rank_limit)
    rank_providers = build_rank_providers(ranking_rows, countries, rank_limit)
    provider_status = build_provider_status(config, revenue_rows, ranking_rows, source_files)
    months = sorted({row.get("month") for row in revenue_rows if row.get("month")}, reverse=True)
    summary = summarize_games(markets, rank_providers, revenue_rows, ranking_rows, countries, source_files, rank_limit)

    now = datetime.now(UTC)
    data = {
        "schemaVersion": GAME_SCHEMA_VERSION,
        "watchlistRevision": watchlist_revision,
        "watchlistCount": len(catalog.get("games") or []),
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": bool(revenue_rows or ranking_rows),
        "source": "官方/权威媒体披露流水 / Sensor Tower 预估流水 / 点点数据榜单 / 七麦数据榜单",
        "cadence": "半小时最多刷新一次；Top100 流水优先读取官方/媒体披露，缺失时使用 Sensor Tower 估算。",
        "rankLimit": rank_limit,
        "countries": countries,
        "markets": markets,
        "rankProviders": rank_providers,
        "providerStatus": provider_status,
        "months": months,
        "defaultMonth": months[0] if months else current_month(),
        "summary": summary,
        "warnings": source_warnings,
        "watchlistWarnings": watchlist_warnings,
        "errors": errors,
    }

    await save_latest_games(db_path, data)
    async with GAME_CACHE_LOCK:
        GAME_CACHE["data"] = data
        GAME_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


async def invalidate_game_cache() -> None:
    async with GAME_CACHE_LOCK:
        GAME_CACHE["data"] = None
        GAME_CACHE["expires_at"] = datetime.min.replace(tzinfo=UTC)


def filter_game_dashboard_rows(
    revenue_rows: list[dict[str, Any]],
    ranking_rows: list[dict[str, Any]],
    catalog: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    filtered_revenue: list[dict[str, Any]] = []
    filtered_rankings: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Sensor Tower/reported revenue is a market Top100 universe. The watchlist
    # only enriches matching rows; it must never shrink or renumber the chart.
    for row in revenue_rows:
        source = "sensorTower" if row.get("sourceType") == "sensor_tower" else "reported"
        matched, _ = filter_rows_for_watchlist([row], source=source, catalog=catalog)
        filtered_revenue.append(matched[0] if matched else dict(row))

    for provider in ("qimai", "diandian"):
        rows = [row for row in ranking_rows if row.get("provider") == provider]
        matched, source_warnings = filter_rows_for_watchlist(rows, source=provider, catalog=catalog)
        filtered_rankings.extend(matched)
        warnings.extend(source_warnings)

    return filtered_revenue, filtered_rankings, warnings


def load_imported_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    source_files: list[dict[str, Any]] = []
    revenue_rows: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []

    revenue_rows.extend(load_records_from_path(REPORTED_REVENUE_JSON, "reportedRevenue", parse_reported_revenue_row, errors, source_files))
    revenue_rows.extend(load_records_from_path(REPORTED_REVENUE_CSV, "reportedRevenue", parse_reported_revenue_row, errors, source_files))
    revenue_rows.extend(load_records_from_path(SENSOR_TOWER_REVENUE_JSON, "sensorTowerRevenue", parse_sensor_tower_revenue_row, errors, source_files))
    revenue_rows.extend(load_records_from_path(SENSOR_TOWER_REVENUE_CSV, "sensorTowerRevenue", parse_sensor_tower_revenue_row, errors, source_files))
    ranking_rows.extend(load_records_from_path(GAME_RANKINGS_JSON, "providerRankings", parse_ranking_row, errors, source_files))
    ranking_rows.extend(load_records_from_path(GAME_RANKINGS_CSV, "providerRankings", parse_ranking_row, errors, source_files))

    legacy_records = load_raw_records(LEGACY_GAME_DATA_JSON, errors)
    if legacy_records:
        legacy_revenue, legacy_rankings = parse_legacy_rows(legacy_records)
        revenue_rows.extend(legacy_revenue)
        ranking_rows.extend(legacy_rankings)
        source_files.append({"path": relative_path(LEGACY_GAME_DATA_JSON), "kind": "legacyGameMetrics", "rows": len(legacy_records)})

    legacy_records = load_raw_records(LEGACY_GAME_DATA_CSV, errors)
    if legacy_records:
        legacy_revenue, legacy_rankings = parse_legacy_rows(legacy_records)
        revenue_rows.extend(legacy_revenue)
        ranking_rows.extend(legacy_rankings)
        source_files.append({"path": relative_path(LEGACY_GAME_DATA_CSV), "kind": "legacyGameMetrics", "rows": len(legacy_records)})

    return compact_rows(revenue_rows), compact_rows(ranking_rows), errors, source_files


def latest_complete_month(now: datetime | None = None) -> tuple[str, str, str]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    current_month_start = datetime(current.year, current.month, 1, tzinfo=UTC)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    return (
        previous_month_start.strftime("%Y-%m"),
        previous_month_start.strftime("%Y-%m-%d"),
        previous_month_end.strftime("%Y-%m-%d"),
    )


async def fetch_authorized_sensor_tower_revenue(
    config: dict[str, Any],
    timeout: float,
    *,
    rank_limit: int = DEFAULT_RANK_LIMIT,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    sensor_config = (config.get("games") or {}).get("sensor_tower") or {}
    token_env = clean_text(sensor_config.get("auth_token_env")) or "SENSORTOWER_AUTH_TOKEN"
    token = clean_text(os.getenv(token_env))
    if not token:
        return [], [], None

    month, start_date, end_date = latest_complete_month()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    endpoint = f"{SENSOR_TOWER_API_BASE}/{SENSOR_TOWER_TOP_APPS_PATH}"
    async with httpx.AsyncClient(
        headers={"User-Agent": "news-digest-web/1.0", "Accept": "application/json"},
        timeout=max(float(timeout), 30.0),
        follow_redirects=True,
    ) as client:
        coordinate_httpx_client(client)
        for market, region in SENSOR_TOWER_MARKET_REGIONS.items():
            try:
                response = await client.get(
                    endpoint,
                    params={
                        "auth_token": token,
                        "comparison_attribute": "absolute",
                        "time_range": "month",
                        "measure": "revenue",
                        "date": start_date,
                        "end_date": end_date,
                        "category": SENSOR_TOWER_GAMES_CATEGORY,
                        "regions": region,
                        "limit": rank_limit,
                        "device_type": "total",
                    },
                )
                response.raise_for_status()
                rows.extend(parse_sensor_tower_top_apps(response.json(), market=market, month=month)[:rank_limit])
            except Exception as error:
                errors.append(sensor_tower_api_error(error, market=market, token=token))
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status in {401, 403}:
                    break

    source = None
    if rows:
        source = {
            "path": SENSOR_TOWER_SOURCE_URL,
            "kind": "sensorTowerAuthorizedApi",
            "rows": len(rows),
            "updatedAt": datetime.now(UTC).isoformat(),
            "period": month,
            "note": "Sensor Tower 授权 API；移动应用商店消费者支出估算，不含 PC、主机与广告收入。",
        }
    return rows, errors, source


def sensor_tower_api_error(error: Exception, *, market: str, token: str) -> str:
    label = "全球" if market == "global" else "中国"
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status in {401, 403}:
        return f"Sensor Tower 授权 API（{label}）未授权或当前套餐无权限；已改用公开转述兜底。"
    text = str(error).replace(token, "[REDACTED]") if token else str(error)
    text = re.sub(r"auth_token=[^&\s]+", "auth_token=[REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return f"Sensor Tower 授权 API（{label}）读取失败：{text[:240]}"


def parse_sensor_tower_top_apps(payload: Any, *, market: str, month: str) -> list[dict[str, Any]]:
    records = sensor_tower_payload_records(payload)
    rows: list[dict[str, Any]] = []
    region = SENSOR_TOWER_MARKET_REGIONS.get(market, market.upper())
    for fallback_rank, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        revenue = sensor_tower_revenue_dollars(record)
        if revenue is None:
            continue
        entities = sensor_tower_entities(record)
        game = first_mapping_value(
            [record, *entities],
            ["unified_app_name", "app_name", "name", "unified_product_name", "custom_tags.unified_product_name"],
        )
        app_id = first_mapping_value(
            [record, *entities],
            ["app_id", "unified_app_id", "platform_app_id"],
        )
        if not game:
            game = app_id
        if not game:
            continue
        platforms = sorted(
            {
                normalized_store_name(first_mapping_value([entity], ["os", "platform", "store"]))
                for entity in entities
                if normalized_store_name(first_mapping_value([entity], ["os", "platform", "store"]))
            }
        ) or ["iOS", "Android"]
        rows.append(
            clean_dict(
                {
                    "market": market,
                    "month": month,
                    "rank": parse_int(record.get("rank")) or fallback_rank,
                    "game": game,
                    "gameZh": first_mapping_value(
                        [record, *entities],
                        ["name_zh", "game_zh", "localized_name", "custom_tags.unified_product_name_zh"],
                    ),
                    "publisher": first_mapping_value(
                        [record, *entities],
                        ["publisher_name", "publisher", "developer_name", "developer"],
                    ),
                    "genre": first_mapping_value(
                        [record, *entities],
                        ["genre", "category", "primary_category", "custom_tags.Primary Category"],
                    ),
                    "platform": " / ".join(platforms),
                    "appId": app_id,
                    "revenue": revenue,
                    "currency": "USD",
                    "downloads": sensor_tower_downloads(record),
                    "source": "Sensor Tower 授权 API",
                    "sourceType": "sensor_tower",
                    "sourcePriority": revenue_source_priority("sensor_tower"),
                    "sourceUrl": SENSOR_TOWER_SOURCE_URL,
                    "method": "estimated",
                    "sourceKind": "authorized_api",
                    "coverageStatus": "modeled",
                    "coveredRegions": [region],
                    "coveragePlatforms": platforms,
                    "excluded": list(REVENUE_EXCLUDED_CHANNELS),
                    "coverageNote": (
                        f"{region}；Sensor Tower 移动应用商店消费者支出估算；"
                        "不含 PC、主机与广告收入。"
                    ),
                    "note": "Sensor Tower 模型估算；金额由 API 美分转换为美元。",
                }
            )
        )
    return sorted(rows, key=lambda row: row.get("rank") or 999999)


def sensor_tower_payload_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "rows", "apps"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return [payload] if any(key in payload for key in ("app_id", "revenue_absolute", "revenue")) else []


def sensor_tower_entities(record: dict[str, Any]) -> list[dict[str, Any]]:
    entities = record.get("entities")
    if isinstance(entities, list):
        return [item for item in entities if isinstance(item, dict)]
    if isinstance(entities, dict):
        if any(key in entities for key in ("name", "app_id", "publisher")):
            return [entities]
        return [item for item in entities.values() if isinstance(item, dict)]
    return []


def first_mapping_value(mappings: list[dict[str, Any]], keys: list[str]) -> str:
    for mapping in mappings:
        for key in keys:
            value = mapping.get(key)
            if value not in (None, "", [], {}):
                return clean_text(value)
            nested: Any = mapping
            for segment in key.split("."):
                nested = nested.get(segment) if isinstance(nested, dict) else None
            if nested not in (None, "", [], {}):
                return clean_text(nested)
    return ""


def sensor_tower_revenue_dollars(record: dict[str, Any]) -> float | None:
    for key in ("revenue_absolute", "unified_revenue", "revenue_cents"):
        value = parse_number(record.get(key))
        if value is not None:
            return value / 100
    for key in ("revenue", "revenue_usd", "estimated_revenue"):
        value = parse_number(record.get(key))
        if value is not None:
            return value
    return None


def sensor_tower_downloads(record: dict[str, Any]) -> float | None:
    for key in ("units_absolute", "unified_units", "downloads", "units"):
        value = parse_number(record.get(key))
        if value is not None:
            return value
    return None


def normalized_store_name(value: Any) -> str:
    text = clean_text(value).lower()
    if text in {"ios", "iphone", "ipad", "apple", "app_store"}:
        return "iOS"
    if text in {"android", "google_play", "googleplay"}:
        return "Android"
    return clean_text(value)


async def fetch_public_sensor_tower_revenue(timeout: float) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        client_token = str(uuid.uuid4())
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            coordinate_httpx_client(client)
            await establish_gacharevenue_session(client, client_token)
            config = await gacharevenue_api(client, "config", client_token=client_token)
            revenue = await gacharevenue_api(client, "revenue", client_token=client_token)
    except Exception as error:
        return [], [f"GACHAREVENUE 公开 Sensor Tower 估算读取失败：{error}"], None

    games = revenue.get("games") if isinstance(revenue, dict) else None
    if not isinstance(games, list):
        return [], ["GACHAREVENUE 返回结构不含 games。"], None

    month = normalize_gacharevenue_month(config.get("current_table") if isinstance(config, dict) else "")
    table_key = gacharevenue_table_key(config.get("current_table") if isinstance(config, dict) else "", games)
    rows = aggregate_gacharevenue_rows(games, month, table_key)
    source = {
        "path": GACHAREVENUE_SOURCE_URL,
        "kind": "publicSensorTowerRevenue",
        "rows": len(rows),
        "updatedAt": config.get("last_updated") if isinstance(config, dict) else "",
        "note": (
            "公开网页转述的 Sensor Tower 移动端估算，覆盖偏二游/抽卡游戏；"
            "中国 Android 按中国 iOS 的 1.75 倍推算，不含 PC、主机与广告收入。"
        ),
    }
    return rows, [], source


async def establish_gacharevenue_session(client: httpx.AsyncClient, client_token: str) -> None:
    response = await client.post(
        f"{GACHAREVENUE_API_BASE}/auth/token",
        headers={
            "X-Client-Token": client_token,
            "X-Request-Path": "/",
            "X-Request-Method": "POST",
        },
    )
    response.raise_for_status()


async def gacharevenue_api(client: httpx.AsyncClient, path: str, *, client_token: str) -> dict[str, Any]:
    request_path = f"/{path}"
    auth_headers = {
        "X-Client-Token": client_token,
        "X-Request-Path": request_path,
        "X-Request-Method": "GET",
    }
    auth = await client.post(f"{GACHAREVENUE_API_BASE}/auth/token", headers=auth_headers)
    auth.raise_for_status()
    token = auth.json()
    headers = {
        "X-Client-Token": client_token,
        "X-Request-Path": request_path,
        "X-Request-Method": "GET",
        "X-Timestamp": str(token.get("timestamp", "")),
        "X-Signature": str(token.get("signature", "")),
        "X-Nonce": str(token.get("nonce", "")),
    }
    response = await client.get(f"{GACHAREVENUE_API_BASE}/{path}", headers=headers)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def gacharevenue_table_key(current_table: str, games: list[dict[str, Any]]) -> str:
    candidates = []
    match = re.fullmatch(r"(20\d{2})-(\d{2})", clean_text(current_table))
    if match:
        candidates.append(f"{match.group(2)}-{match.group(1)}")
        candidates.append(current_table)
    if current_table:
        candidates.append(current_table)

    observed: set[str] = set()
    for game in games[:100]:
        monthly = game.get("monthly_data")
        if isinstance(monthly, dict):
            observed.update(str(key) for key in monthly)

    for candidate in candidates:
        if candidate in observed:
            return candidate
    return sorted(observed, reverse=True)[0] if observed else current_month()


def normalize_gacharevenue_month(current_table: str) -> str:
    text = clean_text(current_table)
    match = re.fullmatch(r"(20\d{2})-(\d{2})", text)
    if match:
        return text
    match = re.fullmatch(r"(\d{2})-(20\d{2})", text)
    if match:
        return f"{match.group(2)}-{match.group(1)}"
    return current_month()


def aggregate_gacharevenue_rows(games: list[dict[str, Any]], month: str, table_key: str) -> list[dict[str, Any]]:
    global_groups: dict[str, dict[str, Any]] = {}
    china_groups: dict[str, dict[str, Any]] = {}

    for game in games:
        if not isinstance(game, dict) or game.get("hidden"):
            continue
        monthly = game.get("monthly_data")
        if not isinstance(monthly, dict):
            continue
        data = monthly.get(table_key)
        if not isinstance(data, dict):
            continue

        revenue, downloads = gacharevenue_values(game, data)
        if revenue <= 0:
            continue

        group_key = normalize_name(game.get("id") or game.get("name_en") or game.get("name"))
        if not group_key:
            continue
        update_revenue_group(global_groups, group_key, game, revenue, downloads)
        if clean_text(game.get("region")).upper() == "CN":
            update_revenue_group(china_groups, group_key, game, revenue, downloads)

    rows = []
    rows.extend(format_gacharevenue_groups(global_groups, "global", month))
    rows.extend(format_gacharevenue_groups(china_groups, "china", month))
    return rows


def gacharevenue_values(game: dict[str, Any], data: dict[str, Any]) -> tuple[float, float]:
    region = clean_text(game.get("region")).upper()
    ios_revenue = parse_number(data.get("ios_revenue")) or 0.0
    ios_downloads = parse_number(data.get("ios_downloads")) or 0.0
    if region == "CN" and ios_revenue:
        return (ios_revenue * 2.75) / 100, ios_downloads * 2.75
    revenue = parse_number(data.get("total_revenue")) or ios_revenue or 0.0
    downloads = parse_number(data.get("total_downloads")) or ios_downloads or 0.0
    return revenue / 100, downloads


def preferred_chinese_game_name(raw_name: Any, english_name: Any = "", game_id: Any = "") -> str:
    name = clean_text(raw_name)
    english = clean_text(english_name)
    if name and name != english and contains_cjk(name):
        return name

    for key in (normalize_name(game_id), normalize_name(english)):
        if key and key in GAME_ZH_OVERRIDES:
            return GAME_ZH_OVERRIDES[key]
    return ""


def contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))


def update_revenue_group(groups: dict[str, dict[str, Any]], key: str, game: dict[str, Any], revenue: float, downloads: float) -> None:
    english_name = clean_text(game.get("name_en")) or clean_text(game.get("name"))
    chinese_name = preferred_chinese_game_name(game.get("name"), english_name, game.get("id"))
    group = groups.setdefault(
        key,
        {
            "game": english_name,
            "gameZh": chinese_name,
            "publisher": clean_text(game.get("publisher")),
            "genre": "Gacha / Mobile",
            "platform": "iOS / Android",
            "revenue": 0.0,
            "downloads": 0.0,
            "artworkUrl": clean_text(game.get("icon")),
            "regions": set(),
        },
    )
    group["revenue"] += revenue
    group["downloads"] += downloads
    region = clean_text(game.get("region"))
    if region:
        group["regions"].add(region.upper())
    if not group.get("publisher") and game.get("publisher"):
        group["publisher"] = clean_text(game.get("publisher"))
    if not group.get("gameZh") and chinese_name:
        group["gameZh"] = chinese_name


def format_gacharevenue_groups(groups: dict[str, dict[str, Any]], market: str, month: str) -> list[dict[str, Any]]:
    rows = sorted(groups.values(), key=lambda row: row.get("revenue") or 0, reverse=True)
    result: list[dict[str, Any]] = []
    for rank, row in enumerate(rows[:DEFAULT_RANK_LIMIT], start=1):
        regions = sorted(row.get("regions") or [])
        includes_china = "CN" in regions
        coverage_note = (
            f"覆盖区域：{', '.join(regions) or '源未声明'}；仅移动端；"
            + (
                "中国 Android = Sensor Tower 中国 iOS 估算 × 1.75（中国合计 = iOS × 2.75）；"
                if includes_china
                else ""
            )
            + "PC、主机、广告收入及源未覆盖地区未统计，缺口不补 0。"
        )
        result.append(
            clean_dict(
                {
                    "market": market,
                    "month": month,
                    "rank": rank,
                    "game": row.get("game"),
                    "gameZh": row.get("gameZh"),
                    "publisher": row.get("publisher"),
                    "genre": row.get("genre"),
                    "platform": row.get("platform"),
                    "revenue": row.get("revenue"),
                    "currency": "USD",
                    "downloads": row.get("downloads"),
                    "source": "GACHAREVENUE / Sensor Tower估算",
                    "sourceType": "sensor_tower",
                    "sourcePriority": revenue_source_priority("sensor_tower") + 5,
                    "sourceUrl": GACHAREVENUE_SOURCE_URL,
                    "artworkUrl": row.get("artworkUrl"),
                    "method": "estimated",
                    "sourceKind": "public_reprint",
                    "coverageStatus": "partial",
                    "coveredRegions": regions,
                    "coveragePlatforms": ["iOS", "Android"],
                    "excluded": list(REVENUE_EXCLUDED_CHANNELS),
                    "formula": "total = iOS + (iOS × 1.75) = iOS × 2.75" if market == "china" else "",
                    "coverageNote": coverage_note,
                    "note": "公开 Sensor Tower 估算转述；仅用于无授权数据时兜底。",
                }
            )
        )
    return result


def load_records_from_path(
    path: Path,
    kind: str,
    parser: Any,
    errors: list[str],
    source_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_records = load_raw_records(path, errors)
    if not raw_records:
        return []

    rows: list[dict[str, Any]] = []
    for record in raw_records:
        parsed = parser(record)
        if parsed:
            rows.append(parsed)

    source_files.append({"path": relative_path(path), "kind": kind, "rows": len(rows)})
    return rows


def load_raw_records(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            return json_payload_to_records(payload)

        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]
    except Exception as error:  # pragma: no cover - defensive import diagnostics
        errors.append(f"{relative_path(path)} 解析失败：{error}")
        return []


def json_payload_to_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]

    if isinstance(payload, dict):
        for key in (
            "rows",
            "data",
            "games",
            "revenue",
            "revenueRows",
            "reportedRevenue",
            "reportedRevenueRows",
            "officialRevenue",
            "mediaRevenue",
            "rankings",
            "rankingRows",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]

    return []


def parse_sensor_tower_revenue_row(record: dict[str, Any]) -> dict[str, Any] | None:
    return parse_revenue_row(record, default_source="Sensor Tower", default_source_type="sensor_tower")


def parse_reported_revenue_row(record: dict[str, Any]) -> dict[str, Any] | None:
    return parse_revenue_row(record, default_source="官方/权威媒体披露", default_source_type="reported")


def parse_revenue_row(
    record: dict[str, Any],
    *,
    default_source: str = "Sensor Tower",
    default_source_type: str = "sensor_tower",
) -> dict[str, Any] | None:
    game = clean_text(value_for(record, "game"))
    revenue = parse_number(value_for(record, "revenue"))
    if not game and revenue is None:
        return None

    country = clean_text(value_for(record, "country"))
    country_code = normalize_country_code(value_for(record, "countryCode")) or country_code_for_name(country)
    market = normalize_market(value_for(record, "market"), country_code=country_code, country=country)
    source = clean_text(value_for(record, "sourceName")) or default_source
    source_type = normalize_revenue_source_type(value_for(record, "sourceType"), source, default_source_type)
    source_priority = parse_int(value_for(record, "sourcePriority")) or revenue_source_priority(source_type)
    platform = clean_text(value_for(record, "platform")) or "iOS / Android"
    method = clean_text(record.get("method")) or ("estimated" if source_type in {"sensor_tower", "estimate"} else "reported")
    covered_regions = normalize_string_list(record.get("coveredRegions") or record.get("covered_regions"))
    if not covered_regions and country_code:
        covered_regions = [country_code.upper()]
    coverage_platforms = normalize_string_list(record.get("coveragePlatforms") or record.get("coverage_platforms"))
    if not coverage_platforms and platform:
        coverage_platforms = [item.strip() for item in platform.split("/") if item.strip()]
    excluded = normalize_string_list(record.get("excluded") or record.get("excluded_channels"))
    coverage_note = clean_text(record.get("coverageNote") or record.get("coverage_note"))
    coverage_status = clean_text(record.get("coverageStatus") or record.get("coverage_status")) or (
        "declared" if coverage_note or covered_regions else "unknown"
    )

    return clean_dict(
        {
            "market": market,
            "month": normalize_month(value_for(record, "month")),
            "rank": parse_int(value_for(record, "rank")),
            "game": game,
            "gameZh": clean_text(value_for(record, "gameZh")) or preferred_chinese_game_name("", game, value_for(record, "appId") or game),
            "publisher": clean_text(value_for(record, "publisher")),
            "genre": clean_text(value_for(record, "genre")),
            "platform": platform,
            "appId": clean_text(value_for(record, "appId")),
            "country": country,
            "countryCode": country_code,
            "revenue": revenue,
            "currency": clean_text(value_for(record, "currency")) or "USD",
            "downloads": parse_number(value_for(record, "downloads")),
            "source": source,
            "sourceType": source_type,
            "sourcePriority": source_priority,
            "method": method,
            "sourceKind": clean_text(record.get("sourceKind") or record.get("source_kind")) or "import",
            "coverageStatus": coverage_status,
            "coveredRegions": covered_regions,
            "coveragePlatforms": coverage_platforms,
            "excluded": excluded,
            "formula": clean_text(record.get("formula")),
            "coverageNote": coverage_note or "覆盖范围以该来源披露口径为准；未披露地区不推算、不补 0。",
            "sourceUrl": clean_text(value_for(record, "url")),
            "artworkUrl": clean_text(value_for(record, "artworkUrl")),
            "note": clean_text(value_for(record, "note")),
        }
    )


def parse_ranking_row(record: dict[str, Any]) -> dict[str, Any] | None:
    provider = normalize_provider(value_for(record, "provider"))
    chart = normalize_chart(value_for(record, "chart"))
    game = clean_text(value_for(record, "game"))
    rank = parse_int(value_for(record, "rank"))
    country = clean_text(value_for(record, "country"))
    country_code = normalize_country_code(value_for(record, "countryCode")) or country_code_for_name(country)

    if not provider or not chart or not country_code or (not game and rank is None):
        return None

    country = country or country_name_for(country_code)
    return clean_dict(
        {
            "provider": provider,
            "chart": chart,
            "rank": rank,
            "game": game,
            "gameZh": clean_text(value_for(record, "gameZh")) or preferred_chinese_game_name("", game, value_for(record, "appId") or game),
            "publisher": clean_text(value_for(record, "publisher")),
            "genre": clean_text(value_for(record, "genre")),
            "platform": clean_text(value_for(record, "platform")) or "iOS",
            "appId": clean_text(value_for(record, "appId")),
            "country": country,
            "countryCode": country_code,
            "url": clean_text(value_for(record, "url")),
            "artworkUrl": clean_text(value_for(record, "artworkUrl")),
            "updatedAt": normalize_datetime(value_for(record, "updatedAt")),
            "source": provider_name(provider),
            "note": clean_text(value_for(record, "note")),
        }
    )


def parse_legacy_rows(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    revenue_rows: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []

    for record in records:
        revenue = parse_number(value_for(record, "revenue"))
        if revenue is not None:
            revenue_rows.append(parse_revenue_row(record) or {})

        for provider in ("diandian", "qimai"):
            free_rank = parse_int(value_for_exact(record, [f"{provider}_rank", f"{provider} rank", f"{provider}排名"]))
            grossing_rank = parse_int(
                value_for_exact(
                    record,
                    [f"{provider}_grossing_rank", f"{provider}_revenue_rank", f"{provider}畅销排名", f"{provider}流水排名"],
                )
            )
            base = {
                "provider": provider,
                "game": value_for(record, "game"),
                "publisher": value_for(record, "publisher"),
                "app_id": value_for(record, "appId"),
                "country": value_for(record, "country") or "中国",
                "country_code": value_for(record, "countryCode") or "cn",
                "updated_at": value_for(record, "month"),
                "note": value_for(record, "note"),
            }
            if free_rank:
                ranking_rows.append(parse_ranking_row({**base, "chart": "free", "rank": free_rank}) or {})
            if grossing_rank:
                ranking_rows.append(parse_ranking_row({**base, "chart": "grossing", "rank": grossing_rank}) or {})

    return compact_rows(revenue_rows), compact_rows(ranking_rows)


def build_markets(
    revenue_rows: list[dict[str, Any]],
    ranking_rows: list[dict[str, Any]],
    countries: list[dict[str, Any]],
    rank_limit: int,
) -> list[dict[str, Any]]:
    ranking_index = index_rankings(ranking_rows)
    country_order = {country["code"]: index for index, country in enumerate(countries)}
    markets: list[dict[str, Any]] = []

    for definition in MARKET_DEFS:
        market_id = definition["id"]
        rows = preferred_revenue_rows([row for row in revenue_rows if row.get("market") == market_id])
        if market_id == "global" and not rows:
            rows = preferred_revenue_rows([row for row in revenue_rows if not row.get("market")])

        rows = sorted(
            rows,
            key=lambda row: (
                row.get("revenue") is None,
                -(row.get("revenue") or 0),
                row.get("rank") if row.get("rank") is not None else 999999,
                row.get("game") or "",
            ),
        )

        top100 = []
        for index, row in enumerate(rows[:rank_limit], start=1):
            top100.append(format_market_row(row, ranking_index, country_order, index))

        markets.append(
            {
                **definition,
                "rankLimit": rank_limit,
                "top100": top100,
                "rowCount": len(top100),
                "coverage": build_market_coverage(top100, rank_limit),
            }
        )

    return markets


def preferred_revenue_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    parents = list(range(len(rows)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    key_owners: dict[str, int] = {}
    for index, row in enumerate(rows):
        keys = match_keys(row)
        if not keys:
            keys = [f"row:{row.get('rank') or index}:{row.get('game') or ''}"]
        for key in keys:
            owner = key_owners.get(key)
            if owner is None:
                key_owners[key] = index
            else:
                union(owner, index)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return [merge_revenue_group(group) for group in groups.values()]


def revenue_group_key(row: dict[str, Any], index: int) -> str:
    keys = match_keys(row)
    if keys:
        return keys[0]
    return f"row:{row.get('rank') or index}:{row.get('game') or ''}"


def merge_revenue_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_month = max((row.get("month") or "" for row in rows), default="")
    candidates = [row for row in rows if (row.get("month") or "") == latest_month] or rows
    candidates = sorted(
        candidates,
        key=lambda row: (
            row.get("sourcePriority", revenue_source_priority(row.get("sourceType", ""))),
            row.get("rank") if row.get("rank") is not None else 999999,
            -(row.get("revenue") or 0),
        ),
    )
    preferred = candidates[0]
    merged: dict[str, Any] = {}
    for row in sorted(candidates, key=lambda item: item.get("sourcePriority", 999), reverse=True):
        for key, value in row.items():
            if value not in (None, "", [], {}):
                merged[key] = value
    for key, value in preferred.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    for key in (
        "method",
        "sourceKind",
        "coverageStatus",
        "coveredRegions",
        "coveragePlatforms",
        "excluded",
        "formula",
        "coverageNote",
        "sourceUrl",
        "note",
    ):
        if preferred.get(key) not in (None, "", [], {}):
            merged[key] = preferred[key]
        else:
            merged.pop(key, None)
    merged["revenueAlternatives"] = [
        clean_dict(
            {
                "source": row.get("source"),
                "sourceType": row.get("sourceType"),
                "revenue": {"amount": row.get("revenue"), "currency": row.get("currency") or "USD"} if row.get("revenue") is not None else None,
                "sourceUrl": row.get("sourceUrl"),
                "note": row.get("note"),
            }
        )
        for row in candidates
    ]
    return merged


def format_market_row(
    row: dict[str, Any],
    ranking_index: dict[str, list[dict[str, Any]]],
    country_order: dict[str, int],
    fallback_rank: int,
) -> dict[str, Any]:
    amount = row.get("revenue")
    currency = row.get("currency") or "USD"
    return clean_dict(
        {
            "rank": fallback_rank,
            "sourceRank": row.get("rank"),
            "watchlistId": row.get("watchlistId"),
            "game": row.get("game"),
            "gameZh": row.get("gameZh"),
            "publisher": row.get("publisher"),
            "genre": row.get("genre"),
            "platform": row.get("platform"),
            "appId": row.get("appId"),
            "artworkUrl": row.get("artworkUrl"),
            "month": row.get("month"),
            "revenue": {"amount": amount, "currency": currency} if amount is not None else None,
            "downloads": row.get("downloads"),
            "source": row.get("source") or "Sensor Tower",
            "sourceType": row.get("sourceType") or "sensor_tower",
            "method": row.get("method"),
            "sourceKind": row.get("sourceKind"),
            "coverageStatus": row.get("coverageStatus"),
            "coveredRegions": row.get("coveredRegions"),
            "coveragePlatforms": row.get("coveragePlatforms"),
            "excluded": row.get("excluded"),
            "formula": row.get("formula"),
            "coverageNote": row.get("coverageNote"),
            "revenueAlternatives": row.get("revenueAlternatives"),
            "sourceUrl": row.get("sourceUrl"),
            "note": row.get("note"),
            "rankings": summarize_rank_snapshots(row, ranking_index, country_order),
        }
    )


def build_market_coverage(rows: list[dict[str, Any]], target_count: int) -> dict[str, Any]:
    available_count = min(len(rows), target_count)
    missing_count = max(target_count - available_count, 0)
    source_scope_partial = any(
        clean_text(row.get("coverageStatus")).lower() in {"partial", "unknown"}
        for row in rows
    )
    status = (
        "missing"
        if not available_count
        else ("partial" if missing_count or source_scope_partial else "complete")
    )
    periods = sorted({clean_text(row.get("month")) for row in rows if clean_text(row.get("month"))}, reverse=True)
    methods = sorted({clean_text(row.get("method")) for row in rows if clean_text(row.get("method"))})
    sources = sorted({clean_text(row.get("source")) for row in rows if clean_text(row.get("source"))})
    covered_regions = sorted(
        {item for row in rows for item in normalize_string_list(row.get("coveredRegions")) if item}
    )
    platforms = sorted(
        {item for row in rows for item in normalize_string_list(row.get("coveragePlatforms")) if item}
    )
    excluded = sorted({item for row in rows for item in normalize_string_list(row.get("excluded")) if item})
    return clean_dict(
        {
            "targetCount": target_count,
            "availableCount": available_count,
            "missingCount": missing_count,
            "status": status,
            "period": periods[0] if periods else "",
            "methods": methods,
            "sources": sources,
            "coveredRegions": covered_regions,
            "platforms": platforms,
            "excluded": excluded,
            "note": (
                "不同游戏的地区覆盖可能不同，各行显示实际覆盖；未列出的地区和渠道不计入，缺口不补 0。"
                if available_count
                else "当前没有可核验记录，未用 0 或虚构条目补榜。"
            ),
            "missingReason": (
                f"当前来源仅提供 {available_count} 条可核验记录；缺少 {missing_count} 条，未补 0、未伪造排名。"
                if missing_count
                else (
                    "排名数量达到目标，但来源的地区或渠道覆盖仍不完整。"
                    if source_scope_partial
                    else "已取得目标数量的可核验记录。"
                )
            ),
        }
    )


def summarize_rank_snapshots(
    row: dict[str, Any],
    ranking_index: dict[str, list[dict[str, Any]]],
    country_order: dict[str, int],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    matches: list[dict[str, Any]] = []
    for key in match_keys(row):
        matches.extend(ranking_index.get(key, []))

    seen: set[tuple[Any, ...]] = set()
    unique_matches = []
    for match in matches:
        key = (match.get("provider"), match.get("countryCode"), match.get("chart"), match.get("rank"))
        if key in seen:
            continue
        seen.add(key)
        unique_matches.append(match)

    payload: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for provider in ("qimai", "diandian"):
        payload[provider] = {}
        for chart in ("free", "grossing"):
            chart_rows = [
                row
                for row in unique_matches
                if row.get("provider") == provider and row.get("chart") == chart and row.get("rank") is not None
            ]
            chart_rows = sorted(
                chart_rows,
                key=lambda item: (country_order.get(item.get("countryCode"), 999), item.get("rank") or 999999),
            )
            payload[provider][chart] = [
                {
                    "countryCode": item.get("countryCode"),
                    "country": item.get("country") or country_name_for(item.get("countryCode", "")),
                    "rank": item.get("rank"),
                    "url": item.get("url"),
                }
                for item in chart_rows[:8]
            ]

    return payload


def build_rank_providers(
    ranking_rows: list[dict[str, Any]],
    countries: list[dict[str, Any]],
    rank_limit: int,
) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []

    for definition in RANK_PROVIDER_DEFS:
        provider_id = definition["id"]
        provider_rows = [row for row in ranking_rows if row.get("provider") == provider_id]
        country_payload = []

        for country in countries:
            country_rows = [row for row in provider_rows if row.get("countryCode") == country["code"]]
            charts = []
            for chart_def in CHART_DEFS:
                chart_rows = [row for row in country_rows if row.get("chart") == chart_def["id"]]
                chart_rows = sorted(chart_rows, key=lambda row: row.get("rank") if row.get("rank") is not None else 999999)
                rows = [format_ranking_row(row) for row in chart_rows[:rank_limit]]
                charts.append(
                    {
                        **chart_def,
                        "source": definition["name"],
                        "rows": rows,
                        "rowCount": len(rows),
                        "updatedAt": latest_value(row.get("updatedAt") for row in chart_rows),
                    }
                )

            country_payload.append(
                {
                    **country,
                    "charts": charts,
                    "rowCount": sum(chart["rowCount"] for chart in charts),
                    "updatedAt": latest_value(row.get("updatedAt") for row in country_rows),
                }
            )

        providers.append(
            {
                **definition,
                "rankLimit": rank_limit,
                "countries": country_payload,
                "rowCount": sum(country["rowCount"] for country in country_payload),
            }
        )

    return providers


def format_ranking_row(row: dict[str, Any]) -> dict[str, Any]:
    return clean_dict(
        {
            "rank": row.get("rank"),
            "watchlistId": row.get("watchlistId"),
            "game": row.get("game"),
            "gameZh": row.get("gameZh"),
            "publisher": row.get("publisher"),
            "genre": row.get("genre"),
            "platform": row.get("platform"),
            "appId": row.get("appId"),
            "country": row.get("country"),
            "countryCode": row.get("countryCode"),
            "url": row.get("url"),
            "artworkUrl": row.get("artworkUrl"),
            "updatedAt": row.get("updatedAt"),
            "note": row.get("note"),
        }
    )


def build_provider_status(
    config: dict[str, Any],
    revenue_rows: list[dict[str, Any]],
    ranking_rows: list[dict[str, Any]],
    source_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    games_config = config.get("games", {})
    sensor_config = games_config.get("sensor_tower", {})
    token_env = sensor_config.get("auth_token_env", "SENSORTOWER_AUTH_TOKEN")
    token_present = bool(os.getenv(token_env))
    reported_rows = [row for row in revenue_rows if row.get("sourceType") in {"official", "media", "reported"}]
    sensor_rows = [row for row in revenue_rows if row.get("sourceType") == "sensor_tower"]
    reported_files = [file for file in source_files if file.get("kind") == "reportedRevenue"]
    revenue_files = [file for file in source_files if file.get("kind") == "sensorTowerRevenue"]
    authorized_revenue_files = [file for file in source_files if file.get("kind") == "sensorTowerAuthorizedApi"]
    public_revenue_files = [file for file in source_files if file.get("kind") == "publicSensorTowerRevenue"]
    if revenue_files:
        sensor_status = "imported"
        sensor_message = f"已读取 {len(sensor_rows)} 条 Sensor Tower 正式导出流水。"
    elif authorized_revenue_files:
        sensor_status = "authorized_api"
        sensor_message = f"已通过 Sensor Tower 授权 API 读取 {len(sensor_rows)} 条移动端消费者支出估算。"
    elif public_revenue_files:
        sensor_status = "configuration_required" if token_present else "public_fallback"
        sensor_message = (
            (
                "Sensor Tower 授权未产出可用数据，当前改用公开估算兜底；请检查 Token 或套餐权限。"
                if token_present
                else f"已读取 {len(sensor_rows)} 条公开 Sensor Tower 估算转述；"
            )
            + "仅移动端且覆盖偏二游/抽卡游戏，中国 Android 按 iOS × 1.75 推算，未覆盖项保持缺失。"
        )
    else:
        sensor_status = "credentials_present" if token_present else "needs_credentials_or_export"
        sensor_message = (
            f"未取得 Sensor Tower 流水；可配置 {token_env} 或导入 data/game_sensor_tower_revenue.csv/json。"
        )

    statuses = [
        {
            "id": "reported_revenue",
            "name": "官方/媒体流水",
            "role": "优先替换 Sensor Tower 流水",
            "status": "imported" if reported_rows else "optional",
            "rows": len(reported_rows),
            "message": (
                f"已读取 {len(reported_rows)} 条官方/权威媒体披露流水，匹配到同一游戏时优先采用。"
                if reported_rows
                else "未发现官方/媒体披露流水；将使用 Sensor Tower 估算作为兜底。"
            ),
            "sourceFiles": reported_files,
        },
        {
            "id": "sensor_tower",
            "name": "Sensor Tower",
            "role": "缺少披露数据时的流水兜底",
            "status": sensor_status,
            "rows": len(sensor_rows),
            "message": sensor_message,
            "sourceFiles": revenue_files or authorized_revenue_files or public_revenue_files,
            "homeUrl": (
                GACHAREVENUE_SOURCE_URL
                if public_revenue_files and not revenue_files and not authorized_revenue_files
                else "https://app.sensortower.com/"
            ),
            "docsUrl": "https://app.sensortower.com/api/docs/app_analysis",
        }
    ]

    for definition in RANK_PROVIDER_DEFS:
        rows = [row for row in ranking_rows if row.get("provider") == definition["id"]]
        files = [file for file in source_files if file.get("kind") == "providerRankings"]
        statuses.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "role": definition["role"],
                "status": "imported" if rows else "needs_login_or_export",
                "rows": len(rows),
                "message": (
                    f"已读取 {len(rows)} 条{definition['name']}国家榜。"
                    if rows
                    else f"未发现{definition['name']}榜单导出；请导入 data/game_rankings.csv/json，字段包含 provider/country_code/chart/rank/game。"
                ),
                "sourceFiles": files,
                "homeUrl": definition["homeUrl"],
            }
        )

    return statuses


def summarize_games(
    markets: list[dict[str, Any]],
    rank_providers: list[dict[str, Any]],
    revenue_rows: list[dict[str, Any]],
    ranking_rows: list[dict[str, Any]],
    countries: list[dict[str, Any]],
    source_files: list[dict[str, Any]],
    rank_limit: int,
) -> dict[str, Any]:
    market_counts = {market["id"]: len(market.get("top100") or []) for market in markets}
    provider_counts = {provider["id"]: provider.get("rowCount", 0) for provider in rank_providers}
    reported_rows = [row for row in revenue_rows if row.get("sourceType") in {"official", "media", "reported"}]
    sensor_rows = [row for row in revenue_rows if row.get("sourceType") == "sensor_tower"]

    return {
        "globalTopCount": market_counts.get("global", 0),
        "chinaTopCount": market_counts.get("china", 0),
        "revenueRows": len(revenue_rows),
        "reportedRevenueRows": len(reported_rows),
        "officialRevenueRows": len([row for row in revenue_rows if row.get("sourceType") == "official"]),
        "mediaRevenueRows": len([row for row in revenue_rows if row.get("sourceType") == "media"]),
        "sensorTowerRevenueRows": len(sensor_rows),
        "rankingRows": len(ranking_rows),
        "qimaiRankingRows": provider_counts.get("qimai", 0),
        "diandianRankingRows": provider_counts.get("diandian", 0),
        "countryCount": len(countries),
        "rankLimit": rank_limit,
        "sourceFiles": source_files,
        "marketCounts": market_counts,
        "providerCounts": provider_counts,
    }


def configured_game_countries(config: dict[str, Any]) -> list[dict[str, Any]]:
    games_config = config.get("games", {})
    raw_countries = games_config.get("countries") or DEFAULT_MAJOR_GAME_COUNTRIES
    countries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(raw_countries, start=1):
        if not isinstance(item, dict):
            continue
        code = normalize_country_code(item.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        countries.append(
            {
                "code": code,
                "name": clean_text(item.get("name")) or country_name_for(code),
                "marketRank": parse_int(item.get("marketRank")) or index,
            }
        )

    return countries[:MAX_MAJOR_COUNTRIES] or DEFAULT_MAJOR_GAME_COUNTRIES


def configured_rank_limit(config: dict[str, Any]) -> int:
    games_config = config.get("games", {})
    try:
        limit = int(games_config.get("rank_limit", DEFAULT_RANK_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_RANK_LIMIT
    return max(1, min(limit, DEFAULT_RANK_LIMIT))


def index_rankings(ranking_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in ranking_rows:
        for key in match_keys(row):
            index.setdefault(key, []).append(row)
    return index


def match_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    app_id = clean_text(row.get("appId"))
    if app_id:
        keys.append(f"appid:{app_id.lower()}")
    game = normalize_name(row.get("game"))
    if game:
        keys.append(f"name:{game}")
    game_zh = normalize_name(row.get("gameZh"))
    if game_zh and game_zh != game:
        keys.append(f"name:{game_zh}")
    return keys


def value_for(record: dict[str, Any], field: str) -> Any:
    return value_for_exact(record, FIELD_ALIASES.get(field, [field]))


def value_for_exact(record: dict[str, Any], aliases: list[str]) -> Any:
    normalized = {normalize_field_name(key): value for key, value in record.items()}
    for alias in aliases:
        value = normalized.get(normalize_field_name(alias))
        if value not in (None, ""):
            return value
    return None


def normalize_field_name(value: Any) -> str:
    return re.sub(r"[\s_\-./:：()（）]+", "", str(value or "").strip().lower())


def normalize_name(value: Any) -> str:
    return re.sub(r"[\s_\-./:：()（）·・]+", "", str(value or "").strip().lower())


def normalize_market(value: Any, *, country_code: str = "", country: str = "") -> str:
    text = normalize_name(value)
    if text in {"china", "cn", "中国", "中國", "mainlandchina"}:
        return "china"
    if text in {"global", "world", "worldwide", "全球", "海外"}:
        return "global"
    if country_code == "cn" or "中国" in country:
        return "china"
    return "global"


def normalize_provider(value: Any) -> str:
    text = normalize_name(value)
    if "qimai" in text or "七麦" in text or "七麥" in text:
        return "qimai"
    if "diandian" in text or "点点" in text or "點點" in text:
        return "diandian"
    return text if text in {"qimai", "diandian"} else ""


def normalize_chart(value: Any) -> str:
    text = normalize_name(value)
    if "grossing" in text or "revenue" in text or "畅销" in text or "收入" in text or "流水" in text:
        return "grossing"
    if "free" in text or "免费" in text:
        return "free"
    return text if text in {"free", "grossing"} else ""


def normalize_revenue_source_type(value: Any, source: str = "", default: str = "reported") -> str:
    text = normalize_name(value)
    source_text = normalize_name(source)
    combined = f"{text}{source_text}"
    if text in {"official", "media", "reported", "sensor_tower", "estimate"}:
        return text
    if "official" in text or "publisher" in text or "company" in text or "官方" in text or "公告" in text or "财报" in text:
        return "official"
    if "media" in text or "press" in text or "news" in text or "媒体" in text or "报道" in text:
        return "media"
    if "sensor" in combined or "sensortower" in combined:
        return "sensor_tower"
    if "official" in combined or "publisher" in combined or "company" in combined or "官方" in combined or "公告" in combined or "财报" in combined:
        return "official"
    if "media" in combined or "press" in combined or "news" in combined or "媒体" in combined or "报道" in combined:
        return "media"
    if "estimate" in combined or "估算" in combined or "预估" in combined:
        return "estimate"
    return default


def revenue_source_priority(source_type: str) -> int:
    return {
        "official": 10,
        "media": 20,
        "reported": 25,
        "sensor_tower": 50,
        "estimate": 60,
    }.get(source_type, 70)


def normalize_country_code(value: Any) -> str:
    text = normalize_name(value)
    if not text:
        return ""
    return COUNTRY_CODE_ALIASES.get(text, text[:2])


def country_name_for(code: str) -> str:
    code = normalize_country_code(code)
    for country in DEFAULT_MAJOR_GAME_COUNTRIES:
        if country["code"] == code:
            return country["name"]
    return code.upper() if code else ""


def country_code_for_name(value: Any) -> str:
    text = normalize_name(value)
    if not text:
        return ""
    for country in DEFAULT_MAJOR_GAME_COUNTRIES:
        if text in {normalize_name(country["name"]), country["code"]}:
            return country["code"]
    aliases = {
        "美国": "us",
        "美國": "us",
        "unitedstates": "us",
        "usa": "us",
        "日本": "jp",
        "韩国": "kr",
        "韓國": "kr",
        "德国": "de",
        "德國": "de",
        "英国": "gb",
        "英國": "gb",
        "france": "fr",
        "法国": "fr",
        "法國": "fr",
        "加拿大": "ca",
        "澳大利亚": "au",
        "澳洲": "au",
        "巴西": "br",
        "墨西哥": "mx",
        "中国": "cn",
        "中國": "cn",
    }
    return aliases.get(text, "")


def provider_name(provider: str) -> str:
    for definition in RANK_PROVIDER_DEFS:
        if definition["id"] == provider:
            return definition["name"]
    return provider


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if not text:
        return None

    multiplier = 1.0
    lowered = text.lower()
    if lowered.endswith("bn") or lowered.endswith("b"):
        multiplier = 1_000_000_000.0
        text = text[:-2] if lowered.endswith("bn") else text[:-1]
    elif lowered.endswith("mn") or lowered.endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-2] if lowered.endswith("mn") else text[:-1]
    elif lowered.endswith("k"):
        multiplier = 1_000.0
        text = text[:-1]
    elif "亿" in text:
        multiplier = 100_000_000.0
        text = text.replace("亿", "")
    elif "万" in text:
        multiplier = 10_000.0
        text = text.replace("万", "")

    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_number(value)
    if number is None:
        return None
    return int(number)


def normalize_month(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return current_month()
    match = re.search(r"(20\d{2})[-/.年]?\s*(\d{1,2})", text)
    if not match:
        return text[:7]
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def normalize_datetime(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return datetime.now(UTC).isoformat()
    if re.fullmatch(r"20\d{2}-\d{2}", text):
        return f"{text}-01T00:00:00+00:00"
    return text


def current_month() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m")


def latest_value(values: Any) -> str:
    clean_values = sorted({value for value in values if value}, reverse=True)
    return clean_values[0] if clean_values else ""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_string_list(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(dict.fromkeys(clean_text(item) for item in value if clean_text(item)))
    return list(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"[,;，；|]", clean_text(value))
            if item.strip()
        )
    )


def clean_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row]


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


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


async def load_latest_games(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_games_sync, db_path)


async def save_latest_games(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_games_sync, db_path, data)


def load_latest_games_sync(db_path: Path) -> dict[str, Any] | None:
    ensure_games_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_games WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_games_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_games_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_games WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_games (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (
                data.get("generatedAt"),
                data.get("savedAt"),
                data.get("expiresAt"),
                json.dumps(data, ensure_ascii=False),
            ),
        )
        conn.commit()


def ensure_games_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_games (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.commit()
