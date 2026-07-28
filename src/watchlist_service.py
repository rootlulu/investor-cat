from __future__ import annotations

import asyncio
import copy
import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests

from .request_coordinator import (
    DomainCoolingDown,
    coordinate_requests_session,
    coordinated_requests_request,
)
from .stock_research import build_portfolio_exposure_notice, build_stock_research_snapshot
from .stock_service import safe_float

try:
    WATCHLIST_MARKET_TIMEZONES = {
        "a_share": ZoneInfo("Asia/Shanghai"),
        "hk": ZoneInfo("Asia/Hong_Kong"),
        "us": ZoneInfo("America/New_York"),
    }
except Exception:
    WATCHLIST_MARKET_TIMEZONES = {
        "a_share": UTC,
        "hk": UTC,
        "us": UTC,
    }

ROOT_DIR = Path(__file__).resolve().parents[1]
WATCHLIST_CONFIG_PATH = ROOT_DIR / "config" / "stock_watchlist.json"
WATCHLIST_DETAIL_CACHE_PATH = ROOT_DIR / "data" / "stock_watch_details.json"

EASTMONEY_QUOTE_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_CAPITAL_FLOW_API = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
EASTMONEY_CAPITAL_FLOW_APIS = (
    "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
    "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get",
    EASTMONEY_CAPITAL_FLOW_API,
    "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
)
EASTMONEY_DATACENTER_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REPORT_API = "https://reportapi.eastmoney.com/report/list"
EASTMONEY_REPORT_POST_API = "https://reportapi.eastmoney.com/report/list2"
EASTMONEY_REPORT_PAGE = "https://data.eastmoney.com/report/stock.jshtml"
EASTMONEY_ANNOUNCEMENT_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
EASTMONEY_GUBA_API = "https://gbapi.eastmoney.com/webarticlelist/api/Article/Articlelist"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
BING_NEWS_RSS = "https://www.bing.com/news/search"
XUEQIU_SEARCH_API = "https://xueqiu.com/statuses/search.json"
XUEQIU_SEARCH_APIS = (
    XUEQIU_SEARCH_API,
    "https://xueqiu.com/query/v1/symbol/search/status.json",
    "https://xueqiu.com/statuses/stock_timeline.json",
)
SINA_CAPITAL_FLOW_API = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs"
YAHOO_CHART_APIS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)
TENCENT_QUOTE_API = "https://qt.gtimg.cn/q="
AASTOCKS_SHORT_SELLING_URL = "https://www.aastocks.com/en/stocks/market/shortselling/stock-short-selling-ratio.aspx"
AASTOCKS_INTEREST_DISCLOSURE_URL = "https://www.aastocks.com/en/stock/interestsdisclosure.aspx"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

WATCHLIST_CACHE_SECONDS = 90
DETAIL_CACHE_SECONDS = 30 * 60
DETAIL_CACHE_VERSION = 3
WATCHLIST_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": None, "version": 0}
WATCHLIST_STATE: dict[str, Any] = {"version": 0}
DETAIL_CACHE: dict[str, dict[str, Any]] = {}
DETAIL_STORE_LOCK = threading.Lock()
WATCHLIST_LOCK = asyncio.Lock()
QUOTE_PROVENANCE_FIELDS = (
    "price",
    "changePct",
    "change",
    "volume",
    "amount",
    "marketCap",
    "floatMarketCap",
    "pe",
    "pb",
    "turnoverRate",
)


async def get_stock_watchlist(refresh: bool = False) -> dict[str, Any]:
    while True:
        async with WATCHLIST_LOCK:
            version = WATCHLIST_STATE["version"]
            if (
                not refresh
                and WATCHLIST_CACHE["data"]
                and WATCHLIST_CACHE.get("version") == version
                and time.time() < WATCHLIST_CACHE["expires_at"]
            ):
                data = dict(WATCHLIST_CACHE["data"])
                data["cached"] = True
                return data

        data = await asyncio.to_thread(fetch_stock_watchlist_sync)
        async with WATCHLIST_LOCK:
            if WATCHLIST_STATE["version"] != version:
                continue
            WATCHLIST_CACHE["data"] = data
            WATCHLIST_CACHE["version"] = version
            WATCHLIST_CACHE["expires_at"] = time.time() + WATCHLIST_CACHE_SECONDS
            return data


async def get_stock_watch_detail(stock_id: str, refresh: bool = False) -> dict[str, Any]:
    cached_payload: dict[str, Any] | None = None
    async with WATCHLIST_LOCK:
        if not stock_id_exists(stock_id):
            raise ValueError(f"unknown stock id: {stock_id}")
        cached = DETAIL_CACHE.get(stock_id)
        if not refresh and cached and time.time() < cached.get("expires_at", 0):
            cached_payload = cached["data"]

    if cached_payload is not None:
        data = await asyncio.to_thread(hydrate_detail_quote_sync, stock_id, cached_payload)
        data["cached"] = True
        return data

    if not refresh:
        disk_cached = await asyncio.to_thread(read_cached_detail_sync, stock_id)
        if disk_cached:
            disk_cached = await asyncio.to_thread(hydrate_detail_quote_sync, stock_id, disk_cached)
            async with WATCHLIST_LOCK:
                DETAIL_CACHE[stock_id] = {"expires_at": time.time() + DETAIL_CACHE_SECONDS, "data": disk_cached}
            return disk_cached

    data = await asyncio.to_thread(fetch_and_store_detail_sync, stock_id)
    async with WATCHLIST_LOCK:
        DETAIL_CACHE[stock_id] = {"expires_at": time.time() + DETAIL_CACHE_SECONDS, "data": data}
    return data


async def import_stock_to_watchlist(query: str, market: str = "", name: str = "") -> dict[str, Any]:
    candidate = resolve_import_stock(query, market, name)

    async with WATCHLIST_LOCK:
        existing = find_watchlist_match(load_watchlist_config(), candidate)
    if existing:
        detail_prefetched, detail_error = await refresh_watchlist_detail_cache(existing["id"])
        data = await get_stock_watchlist(refresh=True)
        row = next((item for item in data.get("items", []) if item.get("id") == existing.get("id")), stock_public_fields(existing))
        result = {
            **data,
            "imported": False,
            "stock": row,
            "message": "股票已在自选列表",
            "detailPrefetched": detail_prefetched,
            "detailPrefetchError": detail_error,
        }
        if detail_error:
            result["errors"] = [*(result.get("errors") or []), detail_error]
        return result

    quote_map = await asyncio.to_thread(fetch_quotes_sync, [candidate])
    quote = quote_map.get(candidate["id"]) or {}
    if not quote or not any(quote.get(key) is not None for key in ("price", "amount", "marketCap")):
        raise ValueError("没有查到可用行情，请检查股票代码和市场。")
    quote_name = normalize_text(quote.get("quoteName"))
    if not normalize_text(name) and quote_name:
        candidate["name"] = quote_name

    async with WATCHLIST_LOCK:
        stocks = load_watchlist_config()
        existing = find_watchlist_match(stocks, candidate)
        if existing:
            stock_id = existing["id"]
            imported = False
        else:
            stocks.append(candidate)
            save_watchlist_config(stocks)
            stock_id = candidate["id"]
            imported = True
        invalidate_watchlist_cache(stock_id)

    detail_prefetched, detail_error = await refresh_watchlist_detail_cache(stock_id)
    data = await get_stock_watchlist(refresh=True)
    row = next((item for item in data.get("items", []) if item.get("id") == stock_id), stock_public_fields(candidate))
    result = {
        **data,
        "imported": imported,
        "stock": row,
        "message": "已导入股票" if imported else "股票已在自选列表",
        "detailPrefetched": detail_prefetched,
        "detailPrefetchError": detail_error,
    }
    if detail_error:
        result["errors"] = [*(result.get("errors") or []), detail_error]
    return result


async def refresh_watchlist_detail_cache(stock_id: str) -> tuple[bool, str]:
    try:
        data = await asyncio.to_thread(fetch_and_store_detail_sync, stock_id)
    except Exception as error:
        return False, f"详情预抓取暂未完成：{error}"

    async with WATCHLIST_LOCK:
        DETAIL_CACHE[stock_id] = {"expires_at": time.time() + DETAIL_CACHE_SECONDS, "data": data}
    return True, ""


async def update_stock_watchlist_item(stock_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = normalize_text(payload.get("name"))
    if not name:
        raise ValueError("名称不能为空。")

    async with WATCHLIST_LOCK:
        stocks = load_watchlist_config()
        stock = next((item for item in stocks if item.get("id") == stock_id), None)
        if not stock:
            raise ValueError(f"unknown stock id: {stock_id}")
        stock["name"] = name
        save_watchlist_config(stocks)
        update_cached_detail_stock_name(stock_id, name)
        invalidate_watchlist_cache(stock_id, keep_detail_memory=True)

    data = await get_stock_watchlist(refresh=True)
    row = next((item for item in data.get("items", []) if item.get("id") == stock_id), stock_public_fields(stock))
    return {**data, "updated": True, "stock": row, "message": "已更新自选股票"}


async def delete_stock_from_watchlist(stock_id: str) -> dict[str, Any]:
    async with WATCHLIST_LOCK:
        stocks = load_watchlist_config()
        next_stocks = [item for item in stocks if item.get("id") != stock_id]
        if len(next_stocks) == len(stocks):
            raise ValueError(f"unknown stock id: {stock_id}")
        save_watchlist_config(next_stocks)
        remove_cached_detail(stock_id)
        invalidate_watchlist_cache(stock_id)

    data = await get_stock_watchlist(refresh=True)
    return {**data, "deleted": True, "deletedId": stock_id, "message": "已删除自选股票"}


async def prefetch_stock_watchlist_details(force: bool = False, stock_ids: list[str] | None = None) -> dict[str, Any]:
    stocks = load_watchlist_config()
    allowed = set(stock_ids or [])
    targets = [stock for stock in stocks if not allowed or stock.get("id") in allowed]
    semaphore = asyncio.Semaphore(3)

    async def prefetch_one(stock: dict[str, Any]) -> tuple[str, str]:
        stock_id = stock["id"]
        async with semaphore:
            if not force and await asyncio.to_thread(read_cached_detail_sync, stock_id, True):
                return "skipped", ""
            try:
                await asyncio.to_thread(fetch_and_store_detail_sync, stock_id)
                return "refreshed", ""
            except Exception as error:
                return "error", f"{stock.get('name') or stock_id} 详情预抓取失败：{error}"

    results = await asyncio.gather(*(prefetch_one(stock) for stock in targets))
    refreshed = sum(1 for status, _ in results if status == "refreshed")
    skipped = sum(1 for status, _ in results if status == "skipped")
    errors = [message for status, message in results if status == "error" and message]

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "refreshed": refreshed,
        "skipped": skipped,
        "total": len(targets),
        "errors": errors,
    }


