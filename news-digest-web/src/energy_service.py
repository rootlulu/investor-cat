from __future__ import annotations

import asyncio
import copy
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .commodity_service import clean_html, load_config, parse_dt, resolve_sqlite_path, safe_float, user_agent

ENERGY_CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
ENERGY_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
ENERGY_SCHEMA_VERSION = 1

NBS_RELEASE_INDEXES = [
    "https://www.stats.gov.cn/sj/zxfb/index.html",
    "https://www.stats.gov.cn/sj/zxfb/index_1.html",
    "https://www.stats.gov.cn/sj/zxfb/index_2.html",
]
FALLBACK_ENERGY_RELEASE_URL = "https://www.stats.gov.cn/sj/zxfb/202606/t20260616_1963948.html"
FALLBACK_INDUSTRIAL_RELEASE_URL = "https://www.stats.gov.cn/sj/zxfb/202606/t20260616_1963953.html"
NUMBER_PATTERN = r"[-+]?\d+(?:\.\d+)?"

METRIC_DEFINITIONS: list[dict[str, str]] = [
    {"id": "raw_coal", "name": "原煤", "category": "煤炭", "label": "原煤（万吨）", "unit": "万吨"},
    {"id": "coke", "name": "焦炭", "category": "煤炭", "label": "焦炭（万吨）", "unit": "万吨"},
    {"id": "crude_oil", "name": "原油", "category": "油气", "label": "原油（万吨）", "unit": "万吨"},
    {"id": "crude_oil_processing", "name": "原油加工量", "category": "油气", "label": "原油加工量（万吨）", "unit": "万吨"},
    {"id": "natural_gas", "name": "天然气", "category": "油气", "label": "天然气（亿立方米）", "unit": "亿立方米"},
    {"id": "power_generation", "name": "规上工业发电量", "category": "电力", "label": "规模以上工业发电量（亿千瓦时）", "unit": "亿千瓦时"},
    {"id": "thermal_power", "name": "火力发电量", "category": "电力", "label": "火力发电量（亿千瓦时）", "unit": "亿千瓦时"},
    {"id": "hydro_power", "name": "水力发电量", "category": "电力", "label": "水力发电量（亿千瓦时）", "unit": "亿千瓦时"},
    {"id": "nuclear_power", "name": "核能发电量", "category": "电力", "label": "核能发电量（亿千瓦时）", "unit": "亿千瓦时"},
    {"id": "wind_power", "name": "风力发电量", "category": "电力", "label": "风力发电量（亿千瓦时）", "unit": "亿千瓦时"},
    {"id": "solar_power", "name": "太阳能发电量", "category": "电力", "label": "太阳能发电量（亿千瓦时）", "unit": "亿千瓦时"},
]

FALLBACK_HISTORIES: dict[str, list[dict[str, Any]]] = {
    "raw_coal": [
        {"period": "2026-03", "periodLabel": "3月", "value": 44062, "yoy": 0.0},
        {"period": "2026-04", "periodLabel": "4月", "value": 38563, "yoy": -1.0},
        {"period": "2026-05", "periodLabel": "5月", "value": 39722, "yoy": -1.7},
    ],
    "coke": [
        {"period": "2026-03", "periodLabel": "3月", "value": 4276, "yoy": 3.7},
        {"period": "2026-04", "periodLabel": "4月", "value": 4153, "yoy": 0.0},
        {"period": "2026-05", "periodLabel": "5月", "value": 4272, "yoy": 1.1},
    ],
    "crude_oil": [
        {"period": "2026-03", "periodLabel": "3月", "value": 1907, "yoy": 0.2},
        {"period": "2026-04", "periodLabel": "4月", "value": 1794, "yoy": 1.2},
        {"period": "2026-05", "periodLabel": "5月", "value": 1857, "yoy": 0.5},
    ],
    "crude_oil_processing": [
        {"period": "2026-03", "periodLabel": "3月", "value": 6167, "yoy": -2.2},
        {"period": "2026-04", "periodLabel": "4月", "value": 5465, "yoy": -5.8},
        {"period": "2026-05", "periodLabel": "5月", "value": 5372, "yoy": -9.1},
    ],
    "natural_gas": [
        {"period": "2026-03", "periodLabel": "3月", "value": 234, "yoy": 3.0},
        {"period": "2026-04", "periodLabel": "4月", "value": 219, "yoy": 1.9},
        {"period": "2026-05", "periodLabel": "5月", "value": 217, "yoy": -2.2},
    ],
    "power_generation": [
        {"period": "2026-03", "periodLabel": "3月", "value": 8025, "yoy": 1.4},
        {"period": "2026-04", "periodLabel": "4月", "value": 7440, "yoy": 2.6},
        {"period": "2026-05", "periodLabel": "5月", "value": 7843, "yoy": 4.2},
    ],
    "thermal_power": [
        {"period": "2026-03", "periodLabel": "3月", "value": 5327, "yoy": 4.2},
        {"period": "2026-04", "periodLabel": "4月", "value": 4638, "yoy": 3.1},
        {"period": "2026-05", "periodLabel": "5月", "value": 4726, "yoy": 2.1},
    ],
    "hydro_power": [
        {"period": "2026-03", "periodLabel": "3月", "value": 862, "yoy": 10.8},
        {"period": "2026-04", "periodLabel": "4月", "value": 881, "yoy": 12.2},
        {"period": "2026-05", "periodLabel": "5月", "value": 1120, "yoy": 13.0},
    ],
    "nuclear_power": [
        {"period": "2026-03", "periodLabel": "3月", "value": 378, "yoy": -11.8},
        {"period": "2026-04", "periodLabel": "4月", "value": 375, "yoy": -8.7},
        {"period": "2026-05", "periodLabel": "5月", "value": 403, "yoy": 5.0},
    ],
    "wind_power": [
        {"period": "2026-03", "periodLabel": "3月", "value": 912, "yoy": -17.3},
        {"period": "2026-04", "periodLabel": "4月", "value": 974, "yoy": -5.0},
        {"period": "2026-05", "periodLabel": "5月", "value": 969, "yoy": 0.5},
    ],
    "solar_power": [
        {"period": "2026-03", "periodLabel": "3月", "value": 547, "yoy": 10.0},
        {"period": "2026-04", "periodLabel": "4月", "value": 571, "yoy": 7.1},
        {"period": "2026-05", "periodLabel": "5月", "value": 624, "yoy": 12.1},
    ],
}

FALLBACK_CUMULATIVE: dict[str, dict[str, Any]] = {
    "raw_coal": {"cumulativeValue": 198043, "cumulativeYoy": -0.3},
    "coke": {"cumulativeValue": 21037, "cumulativeYoy": 1.9},
    "crude_oil": {"cumulativeValue": 9131, "cumulativeYoy": 1.1},
    "crude_oil_processing": {"cumulativeValue": 29280, "cumulativeYoy": -2.2},
    "natural_gas": {"cumulativeValue": 1117, "cumulativeYoy": 1.7},
    "power_generation": {"cumulativeValue": 39129, "cumulativeYoy": 3.6},
    "thermal_power": {"cumulativeValue": 25283, "cumulativeYoy": 3.4},
    "hydro_power": {"cumulativeValue": 4426, "cumulativeYoy": 10.9},
    "nuclear_power": {"cumulativeValue": 1919, "cumulativeYoy": -2.5},
    "wind_power": {"cumulativeValue": 4820, "cumulativeYoy": -2.1},
    "solar_power": {"cumulativeValue": 2680, "cumulativeYoy": 10.7},
}


async def get_energy(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    async with ENERGY_CACHE_LOCK:
        if (
            not force
            and not refresh
            and ENERGY_CACHE["data"]
            and ENERGY_CACHE["data"].get("schemaVersion") == ENERGY_SCHEMA_VERSION
            and datetime.now(UTC) < ENERGY_CACHE["expires_at"]
        ):
            cached = dict(ENERGY_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = await load_latest_energy(db_path)
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == ENERGY_SCHEMA_VERSION)
    stored_is_fresh = bool(stored_schema_valid and parse_dt(stored.get("expiresAt", "")) > datetime.now(UTC))
    if not force and stored and stored_schema_valid and ((allow_stale and not refresh) or stored_is_fresh):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with ENERGY_CACHE_LOCK:
            ENERGY_CACHE["data"] = stored
            ENERGY_CACHE["expires_at"] = parse_dt(stored.get("expiresAt", ""))
        return stored

    rows = build_fallback_rows()
    errors: list[str] = []
    energy_release_url = FALLBACK_ENERGY_RELEASE_URL
    industrial_release_url = FALLBACK_INDUSTRIAL_RELEASE_URL
    timeout = float(fetch_config.get("request_timeout_seconds", 8))

    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout), verify=False) as client:
        try:
            energy_links = await find_nbs_release_links(client, "能源生产情况", limit=1)
            if energy_links:
                energy_release_url = energy_links[0]["url"]
        except Exception as error:
            errors.append(f"能源生产发布页索引失败：{error}")

        try:
            industrial_links = await find_nbs_release_links(client, "规模以上工业增加值增长", limit=6)
            if industrial_links:
                industrial_release_url = industrial_links[0]["url"]
            else:
                industrial_links = [{"title": "2026年5月份规模以上工业增加值增长4.5%", "url": FALLBACK_INDUSTRIAL_RELEASE_URL}]

            parsed_pages = await asyncio.gather(
                *(fetch_industrial_energy_page(client, link) for link in reversed(industrial_links)),
                return_exceptions=True,
            )
            for result in parsed_pages:
                if isinstance(result, Exception):
                    errors.append(f"工业生产主要数据抓取失败：{result}")
                    continue
                for row_id, update in result.items():
                    merge_energy_row(rows, row_id, update)
        except Exception as error:
            errors.append(f"工业生产主要数据索引失败：{error}")

    finalize_rows(rows)
    now = datetime.now(UTC)
    data = {
        "schemaVersion": ENERGY_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": bool(rows),
        "source": "国家统计局能源生产情况 / 规模以上工业生产主要数据",
        "cadence": "半小时最多刷新一次；月度官方发布后自动读取最新快照",
        "errors": errors,
        "links": [
            {"label": "能源生产情况", "url": energy_release_url},
            {"label": "规模以上工业生产主要数据", "url": industrial_release_url},
        ],
        "summary": build_summary(rows),
        "sections": build_sections(rows),
        "rows": rows,
    }
    await save_latest_energy(db_path, data)
    async with ENERGY_CACHE_LOCK:
        ENERGY_CACHE["data"] = data
        ENERGY_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