def fetch_stock_watchlist_sync() -> dict[str, Any]:
    stocks = load_watchlist_config()
    errors: list[str] = []
    try:
        quote_map = fetch_quotes_sync(stocks)
    except Exception as error:
        quote_map = {}
        errors.append(f"自选行情暂未取到：{error}")
    items = []
    for stock in stocks:
        quote = quote_map.get(stock["id"])
        if not quote:
            errors.append(f"{stock['name']} 行情暂未取到")
            quote = empty_quote(stock)
        items.append({**stock_public_fields(stock), **quote, **detail_cache_meta(stock["id"])})

    generated_at = datetime.now(UTC).isoformat()
    return {
        "generatedAt": generated_at,
        "cached": False,
        "source": "东方财富行情 / Google News / 东方财富股吧 / 雪球 / 东方财富资金流向 / 东方财富公告与研报",
        "items": items,
        "portfolioExposure": build_portfolio_exposure_notice(items),
        "errors": errors,
    }


def fetch_stock_detail_sync(stock_id: str) -> dict[str, Any]:
    stocks = load_watchlist_config()
    stock = next((item for item in stocks if item["id"] == stock_id), None)
    if not stock:
        raise ValueError(f"unknown stock id: {stock_id}")

    errors: list[str] = []
    try:
        quote = fetch_quotes_sync([stock]).get(stock["id"]) or empty_quote(stock)
    except Exception as error:
        quote = empty_quote(stock)
        errors.append(f"行情暂未取到：{error}")
    sections = {
        "shortInterest": safe_section(lambda: fetch_short_interest_sync(stock), errors, "做空信息"),
        "shareholders": safe_section(lambda: fetch_shareholders_sync(stock), errors, "大小股东"),
        "shareholderDistribution": safe_section(lambda: fetch_shareholder_distribution_sync(stock), errors, "股东分布比例"),
        "fundHoldings": safe_section(lambda: fetch_fund_holdings_sync(stock), errors, "基金重仓"),
        "news": safe_section(lambda: fetch_company_news_sync(stock, 20), errors, "公司资讯"),
        "socialPosts": safe_section(lambda: fetch_social_posts_sync(stock, 15), errors, "社区热帖"),
        "capitalFlow": safe_section(lambda: fetch_capital_flow_sync(stock), errors, "资金流向"),
        "announcements": safe_section(lambda: fetch_announcements_sync(stock, 15), errors, "公司动态"),
        "ratings": safe_section(lambda: fetch_ratings_sync(stock, 15), errors, "券商评级"),
    }

    generated_at = datetime.now(UTC).isoformat()
    stock_payload = {**stock_public_fields(stock), **quote}
    return {
        "generatedAt": generated_at,
        "cached": False,
        "stock": stock_payload,
        "sections": sections,
        "research": build_stock_research_snapshot(stock_payload, sections, generated_at=generated_at),
        "errors": errors,
    }


def fetch_and_store_detail_sync(stock_id: str) -> dict[str, Any]:
    data = fetch_stock_detail_sync(stock_id)
    store_detail_sync(stock_id, data)
    return data