def build_fallback_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in METRIC_DEFINITIONS:
        history = copy.deepcopy(FALLBACK_HISTORIES.get(definition["id"], []))
        latest = history[-1] if history else {}
        cumulative = FALLBACK_CUMULATIVE.get(definition["id"], {})
        rows.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "category": definition["category"],
                "unit": definition["unit"],
                "period": latest.get("period", "2026-05"),
                "periodLabel": latest.get("periodLabel", "5月"),
                "value": latest.get("value"),
                "yoy": latest.get("yoy"),
                "mom": latest.get("mom"),
                "cumulativeValue": cumulative.get("cumulativeValue"),
                "cumulativeYoy": cumulative.get("cumulativeYoy"),
                "cumulativePeriodLabel": "1—5月",
                "source": "国家统计局",
                "sourceUrl": FALLBACK_INDUSTRIAL_RELEASE_URL,
                "note": "规模以上工业月度产品产量；环比按当月绝对量与上月绝对量计算。",
                "history": history,
            }
        )
    finalize_rows(rows)
    return rows


async def find_nbs_release_links(client: httpx.AsyncClient, keyword: str, limit: int = 6) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for index_url in NBS_RELEASE_INDEXES:
        try:
            html = await fetch_text(client, index_url, "国家统计局索引")
        except Exception:
            continue
        for link in extract_release_links(html, keyword, index_url):
            found.setdefault(link["url"], link)
    links = list(found.values())
    links.sort(key=lambda item: period_sort_key(item.get("title", "")), reverse=True)
    return links[:limit]


def extract_release_links(html: str, keyword: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
        text = clean_html(title)
        if keyword not in text:
            continue
        links.append({"title": text, "url": urljoin(base_url, href)})
    return links


async def fetch_industrial_energy_page(client: httpx.AsyncClient, link: dict[str, str]) -> dict[str, dict[str, Any]]:
    url = link["url"]
    html = await fetch_text(client, url, "国家统计局工业生产主要数据")
    title = link.get("title") or extract_title(html)
    return parse_industrial_energy_rows(html, title, url)


def parse_industrial_energy_rows(html: str, title: str, url: str) -> dict[str, dict[str, Any]]:
    period, period_label, cumulative_period_label = period_from_title(title)
    if not period:
        period, period_label, cumulative_period_label = "2026-05", "5月", "1—5月"
    text = normalize_text(clean_html(html))
    updates: dict[str, dict[str, Any]] = {}
    for definition in METRIC_DEFINITIONS:
        match = re.search(
            rf"{re.escape(definition['label'])}\s+({NUMBER_PATTERN})\s+({NUMBER_PATTERN})\s+({NUMBER_PATTERN})\s+({NUMBER_PATTERN})",
            text,
        )
        if not match:
            continue
        value, yoy, cumulative_value, cumulative_yoy = (safe_float(part) for part in match.groups())
        updates[definition["id"]] = {
            "period": period,
            "periodLabel": period_label,
            "value": value,
            "yoy": yoy,
            "cumulativeValue": cumulative_value,
            "cumulativeYoy": cumulative_yoy,
            "cumulativePeriodLabel": cumulative_period_label,
            "source": "国家统计局",
            "sourceUrl": url,
            "note": "规模以上工业生产主要数据；环比按当月绝对量与上月绝对量计算。",
        }
    return updates


def period_from_title(title: str) -> tuple[str, str, str]:
    text = normalize_text(title)
    range_match = re.search(r"(\d{4})年1\s*[—\-－–]\s*(\d{1,2})月份", text)
    if range_match:
        year = int(range_match.group(1))
        month = int(range_match.group(2))
        period = f"{year:04d}-{month:02d}"
        period_label = "1—2月" if month == 2 else f"{month}月"
        return period, period_label, f"1—{month}月"

    month_match = re.search(r"(\d{4})年(\d{1,2})月份", text)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        return f"{year:04d}-{month:02d}", f"{month}月", f"1—{month}月"

    return "", "", ""


def period_sort_key(title: str) -> str:
    period, _, _ = period_from_title(title)
    return period


async def fetch_text(client: httpx.AsyncClient, url: str, label: str) -> str:
    response = await client.get(url, headers={"User-Agent": user_agent(), "Accept": "text/html,application/xhtml+xml"})
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "utf-8"
    text = response.text
    if not text.strip():
        raise ValueError(f"{label}返回为空")
    return text


def merge_energy_row(rows: list[dict[str, Any]], row_id: str, update: dict[str, Any]) -> None:
    target = next((row for row in rows if row.get("id") == row_id), None)
    if not target:
        return

    append_history_point(target, update)
    update_period = str(update.get("period") or "")
    current_period = str(target.get("period") or "")
    if current_period and update_period < current_period:
        return

    for key, value in update.items():
        if value is not None:
            target[key] = value


def append_history_point(target: dict[str, Any], update: dict[str, Any]) -> None:
    period = update.get("period") or target.get("period")
    if not period:
        return
    history = target.setdefault("history", [])
    point = next((item for item in history if item.get("period") == period), None)
    if not point:
        point = {"period": period}
        history.append(point)
    for key in ["periodLabel", "value", "yoy", "mom"]:
        if key in update and update[key] is not None:
            point[key] = update[key]


def finalize_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        history = sorted(row.get("history") or [], key=lambda point: str(point.get("period") or ""))
        for index, point in enumerate(history):
            value = safe_float(point.get("value"))
            if value is None:
                continue
            previous_value = safe_float(history[index - 1].get("value")) if index > 0 else None
            previous_is_monthly = index > 0 and is_monthly_point(history[index - 1])
            current_is_monthly = is_monthly_point(point)
            if point.get("mom") is None and previous_value not in (None, 0) and previous_is_monthly and current_is_monthly:
                point["mom"] = round((value / previous_value - 1) * 100, 2)

            open_value = previous_value if previous_value is not None and previous_is_monthly and current_is_monthly else value
            point["open"] = open_value
            point["close"] = value
            point["high"] = max(open_value, value)
            point["low"] = min(open_value, value)

        row["history"] = history[-12:]
        latest = next((point for point in reversed(history) if point.get("period") == row.get("period")), None)
        if latest and latest.get("mom") is not None:
            row["mom"] = latest["mom"]


def is_monthly_point(point: dict[str, Any]) -> bool:
    label = str(point.get("periodLabel") or "")
    return not any(token in label for token in ["—", "-", "累计", "全年"])


def build_sections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["煤炭", "油气", "电力"]
    sections = []
    for category in order:
        items = [row for row in rows if row.get("category") == category]
        if items:
            sections.append({"id": category, "name": category, "rowCount": len(items), "rows": items})
    return sections


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_period = max((str(row.get("period") or "") for row in rows), default="")
    categories = {row.get("category") for row in rows if row.get("category")}
    source_urls = {row.get("sourceUrl") for row in rows if row.get("sourceUrl")}
    power_rows = [row for row in rows if row.get("category") == "电力"]
    return {
        "latestPeriod": latest_period,
        "categoryCount": len(categories),
        "rowCount": len(rows),
        "coalCount": sum(1 for row in rows if row.get("category") == "煤炭"),
        "oilGasCount": sum(1 for row in rows if row.get("category") == "油气"),
        "powerCount": len(power_rows),
        "klineCount": sum(1 for row in rows if len(row.get("history") or []) >= 2),
        "sourceCount": len(source_urls),
    }


def extract_title(html: str) -> str:
    for pattern in [r"<h1[^>]*>(.*?)</h1>", r"<title>(.*?)</title>"]:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return clean_html(match.group(1))
    return ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


async def load_latest_energy(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_energy_sync, db_path)


async def save_latest_energy(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_energy_sync, db_path, data)


def load_latest_energy_sync(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_energy_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_energy WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_energy_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_energy_table(db_path)
    payload = json.dumps(data, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_energy WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_energy (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (data.get("generatedAt", ""), data.get("savedAt", ""), data.get("expiresAt", ""), payload),
        )


def ensure_energy_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_energy (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