def hydrate_detail_quote_sync(stock_id: str, data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    if not isinstance(result.get("research"), dict):
        result["research"] = build_stock_research_snapshot(
            result.get("stock") if isinstance(result.get("stock"), dict) else {},
            result.get("sections") if isinstance(result.get("sections"), dict) else {},
            generated_at=result.get("generatedAt") or datetime.now(UTC).isoformat(),
        )
    stocks = load_watchlist_config()
    stock = next((item for item in stocks if item["id"] == stock_id), None)
    if not stock:
        return result

    try:
        quote = fetch_quotes_sync([stock]).get(stock_id) or {}
    except Exception as error:
        errors = list(result.get("errors") or [])
        errors.append(f"缓存详情行情补取暂未完成：{error}")
        result["errors"] = errors
        return result

    if not quote_has_market_data(quote):
        return result

    result["stock"] = {
        **stock_public_fields(stock),
        **(result.get("stock") or {}),
        **quote,
    }
    result["research"] = build_stock_research_snapshot(
        result["stock"],
        result.get("sections") if isinstance(result.get("sections"), dict) else {},
        generated_at=datetime.now(UTC).isoformat(),
    )
    return result


def quote_has_market_data(quote: dict[str, Any]) -> bool:
    return any(quote.get(key) not in (None, "") for key in ("price", "amount", "marketCap"))


def safe_section(fetcher: Any, errors: list[str], label: str) -> dict[str, Any]:
    try:
        return fetcher()
    except Exception as error:
        message = f"{label}暂未取到：{error}"
        errors.append(message)
        return {"source": "", "items": [], "error": message}


def load_watchlist_config() -> list[dict[str, Any]]:
    payload = json.loads(WATCHLIST_CONFIG_PATH.read_text(encoding="utf-8"))
    stocks = payload.get("stocks") if isinstance(payload, dict) else []
    result = []
    for raw in stocks or []:
        if not raw.get("id") or not raw.get("symbol"):
            continue
        stock = dict(raw)
        stock["market"] = normalize_market(stock.get("market"))
        stock["secid"] = stock.get("secid") or infer_eastmoney_secid(stock)
        stock["name"] = stock.get("name") or stock["symbol"]
        stock["gubaCode"] = normalize_guba_code(stock.get("gubaCode"), stock)
        stock["xueqiuSymbol"] = stock.get("xueqiuSymbol") or infer_xueqiu_symbol(stock)
        result.append(stock)
    return result


def save_watchlist_config(stocks: list[dict[str, Any]]) -> None:
    WATCHLIST_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for raw in stocks:
        stock = dict(raw)
        stock["market"] = normalize_market(stock.get("market"))
        stock["secid"] = stock.get("secid") or infer_eastmoney_secid(stock)
        stock["gubaCode"] = normalize_guba_code(stock.get("gubaCode"), stock)
        stock["xueqiuSymbol"] = stock.get("xueqiuSymbol") or infer_xueqiu_symbol(stock)
        normalized.append(stock)
    WATCHLIST_CONFIG_PATH.write_text(json.dumps({"stocks": normalized}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_watchlist_config_changed()


def stock_id_exists(stock_id: str) -> bool:
    return any(item.get("id") == stock_id for item in load_watchlist_config())


def invalidate_watchlist_cache(stock_id: str = "", keep_detail_memory: bool = False) -> None:
    WATCHLIST_CACHE["data"] = None
    WATCHLIST_CACHE["expires_at"] = 0.0
    if stock_id and not keep_detail_memory:
        DETAIL_CACHE.pop(stock_id, None)


def mark_watchlist_config_changed() -> None:
    WATCHLIST_STATE["version"] += 1
    WATCHLIST_CACHE["data"] = None
    WATCHLIST_CACHE["expires_at"] = 0.0
    WATCHLIST_CACHE["version"] = WATCHLIST_STATE["version"]


def load_detail_store() -> dict[str, Any]:
    if not WATCHLIST_DETAIL_CACHE_PATH.exists():
        return {"schemaVersion": 1, "details": {}}
    try:
        payload = json.loads(WATCHLIST_DETAIL_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schemaVersion": 1, "details": {}}
    details = payload.get("details") if isinstance(payload, dict) else {}
    return {"schemaVersion": 1, "details": details if isinstance(details, dict) else {}}


def save_detail_store(store: dict[str, Any]) -> None:
    WATCHLIST_DETAIL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_DETAIL_CACHE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_cached_detail_sync(stock_id: str, fresh_only: bool = False) -> dict[str, Any] | None:
    store = load_detail_store()
    entry = (store.get("details") or {}).get(stock_id)
    if not isinstance(entry, dict):
        return None
    if entry.get("cacheVersion") != DETAIL_CACHE_VERSION:
        return None
    cached_at = safe_float(entry.get("cachedAt"))
    data = entry.get("data")
    if not isinstance(data, dict) or not cached_at:
        return None
    age = max(0, time.time() - cached_at)
    stale = age > DETAIL_CACHE_SECONDS
    if fresh_only and stale:
        return None
    result = json.loads(json.dumps(data, ensure_ascii=False))
    if not isinstance(result.get("research"), dict):
        result["research"] = build_stock_research_snapshot(
            result.get("stock") if isinstance(result.get("stock"), dict) else {},
            result.get("sections") if isinstance(result.get("sections"), dict) else {},
            generated_at=result.get("generatedAt") or datetime.fromtimestamp(cached_at, UTC).isoformat(),
        )
    result["cached"] = True
    result["stale"] = stale
    result["cacheUpdatedAt"] = datetime.fromtimestamp(cached_at, UTC).isoformat()
    result["cacheAgeSeconds"] = round(age)
    return result


def store_detail_sync(stock_id: str, data: dict[str, Any]) -> None:
    with DETAIL_STORE_LOCK:
        store = load_detail_store()
        details = store.setdefault("details", {})
        clean_data = json.loads(json.dumps({**data, "cached": False, "stale": False}, ensure_ascii=False))
        details[stock_id] = {"cachedAt": time.time(), "cacheVersion": DETAIL_CACHE_VERSION, "data": clean_data}
        save_detail_store(store)


def remove_cached_detail(stock_id: str) -> None:
    with DETAIL_STORE_LOCK:
        store = load_detail_store()
        details = store.get("details") or {}
        if stock_id in details:
            details.pop(stock_id, None)
            store["details"] = details
            save_detail_store(store)
    DETAIL_CACHE.pop(stock_id, None)


def update_cached_detail_stock_name(stock_id: str, name: str) -> None:
    with DETAIL_STORE_LOCK:
        store = load_detail_store()
        entry = (store.get("details") or {}).get(stock_id)
        data = entry.get("data") if isinstance(entry, dict) else None
        if isinstance(data, dict) and isinstance(data.get("stock"), dict):
            data["stock"]["name"] = name
            save_detail_store(store)
    cached = DETAIL_CACHE.get(stock_id)
    if cached and isinstance(cached.get("data"), dict):
        cached["data"].setdefault("stock", {})["name"] = name


def detail_cache_meta(stock_id: str) -> dict[str, Any]:
    cached = read_cached_detail_sync(stock_id)
    if not cached:
        return {"detailCached": False, "detailStale": True, "detailCacheUpdatedAt": ""}
    return {
        "detailCached": True,
        "detailStale": bool(cached.get("stale")),
        "detailCacheUpdatedAt": cached.get("cacheUpdatedAt") or "",
    }


def find_watchlist_match(stocks: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_market = normalize_market(candidate.get("market"))
    candidate_symbol = str(candidate.get("symbol") or "").upper()
    candidate_secid = candidate.get("secid")
    for stock in stocks:
        if stock.get("id") == candidate.get("id"):
            return stock
        if candidate_secid and stock.get("secid") == candidate_secid:
            return stock
        if normalize_market(stock.get("market")) == candidate_market and str(stock.get("symbol") or "").upper() == candidate_symbol:
            return stock
    return None


def resolve_import_stock(query: str, market: str = "", name: str = "") -> dict[str, Any]:
    raw = normalize_text(query)
    if not raw:
        raise ValueError("请输入股票代码。")

    market_hint = normalize_import_market(market)
    compact = re.sub(r"\s+", "", raw).upper()
    symbol = ""
    resolved_market = market_hint

    match = re.search(r"(?:HK|HKG)[:.\-]?(\d{4,5})", compact) or re.search(r"(\d{4,5})(?:\.HK|HK)$", compact)
    if match:
        resolved_market = "hk"
        symbol = match.group(1).zfill(5)

    if not symbol:
        match = re.search(r"(?:SH|SSE)[:.\-]?(\d{6})", compact) or re.search(r"(\d{6})(?:\.SH|\.SS)$", compact)
        if match:
            resolved_market = "a_share"
            symbol = match.group(1)

    if not symbol:
        match = re.search(r"(?:SZ|SZSE)[:.\-]?(\d{6})", compact) or re.search(r"(\d{6})(?:\.SZ)$", compact)
        if match:
            resolved_market = "a_share"
            symbol = match.group(1)

    if not symbol:
        match = re.search(r"\b(\d{6})\b", raw)
        if match:
            resolved_market = resolved_market or "a_share"
            symbol = match.group(1)

    if not symbol:
        match = re.search(r"\b(\d{4,5})\b", raw)
        if match:
            resolved_market = resolved_market or "hk"
            symbol = match.group(1).zfill(5) if resolved_market == "hk" else match.group(1)

    if not symbol:
        match = re.fullmatch(r"(?:US[:.\-]?)?([A-Z][A-Z0-9.]{0,9})", compact)
        if match:
            resolved_market = "us"
            symbol = match.group(1)

    if not symbol:
        raise ValueError("没有识别到股票代码，支持 HK01104、01104.HK、603173、SH603173、MOMO 这类格式。")

    resolved_market = normalize_market(resolved_market or "a_share")
    if resolved_market == "hk":
        symbol = symbol.zfill(5)
        stock_id = f"hk-{symbol}"
    elif resolved_market == "us":
        symbol = symbol.upper()
        stock_id = f"us-{symbol.lower().replace('.', '-')}"
    else:
        if not re.fullmatch(r"\d{6}", symbol):
            raise ValueError("A股代码需要是 6 位数字。")
        prefix = "sh" if symbol.startswith("6") else "sz"
        stock_id = f"{prefix}-{symbol}"

    stock = {
        "id": stock_id,
        "market": resolved_market,
        "symbol": symbol,
        "name": normalize_text(name) or symbol,
    }
    stock["secid"] = infer_eastmoney_secid(stock)
    stock["gubaCode"] = infer_guba_code(stock)
    stock["xueqiuSymbol"] = infer_xueqiu_symbol(stock)
    return stock


def normalize_import_market(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("hk", "h", "hongkong", "港股"):
        return "hk"
    if text in ("us", "u", "usa", "america", "美股"):
        return "us"
    if text in ("a", "ashare", "a_share", "cn", "china", "沪深", "a股"):
        return "a_share"
    return ""


def normalize_market(value: Any) -> str:
    market = str(value or "").lower()
    if market in ("hk", "hongkong", "港股"):
        return "hk"
    if market in ("us", "america", "美股"):
        return "us"
    return "a_share"


def infer_eastmoney_secid(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").upper()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        return f"116.{symbol.zfill(5)}"
    if market == "us":
        return f"105.{symbol}"
    return f"{'1' if symbol.startswith('6') else '0'}.{symbol}"


def infer_guba_code(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").upper()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        return f"HK{symbol.zfill(5)}"
    if market == "us":
        return f"US{symbol}"
    return symbol


def normalize_guba_code(value: Any, stock: dict[str, Any]) -> str:
    code = normalize_text(value).upper()
    symbol = normalize_text(stock.get("symbol")).upper()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        bare = re.sub(r"^HK", "", code or symbol)
        return f"HK{bare.zfill(5)}" if bare else code
    if market == "us":
        bare = re.sub(r"^US", "", code or symbol)
        return f"US{bare}" if bare else code
    return code or infer_guba_code(stock)


def infer_xueqiu_symbol(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").upper()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        return f"HK{symbol.zfill(5)}"
    if market == "us":
        return symbol
    return f"{'SH' if symbol.startswith('6') else 'SZ'}{symbol}"


def stock_public_fields(stock: dict[str, Any]) -> dict[str, Any]:
    market = normalize_market(stock.get("market"))
    market_label = {"a_share": "A股", "hk": "港股", "us": "美股"}.get(market, market)
    return {
        "id": stock["id"],
        "market": market,
        "marketLabel": market_label,
        "symbol": str(stock.get("symbol") or ""),
        "name": stock.get("name") or stock.get("symbol") or "",
        "secid": stock.get("secid") or "",
        "quoteUrl": stock.get("quoteUrl") or default_quote_url(stock),
    }


def default_quote_url(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").upper()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        return f"https://quote.eastmoney.com/hk/{symbol.zfill(5)}.html"
    if market == "us":
        return f"https://quote.eastmoney.com/us/{symbol}.html"
    prefix = "sh" if symbol.startswith("6") else "sz"
    return f"https://quote.eastmoney.com/{prefix}{symbol}.html"


def fetch_quotes_sync(stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tencent_map: dict[str, dict[str, Any]] = {}
    secids = [stock.get("secid") for stock in stocks if stock.get("secid")]
    if not secids:
        return fetch_tencent_quotes_sync(stocks)
    try:
        response = request_get(
            EASTMONEY_QUOTE_API,
            params={
                "fltt": "2",
                "secids": ",".join(secids),
                "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f20,f21,f9,f10,f23,f100,f124,f152",
            },
            referer="https://quote.eastmoney.com/",
        )
        rows = (response.get("data") or {}).get("diff") or []
    except Exception:
        return fetch_tencent_quotes_sync(stocks)

    try:
        tencent_map = fetch_tencent_quotes_sync(stocks)
    except Exception:
        tencent_map = {}

    secid_to_stock = {stock["secid"]: stock for stock in stocks}
    code_to_stock = {str(stock.get("symbol") or "").upper(): stock for stock in stocks}
    result = {}
    for row in rows:
        secid = f"{row.get('f13')}.{row.get('f12')}"
        stock = secid_to_stock.get(secid) or code_to_stock.get(str(row.get("f12") or "").upper())
        if not stock:
            continue
        quote = parse_quote_row(row, stock)
        fallback = tencent_map.get(stock["id"]) or {}
        field_sources = quote.get("fieldSources") if isinstance(quote.get("fieldSources"), dict) else {}
        fallback_sources = fallback.get("fieldSources") if isinstance(fallback.get("fieldSources"), dict) else {}
        for key, value in fallback.items():
            if key == "fieldSources":
                continue
            if quote.get(key) in (None, "") and value not in (None, ""):
                quote[key] = value
                if isinstance(fallback_sources.get(key), dict):
                    field_sources[key] = fallback_sources[key]
        quote["fieldSources"] = field_sources
        result[stock["id"]] = quote
    for stock_id, quote in tencent_map.items():
        result.setdefault(stock_id, quote)
    return result


def parse_quote_row(row: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    timestamp = safe_float(row.get("f124"))
    updated_at = datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else ""
    source_url = default_quote_url(stock)
    return {
        "price": safe_float(row.get("f2")),
        "changePct": safe_float(row.get("f3")),
        "change": safe_float(row.get("f4")),
        "volume": safe_float(row.get("f5")),
        "amount": safe_float(row.get("f6")),
        "marketCap": safe_float(row.get("f20")),
        "floatMarketCap": safe_float(row.get("f21")),
        "pe": safe_float(row.get("f9")),
        "pb": safe_float(row.get("f23")),
        "turnoverRate": safe_float(row.get("f10")),
        "industry": normalize_text(row.get("f100")),
        "quoteName": normalize_text(row.get("f14")),
        "updatedAt": updated_at,
        "source": "东方财富行情",
        "sourceUrl": source_url,
        "quoteUrl": source_url,
        "fieldSources": build_quote_field_sources("东方财富行情", source_url),
    }


def empty_quote(stock: dict[str, Any]) -> dict[str, Any]:
    source_url = default_quote_url(stock)
    return {
        "price": None,
        "changePct": None,
        "change": None,
        "volume": None,
        "amount": None,
        "marketCap": None,
        "floatMarketCap": None,
        "pe": None,
        "pb": None,
        "turnoverRate": None,
        "industry": "",
        "quoteName": "",
        "updatedAt": "",
        "source": "东方财富行情",
        "sourceUrl": source_url,
        "quoteUrl": source_url,
        "fieldSources": build_quote_field_sources("东方财富行情", source_url),
    }


def fetch_tencent_quotes_sync(stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    symbols = [infer_tencent_symbol(stock) for stock in stocks]
    response = coordinated_requests_request(
        requests,
        "GET",
        f"{TENCENT_QUOTE_API}{','.join(symbols)}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        timeout=12,
    )
    response.raise_for_status()
    response.encoding = "gbk"
    stock_by_tencent = {infer_tencent_symbol(stock).lower(): stock for stock in stocks}
    result = {}
    for match in re.finditer(r'v_([^=]+)="([^"]*)";', response.text):
        key = match.group(1).lower()
        stock = stock_by_tencent.get(key)
        if not stock:
            continue
        quote = parse_tencent_quote(match.group(2), stock)
        if quote:
            result[stock["id"]] = quote
    return result


def infer_tencent_symbol(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").lower()
    market = normalize_market(stock.get("market"))
    if market == "hk":
        return f"hk{symbol.zfill(5)}"
    if market == "us":
        return f"us{symbol.upper()}"
    return f"{'sh' if symbol.startswith('6') else 'sz'}{symbol}"


def parse_tencent_quote(raw: str, stock: dict[str, Any]) -> dict[str, Any] | None:
    parts = raw.split("~")
    if len(parts) < 40:
        return None
    market = normalize_market(stock.get("market"))
    amount = safe_float_at(parts, 37)
    volume = safe_float_at(parts, 36) or safe_float_at(parts, 6)
    if market == "a_share" and len(parts) > 35 and "/" in parts[35]:
        trade_parts = parts[35].split("/")
        if len(trade_parts) >= 3:
            amount = safe_float(trade_parts[2])
    market_cap_index = 45
    float_market_cap_index = 44
    pb_index = 46 if market == "a_share" else 58 if market == "hk" else None
    turnover_index = 38 if market in ("a_share", "us") else 52
    updated_at = parse_tencent_quote_time(parts[30] if len(parts) > 30 else "", market)
    source_url = f"{TENCENT_QUOTE_API}{infer_tencent_symbol(stock)}"
    field_sources = build_quote_field_sources("腾讯行情", source_url)
    for field in ("marketCap", "floatMarketCap"):
        field_sources[field] = {
            **field_sources[field],
            "method": "derived",
            "formula": "腾讯行情市值字段 × 100,000,000（按市场报价币种）",
        }
    return {
        "price": safe_float_at(parts, 3),
        "changePct": safe_float_at(parts, 32),
        "change": safe_float_at(parts, 31),
        "volume": volume,
        "amount": amount,
        "marketCap": multiply_or_none(safe_float_at(parts, market_cap_index), 100_000_000),
        "floatMarketCap": multiply_or_none(safe_float_at(parts, float_market_cap_index), 100_000_000),
        "pe": safe_float_at(parts, 39),
        "pb": safe_float_at(parts, pb_index) if pb_index is not None else None,
        "turnoverRate": safe_float_at(parts, turnover_index),
        "industry": "",
        "quoteName": normalize_text(parts[1] if len(parts) > 1 else ""),
        "updatedAt": updated_at,
        "source": "腾讯行情",
        "sourceUrl": source_url,
        "quoteUrl": default_quote_url(stock),
        "fieldSources": field_sources,
    }


def build_quote_field_sources(source: str, source_url: str) -> dict[str, dict[str, str]]:
    return {
        field: {"source": source, "sourceUrl": source_url, "method": "observed"}
        for field in QUOTE_PROVENANCE_FIELDS
    }


def safe_float_at(values: list[str], index: int) -> float | None:
    return safe_float(values[index]) if 0 <= index < len(values) else None


def multiply_or_none(value: float | None, multiplier: float) -> float | None:
    return value * multiplier if value is not None else None


def parse_tencent_quote_time(value: str, market: str = "a_share") -> str:
    text = normalize_text(value)
    market_timezone = WATCHLIST_MARKET_TIMEZONES.get(normalize_market(market), WATCHLIST_MARKET_TIMEZONES["a_share"])
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            local_time = datetime.strptime(text, pattern).replace(tzinfo=market_timezone)
            return local_time.astimezone(UTC).isoformat()
        except ValueError:
            continue
    return ""


def fetch_short_interest_sync(stock: dict[str, Any]) -> dict[str, Any]:
    market = normalize_market(stock.get("market"))
    items: list[dict[str, Any]] = []
    source_names: list[str] = []
    source_errors: list[str] = []

    if market == "a_share":
        try:
            rows = fetch_datacenter_rows(
                "RPTA_RZRQ_LSHJ",
                f'(SECURITY_CODE="{stock["symbol"]}")',
                page_size=8,
                sort_columns="DIM_DATE",
            )
            items.extend(
                {
                    "date": date_only(row.get("DIM_DATE")),
                    "shortBalance": safe_float(row.get("RQYE")),
                    "financingBalance": safe_float(row.get("RZYE")),
                    "financingBuy": safe_float(row.get("RZMRE")),
                    "source": "东方财富融资融券",
                }
                for row in rows
                if date_only(row.get("DIM_DATE"))
            )
            source_names.append("东方财富融资融券")
        except Exception as error:
            source_errors.append(f"东方财富融资融券：{error}")

    if market == "hk":
        try:
            rows = fetch_aastocks_short_selling_sync(stock)
            items.extend(rows)
            if rows:
                source_names.append("AAStocks短卖")
        except Exception as error:
            source_errors.append(f"AAStocks短卖：{error}")
        try:
            rows = fetch_aastocks_short_positions_sync(stock)
            items.extend(rows)
            if rows:
                source_names.append("AAStocks/HKEX权益披露短仓")
        except Exception as error:
            source_errors.append(f"AAStocks权益披露短仓：{error}")

    note = ""
    if market == "us" and not items:
        note = "美股逐股做空/机构持仓需要 FINRA/Nasdaq/SEC 13F 等口径；当前未配置可稳定匿名抓取的逐股短仓接口。"
    result: dict[str, Any] = {"source": " / ".join(dict.fromkeys(source_names)), "items": items[:15], "note": note}
    if source_errors and not items:
        result["errors"] = source_errors
    return result


def fetch_shareholders_sync(stock: dict[str, Any]) -> dict[str, Any]:
    market = normalize_market(stock.get("market"))
    rows: list[dict[str, Any]] = []
    source_names: list[str] = []
    for report_name in ("RPT_F10_EH_TOP10HOLDERS", "RPT_F10_EH_FREEHOLDERS"):
        try:
            rows = fetch_datacenter_rows(
                report_name,
                f'(SECURITY_CODE="{stock["symbol"]}")',
                page_size=10,
                sort_columns="END_DATE",
            )
        except Exception:
            rows = []
        if rows:
            source_names.append("东方财富F10股东")
            break

    items = []
    for row in rows[:10]:
        items.append(
            {
                "name": first_value(row, "HOLDER_NAME", "SHAREHOLDER_NAME", "HOLDER"),
                "shares": safe_float(first_value(row, "HOLD_NUM", "HOLDER_NUM", "SHARES")),
                "ratio": safe_float(first_value(row, "HOLD_RATIO", "HOLDER_RATIO", "FREE_HOLD_RATIO")),
                "change": first_value(row, "HOLD_NUM_CHANGE", "CHANGE", "HOLD_RATIO_CHANGE"),
                "date": date_only(first_value(row, "END_DATE", "REPORT_DATE")),
                "source": "东方财富F10股东",
            }
        )

    if market == "hk":
        try:
            hk_items = [
                {
                    "name": row.get("name"),
                    "shares": row.get("shares"),
                    "ratio": row.get("ratio"),
                    "change": row.get("eventCode"),
                    "date": row.get("date"),
                    "source": "AAStocks/HKEX权益披露",
                }
                for row in fetch_aastocks_disclosures_sync(stock)
                if row.get("positionType") == "L"
            ]
            if hk_items:
                items.extend(hk_items)
                source_names.append("AAStocks/HKEX权益披露")
        except Exception:
            pass

    return {"source": " / ".join(dict.fromkeys(source_names)) or "公开股东数据", "items": dedupe_holder_items(items)[:10]}


def fetch_shareholder_distribution_sync(stock: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for report_name in ("RPT_F10_EH_HOLDERNUM", "RPT_HOLDERNUM_DET", "RPT_HOLDERNUMLATEST"):
        try:
            rows = fetch_datacenter_rows(
                report_name,
                f'(SECURITY_CODE="{stock["symbol"]}")',
                page_size=8,
                sort_columns="END_DATE",
            )
        except Exception:
            rows = []
        if rows:
            break

    items = []
    for row in rows[:8]:
        items.append(
            {
                "date": date_only(first_value(row, "END_DATE", "REPORT_DATE", "HOLDER_END_DATE")),
                "holderCount": safe_float(first_value(row, "HOLDER_TOTAL_NUM", "HOLDER_NUM", "TOTAL_HOLDER_NUM")),
                "avgHolding": safe_float(first_value(row, "AVG_HOLD_NUM", "AVG_FREE_SHARES", "AVG_HOLDER_NUM")),
                "avgMarketValue": safe_float(first_value(row, "AVG_MARKET_CAP", "AVG_HOLD_MARKET_CAP")),
                "changePct": safe_float(first_value(row, "HOLDER_NUM_RATIO", "HOLDER_CHANGE_RATIO", "CHANGE_RATE")),
            }
        )
    return {"source": "东方财富F10股东户数", "items": [item for item in items if item.get("date")]}


def fetch_fund_holdings_sync(stock: dict[str, Any]) -> dict[str, Any]:
    market = normalize_market(stock.get("market"))
    rows: list[dict[str, Any]] = []
    source_names: list[str] = []
    for report_name, sort_column in (
        ("RPT_F10_EH_FUNDHOLDERS", "END_DATE"),
        ("RPT_FUND_HOLDING_STOCK", "REPORT_DATE"),
        ("RPT_MUTUAL_FUND_HOLDSTOCK", "REPORT_DATE"),
        ("RPT_MAIN_POSITIONDETAILS", "REPORT_DATE"),
    ):
        try:
            rows = fetch_datacenter_rows(
                report_name,
                f'(SECURITY_CODE="{stock["symbol"]}")',
                page_size=30,
                sort_columns=sort_column,
            )
        except Exception:
            rows = []
        if rows:
            source_names.append("东方财富基金持仓")
            break

    items = parse_fund_holding_rows(rows)
    if not items:
        shareholders = fetch_shareholders_sync(stock).get("items") or []
        items = [
            {
                "name": item.get("name"),
                "ratio": item.get("ratio"),
                "shares": item.get("shares"),
                "date": item.get("date"),
                "source": "主要股东中的基金/资管持有人",
            }
            for item in shareholders
            if looks_like_fund_holder(item.get("name"))
        ]
        if items:
            source_names.append("主要股东中的基金/资管持有人")

    if market == "hk" and not items:
        try:
            institutional_items = [
                {
                    "name": item.get("name"),
                    "ratio": item.get("ratio"),
                    "shares": item.get("shares"),
                    "date": item.get("date"),
                    "source": "AAStocks/HKEX权益披露机构持有人",
                }
                for item in fetch_aastocks_disclosures_sync(stock)
                if item.get("positionType") == "L" and looks_like_institution_holder(item.get("name"))
            ]
            if institutional_items:
                items = institutional_items
                source_names.append("AAStocks/HKEX权益披露机构持有人")
        except Exception:
            pass

    items = sorted(
        [item for item in items if item.get("name")],
        key=lambda item: (safe_float(item.get("ratio")) or 0, safe_float(item.get("marketValue")) or 0, safe_float(item.get("shares")) or 0),
        reverse=True,
    )
    return {"source": " / ".join(dict.fromkeys(source_names)) or "公开基金/机构持仓", "items": dedupe_holder_items(items)[:5]}


def parse_fund_holding_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for row in rows:
        items.append(
            {
                "name": normalize_text(first_value(row, "FUND_NAME", "FUND_NAME_ABBR", "FUNDSNAME", "HOLDER_NAME", "SECURITY_NAME_ABBR", "SNAME")),
                "ratio": safe_float(first_value(row, "HOLD_RATIO", "STOCK_PER", "TOTAL_SHARES_RATIO", "PCT_NV", "HOLD_MARKET_CAP_RATIO")),
                "shares": safe_float(first_value(row, "HOLD_NUM", "HOLDING_NUM", "HOLD_STOCK_NUM", "NUM")),
                "marketValue": safe_float(first_value(row, "HOLD_MARKET_CAP", "MARKET_CAP", "HOLD_VALUE", "STOCK_VALUE")),
                "date": date_only(first_value(row, "END_DATE", "REPORT_DATE", "REPORTDATE")),
                "source": "东方财富基金持仓",
            }
        )
    return items


def fetch_aastocks_short_selling_sync(stock: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(stock.get("symbol") or "").zfill(5)
    text = request_text(
        f"{AASTOCKS_SHORT_SELLING_URL}?{urlencode({'symbol': symbol})}",
        referer="https://www.aastocks.com/",
        encoding="utf-8",
    )
    rows = []
    for raw_row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = html_cells(raw_row)
        if len(cells) < 9 or not re.fullmatch(r"\d{2}/\d{2}", cells[0]):
            continue
        rows.append(
            {
                "date": cells[0],
                "price": safe_float(cells[1]),
                "change": safe_float(cells[2]),
                "changePct": safe_float(cells[3]),
                "shortVolume": parse_abbrev_number(cells[4]),
                "shortTurnover": parse_abbrev_number(cells[5]),
                "turnover": parse_abbrev_number(cells[6]),
                "shortMarketPct": safe_float(cells[7]),
                "shortRatio": safe_float(cells[8]),
                "source": "AAStocks短卖",
            }
        )
    return rows


def fetch_aastocks_short_positions_sync(stock: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "date": row.get("date"),
            "holder": row.get("name"),
            "shortBalance": row.get("shares"),
            "shortRatio": row.get("ratio"),
            "eventCode": row.get("eventCode"),
            "source": "AAStocks/HKEX权益披露短仓",
        }
        for row in fetch_aastocks_disclosures_sync(stock)
        if row.get("positionType") == "S"
    ][:5]


def fetch_aastocks_disclosures_sync(stock: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(stock.get("symbol") or "").zfill(5)
    text = request_text(
        f"{AASTOCKS_INTEREST_DISCLOSURE_URL}?{urlencode({'symbol': symbol})}",
        referer="https://www.aastocks.com/",
        encoding="utf-8",
    )
    items = []
    for raw_row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = html_cells(raw_row)
        if len(cells) < 8 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", cells[0]):
            continue
        position_type = parse_position_type(cells[3]) or parse_position_type(cells[6]) or parse_position_type(cells[7])
        items.append(
            {
                "date": cells[0],
                "name": cells[1],
                "eventCode": cells[3],
                "changedShares": parse_position_number(cells[4]),
                "shares": parse_position_number(cells[6]),
                "ratio": parse_position_number(cells[7]),
                "positionType": position_type,
                "source": "AAStocks/HKEX权益披露",
                "url": f"{AASTOCKS_INTEREST_DISCLOSURE_URL}?symbol={symbol}",
            }
        )
    return [item for item in items if item.get("name")]


def html_cells(raw_row: str) -> list[str]:
    cells = []
    for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw_row, re.S | re.I):
        value = re.sub(r"<[^>]+>", " ", cell)
        value = html.unescape(value).replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value).strip()
        cells.append(value)
    return cells


def parse_abbrev_number(value: Any) -> float | None:
    text = normalize_text(value).replace(",", "")
    if not text or text.upper() == "N/A":
        return None
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([KMB]?)", text, re.I)
    if not match:
        return safe_float(text)
    number = safe_float(match.group(1))
    if number is None:
        return None
    suffix = match.group(2).upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return number * multiplier


def parse_position_type(value: Any) -> str:
    text = normalize_text(value)
    match = re.search(r"\(([LSP])\)", text)
    return match.group(1) if match else ""


def parse_position_number(value: Any) -> float | None:
    text = normalize_text(value)
    if not text or text.upper() == "N/A":
        return None
    text = re.sub(r"\([LSP]\)", "", text)
    return safe_float(text.replace(",", ""))


def looks_like_fund_holder(value: Any) -> bool:
    name = normalize_text(value)
    if not name:
        return False
    return bool(re.search(r"基金|ETF|LOF|资管|资产管理|Vanguard|BlackRock|State Street|Fund|Trust|Asset", name, re.IGNORECASE))


def looks_like_institution_holder(value: Any) -> bool:
    name = normalize_text(value)
    if not name:
        return False
    return bool(re.search(r"基金|ETF|LOF|资管|资产管理|Vanguard|BlackRock|State Street|Fund|Trust|Asset|Capital|Management|Limited|Ltd|Holdings|Group|Partners|LP|LLC|Inc", name, re.IGNORECASE))


def dedupe_holder_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        name = normalize_text(item.get("name"))
        if not name:
            continue
        key = name.lower()
        existing = best.get(key)
        current_score = (item.get("date") or "", safe_float(item.get("ratio")) or 0, safe_float(item.get("shares")) or 0)
        existing_score = (existing.get("date") or "", safe_float(existing.get("ratio")) or 0, safe_float(existing.get("shares")) or 0) if existing else ("", 0, 0)
        if not existing or current_score > existing_score:
            best[key] = item
    return sorted(best.values(), key=lambda item: (safe_float(item.get("ratio")) or 0, safe_float(item.get("shares")) or 0), reverse=True)


def fetch_company_news_sync(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    name = normalize_text(stock.get("name"))
    symbol = normalize_text(stock.get("symbol"))
    symbol_tag = infer_xueqiu_symbol(stock)
    queries = [
        f"{name} {symbol} 股票",
        f"{name} 公司 股票",
        f"{symbol_tag} {name}",
    ]
    items: list[dict[str, Any]] = []
    source_errors: list[str] = []

    for query in queries:
        params = {
            "q": query,
            "hl": "zh-CN",
            "gl": "CN",
            "ceid": "CN:zh-Hans",
        }
        try:
            text = request_text(f"{GOOGLE_NEWS_RSS}?{urlencode(params)}", referer="https://news.google.com/")
            items.extend(parse_news_rss(text, "Google News"))
        except Exception as error:
            source_errors.append(f"Google News：{error}")

        try:
            text = request_text(
                f"{BING_NEWS_RSS}?{urlencode({'q': query, 'format': 'rss', 'setlang': 'zh-CN', 'cc': 'CN'})}",
                referer="https://www.bing.com/news",
            )
            items.extend(parse_news_rss(text, "Bing News"))
        except Exception as error:
            source_errors.append(f"Bing News：{error}")

    if not items and source_errors:
        raise RuntimeError("；".join(source_errors[:2]))

    source_names = ["Google News RSS", "Bing News RSS"]
    deduped = dedupe_news_items(items)
    if len(deduped) < limit:
        try:
            announcements = fetch_announcements_sync(stock, limit).get("items") or []
            items.extend(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "source": item.get("source") or "东方财富公告",
                    "publishedAt": item.get("publishedAt"),
                }
                for item in announcements
            )
            source_names.append("东方财富公告")
            deduped = dedupe_news_items(items)
        except Exception as error:
            source_errors.append(f"东方财富公告：{error}")

    result: dict[str, Any] = {"source": " / ".join(source_names), "items": deduped[:limit]}
    if source_errors and len(result["items"]) < limit:
        result["errors"] = list(dict.fromkeys(source_errors))[:4]
    return result


def parse_news_rss(xml_text: str, fallback_source: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        title = node_text(item, "title")
        url = node_text(item, "link")
        published = parse_rss_date(node_text(item, "pubDate"))
        source_node = item.find("source")
        source = source_node.text if source_node is not None and source_node.text else fallback_source
        items.append(
            {
                "title": strip_news_source_suffix(title, source),
                "url": url,
                "source": source,
                "publishedAt": published,
            }
        )
    return items


def dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_title: dict[str, dict[str, Any]] = {}
    for item in items:
        key = normalize_news_title(item.get("title"))
        if not key:
            continue
        existing = latest_by_title.get(key)
        if not existing or (item.get("publishedAt") or "") > (existing.get("publishedAt") or ""):
            latest_by_title[key] = item
    return sorted(latest_by_title.values(), key=lambda item: item.get("publishedAt") or "", reverse=True)


def normalize_news_title(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[|｜_\-—–:：·•,，.。!！?？（）()【】\\[\\]《》<>\"']", "", text)


def strip_news_source_suffix(title: str, source: str) -> str:
    cleaned = normalize_text(title)
    source = normalize_text(source)
    if source and cleaned.endswith(f" - {source}"):
        return cleaned[: -(len(source) + 3)].strip()
    return cleaned


def fetch_social_posts_sync(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    source_errors: list[str] = []
    sources: list[str] = []
    try:
        fetched = fetch_eastmoney_guba_posts_sync(stock, limit)
        if fetched:
            items.extend(fetched)
            sources.append("东方财富股吧")
        if len(items) >= limit:
            return build_social_posts_result(items, sources, source_errors, limit)
    except Exception as error:
        source_errors.append(f"东方财富股吧暂不可用：{normalize_remote_error(error)}")
    try:
        fetched = fetch_xueqiu_posts_sync(stock, limit)
        if fetched:
            items.extend(fetched)
            sources.append("雪球")
    except Exception as error:
        source_errors.append(f"雪球暂不可用：{normalize_remote_error(error)}")

    return build_social_posts_result(items, sources, source_errors, limit)


def build_social_posts_result(items: list[dict[str, Any]], sources: list[str], source_errors: list[str], limit: int) -> dict[str, Any]:
    items = sorted(items, key=lambda item: (safe_float(item.get("heat")) or 0, item.get("publishedAt") or ""), reverse=True)
    result: dict[str, Any] = {"source": " / ".join(sources or ["东方财富股吧", "雪球"]), "items": items[:limit]}
    if source_errors and not items:
        result["errors"] = source_errors
    return result


def fetch_eastmoney_guba_posts_sync(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    errors: list[str] = []
    try:
        data = request_get(
            EASTMONEY_GUBA_API,
            params={"code": stock.get("gubaCode"), "sorttype": "1", "page": "1", "ps": str(limit)},
            referer=f"https://guba.eastmoney.com/list,{stock.get('gubaCode')}.html",
            attempts=2,
        )
        rows = data.get("re") or []
        if rows:
            return parse_eastmoney_guba_rows(rows, stock)[:limit]
        if data.get("me"):
            errors.append(normalize_text(data.get("me")))
    except Exception as error:
        errors.append(normalize_remote_error(error))

    try:
        posts = fetch_eastmoney_guba_html_posts_sync(stock, limit)
        if posts:
            return posts[:limit]
    except Exception as error:
        errors.append(normalize_remote_error(error))

    raise RuntimeError("；".join(item for item in errors if item) or "未返回帖子")


def fetch_eastmoney_guba_html_posts_sync(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    code = normalize_text(stock.get("gubaCode"))
    if not code:
        return []
    session = create_browser_session("https://guba.eastmoney.com/")
    list_url = f"https://guba.eastmoney.com/list,{code}.html"
    text = request_text(list_url, referer="https://guba.eastmoney.com/", session=session, attempts=2)
    payload = extract_js_object(text, "article_list")
    rows = payload.get("re") or []
    return parse_eastmoney_guba_rows(rows, stock)[:limit]


def parse_eastmoney_guba_rows(rows: list[dict[str, Any]], stock: dict[str, Any]) -> list[dict[str, Any]]:
    posts = []
    for row in rows:
        post_id = first_value(row, "post_id", "postid", "id")
        posts.append(
            {
                "title": normalize_text(first_value(row, "post_title", "title")),
                "url": f"https://guba.eastmoney.com/news,{stock.get('gubaCode')},{post_id}.html" if post_id else "https://guba.eastmoney.com/",
                "author": normalize_text(first_value(row, "user_nickname", "user_name")),
                "source": "东方财富股吧",
                "publishedAt": normalize_text(first_value(row, "post_publish_time", "post_last_time")),
                "heat": safe_float(first_value(row, "post_click_count", "post_forward_count", "post_comment_count")),
                "replyCount": safe_float(first_value(row, "post_comment_count", "reply_count")),
            }
        )
    return [post for post in posts if post.get("title")]


def fetch_xueqiu_posts_sync(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    symbol = normalize_text(stock.get("xueqiuSymbol"))
    if not symbol:
        return []
    session = create_xueqiu_stock_session(symbol)
    errors: list[str] = []
    for api in XUEQIU_SEARCH_APIS:
        params = xueqiu_stock_params(api, stock, limit)
        try:
            response = session.get(api, params=params, timeout=10)
            response.raise_for_status()
            data = response_json(response)
            rows = extract_payload_rows(data)
            posts = parse_xueqiu_post_rows(rows, stock)
            if posts:
                return posts[:limit]
        except DomainCoolingDown:
            raise
        except Exception as error:
            errors.append(normalize_remote_error(error))
    raise RuntimeError("；".join(item for item in errors if item) or "未返回帖子")


def create_xueqiu_stock_session(symbol: str) -> requests.Session:
    referer = f"https://xueqiu.com/S/{symbol}"
    session = create_browser_session(referer, accept="application/json, text/plain, */*")
    session.headers.update(
        {
            "Host": "xueqiu.com",
            "Origin": "https://xueqiu.com",
            "Referer": referer,
        }
    )
    cookie = normalize_text(os.getenv("XUEQIU_COOKIE") or os.getenv("XUEQIU_COOKIES"))
    if cookie:
        session.headers["Cookie"] = cookie
    for warmup_url in ("https://xueqiu.com/", referer):
        try:
            session.get(warmup_url, timeout=8)
        except Exception:
            pass
    return session


def xueqiu_stock_params(api: str, stock: dict[str, Any], limit: int) -> dict[str, Any]:
    symbol = normalize_text(stock.get("xueqiuSymbol"))
    if api.endswith("stock_timeline.json"):
        return {"symbol_id": symbol, "count": str(limit), "source": "all", "_": str(int(time.time() * 1000))}
    params = {
        "count": str(limit),
        "comment": "0",
        "symbol": symbol,
        "hl": "0",
        "source": "all",
        "sort": "time",
        "page": "1",
        "_": str(int(time.time() * 1000)),
    }
    name = normalize_text(stock.get("name"))
    if name:
        params["q"] = name
    return params


def parse_xueqiu_post_rows(rows: list[dict[str, Any]], stock: dict[str, Any]) -> list[dict[str, Any]]:
    posts = []
    for row in rows:
        text = strip_html(first_value(row, "title", "description", "text"))
        post_id = first_value(row, "id", "target")
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        posts.append(
            {
                "title": text[:120],
                "url": f"https://xueqiu.com/{user.get('id')}/{post_id}" if post_id and user.get("id") else "https://xueqiu.com/",
                "author": normalize_text(user.get("screen_name") or first_value(row, "screen_name")),
                "source": "雪球",
                "publishedAt": parse_xueqiu_time(first_value(row, "created_at", "timeBefore")),
                "heat": safe_float(first_value(row, "reply_count", "retweet_count", "fav_count")),
            }
        )
    return [post for post in posts if post.get("title")]


def fetch_capital_flow_sync(stock: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    market = normalize_market(stock.get("market"))
    if market == "a_share":
        try:
            sina_items = fetch_sina_capital_flow_items(stock, 15)
            if sina_items:
                return {
                    "source": "新浪资金流向",
                    "sourceUrl": f"{SINA_CAPITAL_FLOW_API}?{urlencode({'daima': infer_sina_symbol(stock)})}",
                    "method": "observed",
                    "kind": "capital_flow",
                    "items": sina_items,
                }
        except Exception as error:
            errors.append(f"新浪资金流向：{normalize_remote_error(error)}")
    else:
        try:
            yahoo_result = build_yahoo_capital_flow_proxy_result(stock, 15)
            if yahoo_result.get("items"):
                return yahoo_result
        except Exception as error:
            errors.append(f"Yahoo成交额代理：{normalize_remote_error(error)}")

    params = {
        "secid": stock.get("secid"),
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        "klt": "101",
        "lmt": "15",
    }
    rows: list[Any] = []
    source_api = ""
    session = create_browser_session(default_quote_url(stock))
    for api in EASTMONEY_CAPITAL_FLOW_APIS:
        try:
            data = request_get(api, params=params, referer=default_quote_url(stock), session=session, attempts=2)
            rows = ((data.get("data") or {}).get("klines") or [])[-15:]
            if rows:
                source_api = api
                break
        except Exception as error:
            errors.append(normalize_remote_error(error))
    if not rows:
        if market == "a_share":
            try:
                yahoo_result = build_yahoo_capital_flow_proxy_result(stock, 15)
                if yahoo_result.get("items"):
                    return yahoo_result
            except Exception as error:
                errors.append(f"Yahoo成交额代理：{normalize_remote_error(error)}")
        else:
            try:
                sina_items = fetch_sina_capital_flow_items(stock, 15)
                if sina_items:
                    return {
                        "source": "新浪资金流向",
                        "sourceUrl": f"{SINA_CAPITAL_FLOW_API}?{urlencode({'daima': infer_sina_symbol(stock)})}",
                        "method": "observed",
                        "kind": "capital_flow",
                        "items": sina_items,
                    }
            except Exception as error:
                errors.append(f"新浪资金流向：{normalize_remote_error(error)}")
        raise RuntimeError("；".join(item for item in errors if item) or "资金流接口未返回数据")
    items = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 10:
            continue
        items.append(
            {
                "date": parts[0],
                "mainNetInflow": safe_float(parts[1]),
                "smallNetInflow": safe_float(parts[2]),
                "largeNetInflow": safe_float(parts[3]),
                "mainNetRatio": safe_float(parts[6]),
                "smallNetRatio": safe_float(parts[7]),
                "largeNetRatio": safe_float(parts[8]),
                "close": safe_float(parts[10]) if len(parts) > 10 else None,
                "changePct": safe_float(parts[11]) if len(parts) > 11 else None,
            }
        )
    return {
        "source": "东方财富资金流向",
        "sourceUrl": f"{source_api}?{urlencode(params)}",
        "method": "observed",
        "kind": "capital_flow",
        "items": items,
    }


def fetch_sina_capital_flow_items(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    symbol = infer_sina_symbol(stock)
    if not symbol:
        return []
    session = create_browser_session("https://finance.sina.com.cn/", accept="*/*")
    response = session.get(SINA_CAPITAL_FLOW_API, params={"daima": symbol}, timeout=12)
    response.raise_for_status()
    response.encoding = "gbk"
    payload = json.loads(response.text)
    if not isinstance(payload, list):
        return []
    items = []
    for row in payload[:limit]:
        if not isinstance(row, dict):
            continue
        main_ratio = safe_float(row.get("r0_ratio"))
        change_pct = safe_float(row.get("changeratio"))
        items.append(
            {
                "date": normalize_text(row.get("opendate")),
                "mainNetInflow": safe_float(row.get("r0_net")),
                "smallNetInflow": None,
                "largeNetInflow": None,
                "mainNetRatio": main_ratio * 100 if main_ratio is not None else None,
                "smallNetRatio": None,
                "largeNetRatio": None,
                "close": safe_float(row.get("trade")),
                "changePct": change_pct * 100 if change_pct is not None else None,
            }
        )
    return [item for item in items if item.get("date")]


def infer_sina_symbol(stock: dict[str, Any]) -> str:
    if normalize_market(stock.get("market")) != "a_share":
        return ""
    symbol = normalize_text(stock.get("symbol")).upper()
    if not symbol:
        return ""
    return f"{'sh' if symbol.startswith('6') else 'sz'}{symbol}"


def build_yahoo_capital_flow_proxy_result(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    items = fetch_yahoo_capital_flow_proxy_items(stock, limit)
    currency = normalize_text(items[0].get("currency")) if items else ""
    currency_hint = f"({currency})" if currency else ""
    encoded_symbol = quote(infer_yahoo_symbol(stock), safe="")
    return {
        "source": f"Yahoo成交额代理{currency_hint}",
        "sourceUrl": f"https://finance.yahoo.com/quote/{encoded_symbol}/history",
        "method": "proxy",
        "kind": "price_pressure_proxy",
        "formula": "成交额（收盘价×成交量）×当日涨跌幅",
        "note": "Yahoo不提供主力/大单拆分；这里是成交额价格压力代理，不是主力净流入或真实资金流。",
        "items": items,
    }


def fetch_yahoo_capital_flow_proxy_items(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    symbol = infer_yahoo_symbol(stock)
    if not symbol:
        return []
    params = {"range": "3mo", "interval": "1d", "includeAdjustedClose": "true"}
    errors: list[str] = []
    encoded_symbol = quote(symbol, safe="")
    referer = f"https://finance.yahoo.com/quote/{encoded_symbol}"
    session = create_browser_session(referer, accept="application/json, text/plain, */*")
    for api in YAHOO_CHART_APIS:
        try:
            data = request_get(
                api.format(symbol=encoded_symbol),
                params=params,
                referer=referer,
                session=session,
                attempts=2,
            )
            chart = data.get("chart") or {}
            chart_error = chart.get("error")
            if isinstance(chart_error, dict) and chart_error:
                raise RuntimeError(normalize_text(chart_error.get("description")) or normalize_text(chart_error.get("code")))
            result = first_item(chart.get("result"))
            items = parse_yahoo_capital_flow_proxy_rows(result, limit)
            if items:
                return items
            errors.append("Yahoo图表未返回可用日线")
        except Exception as error:
            errors.append(normalize_remote_error(error))
    raise RuntimeError("；".join(item for item in errors if item) or "Yahoo图表未返回可用日线")


def infer_yahoo_symbol(stock: dict[str, Any]) -> str:
    symbol = normalize_text(stock.get("symbol")).upper()
    if not symbol:
        return ""
    market = normalize_market(stock.get("market"))
    if market == "hk":
        bare = symbol.lstrip("0")
        return f"{bare.zfill(4)}.HK" if bare else ""
    if market == "us":
        return symbol.replace(".", "-")
    return f"{symbol}.SS" if symbol.startswith("6") else f"{symbol}.SZ"


def parse_yahoo_capital_flow_proxy_rows(result: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    timestamps = result.get("timestamp") or []
    quote_rows = (result.get("indicators") or {}).get("quote") or []
    quote_row = first_item(quote_rows)
    if not isinstance(quote_row, dict):
        return []
    closes = quote_row.get("close") or []
    volumes = quote_row.get("volume") or []
    currency = normalize_text((result.get("meta") or {}).get("currency"))
    items: list[dict[str, Any]] = []
    previous_close: float | None = None
    for index, timestamp in enumerate(timestamps):
        close = safe_float_at(closes, index)
        if close is None:
            continue
        volume = safe_float_at(volumes, index)
        change_pct = ((close - previous_close) / previous_close * 100) if previous_close else None
        amount = close * volume if volume is not None else None
        proxy_flow = amount * change_pct / 100 if amount is not None and change_pct is not None else None
        try:
            date = datetime.fromtimestamp(float(timestamp), UTC).date().isoformat()
        except Exception:
            date = normalize_text(timestamp)
        items.append(
            {
                "date": date,
                "mainNetInflow": None,
                "smallNetInflow": None,
                "largeNetInflow": None,
                "mainNetRatio": None,
                "smallNetRatio": None,
                "largeNetRatio": None,
                "pricePressureProxy": proxy_flow,
                "pricePressureRatio": change_pct,
                "method": "proxy",
                "formula": "成交额（收盘价×成交量）×当日涨跌幅",
                "close": close,
                "changePct": change_pct,
                "currency": currency,
            }
        )
        previous_close = close
    return items[-limit:]


def first_item(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else None


def fetch_announcements_sync(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    data = request_get(
        EASTMONEY_ANNOUNCEMENT_API,
        params={
            "sr": "-1",
            "page_size": str(limit),
            "page_index": "1",
            "ann_type": "A",
            "client_source": "web",
            "stock_list": stock.get("symbol"),
        },
        referer=default_quote_url(stock),
    )
    rows = ((data.get("data") or {}).get("list") or data.get("announcements") or [])[:limit]
    items = []
    for row in rows:
        columns = row.get("columns") if isinstance(row.get("columns"), list) else []
        art_code = first_value(row, "art_code", "code", "notice_id")
        url = first_value(row, "url")
        if not url and art_code:
            url = f"https://data.eastmoney.com/notices/detail/{stock.get('symbol')}/{art_code}.html"
        items.append(
            {
                "title": normalize_text(first_value(row, "title", "notice_title", "art_title")),
                "url": url or default_quote_url(stock),
                "publishedAt": normalize_text(first_value(row, "notice_date", "display_time", "eiTime")),
                "category": " / ".join(normalize_text(item.get("column_name")) for item in columns if isinstance(item, dict) and item.get("column_name")),
                "source": "东方财富公告",
            }
        )
    return {"source": "东方财富公告", "items": [item for item in items if item.get("title")]}


def fetch_ratings_sync(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for fetcher in (
        fetch_eastmoney_reportapi_rows,
        fetch_eastmoney_reportapi_post_rows,
        fetch_eastmoney_report_page_rows,
        fetch_eastmoney_datacenter_rating_rows,
    ):
        try:
            rows = fetcher(stock, limit)
        except Exception as error:
            errors.append(normalize_remote_error(error))
            continue
        if rows:
            break

    if not rows and len(errors) >= 3:
        raise RuntimeError("；".join(dict.fromkeys(errors)) or "研报接口未返回数据")

    return {"source": "东方财富研报", "items": parse_rating_rows(rows, limit)}


def fetch_eastmoney_reportapi_rows(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = request_get(
        EASTMONEY_REPORT_API,
        params=eastmoney_report_params(stock, limit),
        referer=EASTMONEY_REPORT_PAGE,
        attempts=2,
    )
    return data.get("data") or []


def fetch_eastmoney_reportapi_post_rows(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = request_post(
        EASTMONEY_REPORT_POST_API,
        data=eastmoney_report_params(stock, limit),
        referer=EASTMONEY_REPORT_PAGE,
        attempts=1,
    )
    return data.get("data") or []


def fetch_eastmoney_report_page_rows(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    text = request_text(EASTMONEY_REPORT_PAGE, referer="https://data.eastmoney.com/", attempts=2)
    payload = extract_js_object(text, "initdata")
    rows = payload.get("data") or []
    symbol = normalize_text(stock.get("symbol"))
    return [row for row in rows if normalize_text(row.get("stockCode")) == symbol][:limit]


def fetch_eastmoney_datacenter_rating_rows(stock: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    for report_name in ("RPT_RESEARCH_ORGRES", "RPT_RESEARCH_REPORT", "RPT_RESEARCH_REPORTNEW"):
        rows = fetch_datacenter_rows(
            report_name,
            f'(SECURITY_CODE="{stock["symbol"]}")',
            page_size=limit,
            sort_columns="NOTICE_DATE",
        )
        if rows:
            return rows
    return []


def eastmoney_report_params(stock: dict[str, Any], limit: int) -> dict[str, Any]:
    end_date = datetime.now(UTC).date()
    begin_date = end_date - timedelta(days=730)
    return {
        "beginTime": begin_date.isoformat(),
        "endTime": end_date.isoformat(),
        "industryCode": "*",
        "industry": "*",
        "ratingChange": "*",
        "rating": "*",
        "orgCode": "*",
        "code": stock.get("symbol"),
        "rcode": "",
        "pageSize": str(limit),
        "pageNo": "1",
        "fields": "",
        "qType": "0",
    }


def parse_rating_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    items = []
    for row in rows[:limit]:
        target_price_text = rating_target_price_text(row)
        target_price = safe_float(
            first_value(
                row,
                "indvAimPriceT",
                "TARGET_PRICE",
                "PREDICT_PRICE",
                "TARGET_PRICE_MAX",
                "indvAimPriceL",
                "TARGET_PRICE_MIN",
            )
        )
        items.append(
            {
                "date": date_only(first_value(row, "publishDate", "NOTICE_DATE", "PUBLISH_DATE", "REPORT_DATE")),
                "broker": normalize_text(first_value(row, "orgSName", "orgName", "ORG_NAME", "SECURITY_NAME_ABBR", "INS_NAME")),
                "analyst": parse_report_author(row),
                "rating": normalize_text(first_value(row, "emRatingName", "sRatingName", "EM_RATING_NAME", "RATING", "RATE")),
                "targetPrice": target_price,
                "targetPriceText": target_price_text,
                "title": normalize_text(first_value(row, "title", "TITLE", "REPORT_TITLE")),
                "url": report_detail_url(row),
                "source": "东方财富研报",
            }
        )
    return [item for item in items if item.get("title") or item.get("rating")]


def parse_report_author(row: dict[str, Any]) -> str:
    researcher = normalize_text(first_value(row, "researcher", "ANALYST", "ANALYST_NAME"))
    if researcher:
        return researcher
    author = row.get("author")
    if isinstance(author, list):
        names = [normalize_text(str(item).split(".", 1)[-1]) for item in author if item]
        return "、".join(item for item in names if item)
    return normalize_text(author)


def rating_target_price_text(row: dict[str, Any]) -> str:
    low = compact_number(first_value(row, "indvAimPriceL", "TARGET_PRICE_MIN", "TARGET_PRICE_LOW"))
    high = compact_number(first_value(row, "indvAimPriceT", "TARGET_PRICE_MAX", "TARGET_PRICE", "PREDICT_PRICE"))
    if low and high and low != high:
        return f"{low}-{high}"
    return high or low


def compact_number(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    return f"{number:.2f}".rstrip("0").rstrip(".")


def report_detail_url(row: dict[str, Any]) -> str:
    url = normalize_text(first_value(row, "url", "URL"))
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http"):
        return url
    info_code = normalize_text(first_value(row, "infoCode", "INFO_CODE"))
    if info_code:
        return f"https://data.eastmoney.com/report/info/{info_code}.html"
    encode_url = normalize_text(first_value(row, "encodeUrl", "ENCODE_URL"))
    if encode_url:
        return f"https://data.eastmoney.com/report/zw_stock.jshtml?encodeUrl={quote(encode_url)}"
    return EASTMONEY_REPORT_PAGE


def fetch_datacenter_rows(report_name: str, filter_text: str, page_size: int = 15, sort_columns: str = "NOTICE_DATE") -> list[dict[str, Any]]:
    data = request_get(
        EASTMONEY_DATACENTER_API,
        params={
            "reportName": report_name,
            "columns": "ALL",
            "filter": filter_text,
            "pageNumber": "1",
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
        referer="https://data.eastmoney.com/",
    )
    result = data.get("result") or {}
    return result.get("data") or []


def request_get(
    url: str,
    params: dict[str, Any] | None = None,
    referer: str = "",
    session: requests.Session | None = None,
    attempts: int = 3,
    accept: str = "application/json, text/plain, */*",
    warmup_urls: list[str] | None = None,
) -> dict[str, Any]:
    client = session or create_browser_session(referer, accept=accept)
    client.headers.update(common_headers(referer, accept=accept))
    for warmup_url in warmup_urls or []:
        try:
            client.get(warmup_url, timeout=8)
        except Exception:
            pass
    try:
        response = client.get(url, params=params, timeout=12)
        response.raise_for_status()
        return response_json(response)
    except DomainCoolingDown:
        raise
    except Exception as error:
        raise RuntimeError(normalize_remote_error(error)) from error


def request_post(
    url: str,
    data: dict[str, Any] | None = None,
    referer: str = "",
    session: requests.Session | None = None,
    attempts: int = 2,
    accept: str = "application/json, text/plain, */*",
) -> dict[str, Any]:
    client = session or create_browser_session(referer, accept=accept)
    client.headers.update(common_headers(referer, accept=accept))
    try:
        response = client.post(url, data=data, timeout=12)
        response.raise_for_status()
        return response_json(response)
    except DomainCoolingDown:
        raise
    except Exception as error:
        raise RuntimeError(normalize_remote_error(error)) from error


def request_text(
    url: str,
    referer: str = "",
    encoding: str = "utf-8",
    session: requests.Session | None = None,
    attempts: int = 3,
) -> str:
    client = session or create_browser_session(referer, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    client.headers.update(common_headers(referer, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"))
    try:
        response = client.get(url, timeout=12)
        response.raise_for_status()
        response.encoding = encoding
        return response.text
    except DomainCoolingDown:
        raise
    except Exception as error:
        raise RuntimeError(normalize_remote_error(error)) from error


def response_json(response: requests.Response) -> dict[str, Any]:
    response.encoding = "utf-8"
    text = response.text.strip()
    if not text:
        return {}
    if text.startswith("<") or "aliyun_waf" in text[:2000] or "_waf_" in text[:2000]:
        raise RuntimeError("接口返回风控或 HTML 页面")
    try:
        payload = response.json()
    except Exception as error:
        raise RuntimeError(f"接口返回内容不是 JSON：{error}") from error
    return payload if isinstance(payload, dict) else {}


def create_browser_session(referer: str = "", accept: str = "*/*") -> requests.Session:
    session = requests.Session()
    session.headers.update(common_headers(referer, accept=accept))
    return coordinate_requests_session(session)


def common_headers(referer: str = "", accept: str = "*/*") -> dict[str, str]:
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Referer": referer or "https://quote.eastmoney.com/",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    if referer:
        headers["Origin"] = re.sub(r"/+$", "", referer.split("/", 3)[0] + "//" + referer.split("/", 3)[2]) if "://" in referer else referer
    return headers


def normalize_remote_error(error: Any) -> str:
    text = normalize_text(error)
    if not text:
        return "远端接口暂不可用"
    if "RemoteDisconnected" in text or "closed connection without response" in text:
        return "远端断开连接"
    if "SSLEOFError" in text or "UNEXPECTED_EOF" in text:
        return "SSL 连接被远端提前关闭"
    if "403" in text or "Forbidden" in text:
        return "接口拒绝访问或需要登录态"
    if "400" in text or "Bad Request" in text:
        return "接口返回参数/登录态错误"
    return text[:160]


def first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_html(value: Any) -> str:
    return normalize_text(re.sub(r"<[^>]+>", "", str(value or "")))


def extract_payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [
        payload.get("list"),
        payload.get("statuses"),
        payload.get("items"),
        payload.get("data"),
        payload.get("result"),
    ]
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            rows.extend(item for item in candidate if isinstance(item, dict))
        elif isinstance(candidate, dict):
            rows.extend(extract_payload_rows(candidate))
    return rows


def extract_js_object(text: str, name: str) -> dict[str, Any]:
    assignment = re.compile(rf"(?<![\w$])(?:var\s+|let\s+|const\s+)?{re.escape(name)}\s*=")
    starts = [match.end() for match in assignment.finditer(text)]
    if not starts:
        fallback = text.find(f"var {name}")
        if fallback < 0:
            fallback = text.find(name)
        if fallback >= 0:
            starts.append(fallback + len(name))
    last_error: Exception | None = None
    for start_search in starts:
        start = text.find("{", start_search)
        if start < 0:
            continue
        raw = extract_balanced_object(text, start)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception as error:
            last_error = error
            continue
        return payload if isinstance(payload, dict) else {}
    if last_error:
        raise RuntimeError(f"页面 {name} 数据不是 JSON：{last_error}") from last_error
    raise RuntimeError(f"页面未找到 {name} 数据")


def extract_balanced_object(text: str, start: int) -> str:
    depth = 0
    in_string = False
    quote_char = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                in_string = False
            continue
        if char in ('"', "'"):
            in_string = True
            quote_char = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def date_only(value: Any) -> str:
    text = normalize_text(value)
    return text.split(" ")[0].split("T")[0] if text else ""


def node_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def parse_rss_date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except Exception:
        return ""


def parse_xueqiu_time(value: Any) -> str:
    number = safe_float(value)
    if number and number > 10_000_000_000:
        return datetime.fromtimestamp(number / 1000, UTC).isoformat()
    return normalize_text(value)
