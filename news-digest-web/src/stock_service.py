from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import random
import re
import sqlite3
import time
import zipfile
from datetime import UTC, date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import httpx
import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
DB_LOCK = asyncio.Lock()
STOCK_CACHE_LOCK = asyncio.Lock()
STOCK_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
STOCK_SCHEMA_VERSION = 11
CN_TZ = timezone(timedelta(hours=8))
try:
    US_EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    US_EASTERN_TZ = timezone(timedelta(hours=-5))
STOCK_MARKET_HISTORY_MAX_SNAPSHOTS_PER_MARKET = 1
TURNOVER_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60
FINANCING_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60
A_SHARE_TURNOVER_MONTHLY_TRADING_DAYS = 21

EASTMONEY = "https://push2.eastmoney.com"
EASTMONEY_HIS = "https://push2his.eastmoney.com"
EASTMONEY_BKZJ_URL = "https://data.eastmoney.com/bkzj/"
EASTMONEY_STOCK_STATS_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_STOCK_STATS_URL = "https://data.eastmoney.com/cjsj/gpjytj.html"
EASTMONEY_RZRQ_URL = "https://data.eastmoney.com/rzrq/"
THS_HYZJL_URL = "https://data.10jqka.com.cn/funds/hyzjl/"
THS_MARGIN_URL = "https://data.10jqka.com.cn/market/rzrq/"
TRADINGVIEW_SCAN = "https://scanner.tradingview.com"
LEGU = "https://legulegu.com"
HKEX_STOCK_CONNECT_HIGHLIGHTS_URL = (
    "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/"
    "Hong-Kong-and-Mainland-Market-Highlights?sc_lang=zh-HK"
)
HKEX_MARKET_HIGHLIGHTS_WS_URL = "https://www.hkex.com.hk/chi/csm/ws/Highlightsearch.asmx/GetData"
SSE_STOCK_STATISTIC_URL = "https://www.sse.com.cn/market/stockdata/statistic/"
SSE_STOCK_STATISTIC_API = "https://query.sse.com.cn/commonQuery.do"
SZSE_MARKET_OVERVIEW_URL = "https://www.szse.cn/market/overview/index.html"
SZSE_MARKET_OVERVIEW_API = "https://www.szse.cn/api/report/ShowReport/data"
HKEX_MARKET_CAPITALISATION_URL = (
    "https://www.hkex.com.hk/Market-Data/Statistics/Consolidated-Reports/"
    "Securities-Statistics-Archive/Market_capitalisation?sc_lang=en"
)
HKEX_MARKET_CAPITALISATION_INDEX_JSON = (
    "https://www.hkex.com.hk/eng/stat/smstat/mthbull/rpt_data_statistics_archive_market_cap.json"
)
HKEX_WIDGET_DATA_URL = "https://www1.hkex.com.hk/hkexwidget/data"
HKEX_WIDGET_FALLBACK_TOKEN = "evLtsLsBNAUVTPxtGqVeG2wl4vwjdoyNH%2fY1TR8arKHAWbWHFCPMdimMC2E4qZLz"
CBOE_US_EQUITIES_MARKET_SHARE_URL = "https://www.cboe.com/us/equities/market_share/"
CBOE_US_EQUITIES_NOTIONAL_CSV_URL = "https://www.cboe.com/us/equities/market_share/market/csv/"
CBOE_US_EQUITIES_HISTORY_CSV_URL = (
    "https://cdn.cboe.com/resources/us/equities/market-statistics/"
    "historical-market-volume/market_history_{year}.csv"
)
SINA_CN_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20kline=/CN_MarketDataService.getKLineData"
SINA_US_KLINE_URL = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20kline=/US_MinKService.getDailyK"
TENCENT_HK_KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"
FINRA_MARGIN_STATS_URL = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
FINRA_MARGIN_STATS_XLSX_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
HK_SFC_MARGIN_REVIEW_URL = (
    "https://www.sfc.hk/-/media/EN/files/COM/Reports-and-surveys/"
    "Financial-Review-of-the-Securities-Industry-for-the-year-ended-31-December-2025.pdf"
    "?hash=C2C3AD9DA908BE8A424A7382ED8D50EE&rev=f37e312d400840638b7dd4e372363ec6"
)
HK_SFC_MARGIN_BALANCE = {
    "balance": 216_400_000_000,
    "date": "2025-12-31",
    "source": "SFC Financial Review 2025",
    "sourceUrl": HK_SFC_MARGIN_REVIEW_URL,
}

GDP_REFERENCES = {
    "a_share": {
        "value": 140_187_900_000_000,
        "currency": "CNY",
        "label": "中国2025名义GDP，国家统计局初步核算",
        "source": "NBS",
        "url": "https://www.stats.gov.cn/english/PressRelease/202601/t20260119_1962328.html",
    },
    "hk": {
        "value": 843_930_000_000 * 4,
        "currency": "HKD",
        "label": "香港2026Q1名义GDP年化，HKMA经济金融数据",
        "source": "HKMA/C&SD",
        "url": "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/economic-financial-data-for-hong-kong/",
    },
    "us": {
        "value": 31_819_464_000_000,
        "currency": "USD",
        "label": "美国2026Q1名义GDP年化，FRED/BEA",
        "source": "FRED/BEA",
        "url": "https://fred.stlouisfed.org/series/GDP",
    },
}

MARKET_DEFS = [
    {
        "id": "a_share",
        "name": "A股",
        "scanner": "china",
        "currency": "CNY",
        "currencyName": "人民币",
        "universe": "TradingView 中国市场普通股主上市口径",
        "indexMarket": "china",
        "indices": [
            ("SSE:000001", "上证指数"),
            ("SSE:000300", "沪深300"),
            ("SZSE:399001", "深证成指"),
            ("SZSE:399006", "创业板指"),
        ],
    },
    {
        "id": "hk",
        "name": "港股",
        "scanner": "hongkong",
        "currency": "HKD",
        "currencyName": "港元",
        "universe": "TradingView 香港市场普通股主上市口径",
        "indexMarket": "hongkong",
        "indices": [
            ("HSI:HSI", "恒生指数"),
            ("HSI:HSCEI", "恒生国企"),
            ("HSI:HSTECH", "恒生科技"),
        ],
    },
    {
        "id": "us",
        "name": "美股",
        "scanner": "america",
        "currency": "USD",
        "currencyName": "美元",
        "universe": "TradingView 美国市场普通股主上市口径",
        "indexMarket": "america",
        "indices": [
            ("SP:SPX", "标普500"),
            ("NASDAQ:IXIC", "纳斯达克综指"),
            ("NASDAQ:NDX", "纳斯达克100"),
            ("DJ:DJI", "道琼斯工业"),
        ],
    },
]

INDEX_KLINE_DEFS = {
    "SSE:000001": {"source": "Sina CN 日K", "provider": "sina_cn", "symbol": "sh000001"},
    "SSE:000300": {"source": "Sina CN 日K", "provider": "sina_cn", "symbol": "sh000300"},
    "SZSE:399001": {"source": "Sina CN 日K", "provider": "sina_cn", "symbol": "sz399001"},
    "SZSE:399006": {"source": "Sina CN 日K", "provider": "sina_cn", "symbol": "sz399006"},
    "HSI:HSI": {"source": "Tencent HK 日K", "provider": "tencent_hk", "symbol": "hkHSI"},
    "HSI:HSCEI": {"source": "Tencent HK 日K", "provider": "tencent_hk", "symbol": "hkHSCEI"},
    "HSI:HSTECH": {"source": "Tencent HK 日K", "provider": "tencent_hk", "symbol": "hkHSTECH"},
    "SP:SPX": {"source": "Sina US 日K", "provider": "sina_us", "symbol": ".INX"},
    "NASDAQ:IXIC": {"source": "Sina US 日K", "provider": "sina_us", "symbol": ".IXIC"},
    "NASDAQ:NDX": {"source": "Sina US 日K", "provider": "sina_us", "symbol": ".NDX"},
    "DJ:DJI": {"source": "Sina US 日K", "provider": "sina_us", "symbol": ".DJI"},
}

MARKET_PE_HISTORY_DEFS = {
    "hk": {
        "source": "Legulegu Hang Seng Index PE history",
        "page": f"{LEGU}/stockdata/market/hk/dv/hsi",
        "api": f"{LEGU}/api/stockdata/hs",
        "params": {"indexCode": "HSI"},
        "field": "pe",
    },
    "us": {
        "source": "Legulegu S&P 500 PE history",
        "page": f"{LEGU}/stockdata/charts/630",
        "api": f"{LEGU}/api/get-aggregation-data/exp",
        "field": "aggregation_series",
    },
}

MARKET_PE_DISABLED_NOTES = {
    "a_share": "口径不一致",
}

PE_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60

WORLD_ETFS = [
    {"symbol": "XLK", "sector": "科技", "name": "科技行业精选 ETF-SPDR"},
    {"symbol": "XLF", "sector": "金融", "name": "金融行业精选 ETF-SPDR"},
    {"symbol": "XLV", "sector": "医疗保健", "name": "医疗保健行业精选 ETF-SPDR"},
    {"symbol": "XLE", "sector": "能源", "name": "能源行业精选 ETF-SPDR"},
    {"symbol": "XLI", "sector": "工业", "name": "工业行业精选 ETF-SPDR"},
    {"symbol": "XLY", "sector": "可选消费", "name": "可选消费行业精选 ETF-SPDR"},
    {"symbol": "XLP", "sector": "日常消费", "name": "日常消费行业精选 ETF-SPDR"},
    {"symbol": "XLB", "sector": "材料", "name": "材料行业精选 ETF-SPDR"},
    {"symbol": "XLU", "sector": "公用事业", "name": "公用事业行业精选 ETF-SPDR"},
    {"symbol": "VNQ", "sector": "房地产", "name": "美国房地产 ETF-Vanguard"},
]


async def get_stocks(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    async with STOCK_CACHE_LOCK:
        if (
            not refresh
            and STOCK_CACHE["data"]
            and STOCK_CACHE["data"].get("schemaVersion") == STOCK_SCHEMA_VERSION
            and datetime.now(UTC) < STOCK_CACHE["expires_at"]
        ):
            cached = dict(STOCK_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = await load_latest_stocks(db_path)
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == STOCK_SCHEMA_VERSION)
    if stored and stored_schema_valid and has_stock_payload(stored) and not refresh:
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = False
        stored["stale"] = effective_expires_at(stored, ttl_seconds) <= datetime.now(UTC)
        async with STOCK_CACHE_LOCK:
            STOCK_CACHE["data"] = stored
            STOCK_CACHE["expires_at"] = effective_expires_at(stored, ttl_seconds)
        return stored

    stored_is_fresh = bool(
        stored
        and stored_schema_valid
        and has_stock_payload(stored)
        and effective_expires_at(stored, ttl_seconds) > datetime.now(UTC)
    )
    if (
        not force
        and stored
        and stored_schema_valid
        and has_stock_payload(stored)
        and ((allow_stale and not refresh) or stored_is_fresh)
    ):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with STOCK_CACHE_LOCK:
            STOCK_CACHE["data"] = stored
            STOCK_CACHE["expires_at"] = effective_expires_at(stored, ttl_seconds)
        return stored

    request_state = RequestState(
        max_concurrency=1,
        per_domain_concurrency=1,
        timeout=float(fetch_config.get("request_timeout_seconds", 8)),
        retries=int(fetch_config.get("retries", 1)),
    )
    errors: list[str] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(request_state.timeout),
    ) as client:
        try:
            china = await fetch_china_market(client, request_state)
        except Exception as error:
            errors.append(f"中国股票数据：{error}")
            china = empty_china()
        try:
            world = await fetch_world_market(client, request_state)
        except Exception as error:
            errors.append(f"世界股票数据：{error}")
            world = empty_world()

    try:
        markets = await asyncio.to_thread(fetch_market_overviews_sync, db_path, request_state.timeout)
    except Exception as error:
        errors.append(f"市场流动性数据：{error}")
        markets = empty_markets()

    warnings = china.pop("_warnings", []) if isinstance(china, dict) else []
    errors.extend(warnings)

    now = datetime.now(UTC)
    data = {
        "schemaVersion": STOCK_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": False,
        "source": "TradingView Scanner / HKEX每日市场概况 / 东方财富融资融券 / FINRA Margin Statistics / SFC Financial Review / 东方财富板块资金流向 / 同花顺行业资金流向",
        "cadence": "半小时最多真实抓取一次",
        "errors": errors,
        "markets": markets,
        "china": china,
        "world": world,
    }
    data["hasData"] = has_stock_payload(data)

    if not data["hasData"] and stored and has_stock_payload(stored):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["stale"] = True
        return stored

    if data["hasData"]:
        await save_latest_stocks(db_path, data)
        async with STOCK_CACHE_LOCK:
            STOCK_CACHE["data"] = data
            STOCK_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


class RequestState:
    def __init__(self, max_concurrency: int, per_domain_concurrency: int, timeout: float, retries: int) -> None:
        self.global_sem = asyncio.Semaphore(max_concurrency)
        self.domain_sems = {
            "push2.eastmoney.com": asyncio.Semaphore(per_domain_concurrency),
            "push2his.eastmoney.com": asyncio.Semaphore(per_domain_concurrency),
        }
        self.timeout = timeout
        self.retries = retries
        self.eastmoney_available: bool | None = None


async def fetch_china_market(client: httpx.AsyncClient, request_state: RequestState) -> dict[str, Any]:
    warnings: list[str] = []

    try:
        china = await fetch_china_from_eastmoney(client, request_state)
        request_state.eastmoney_available = True
        china["_warnings"] = warnings
        return china
    except Exception as error:
        request_state.eastmoney_available = False
        warnings.append("东方财富行业接口本轮断连，已启用同花顺行业资金流向备用。")

    china = await asyncio.to_thread(fetch_china_from_ths_sync, request_state.timeout)
    china["_warnings"] = warnings
    return china


async def fetch_china_from_eastmoney(client: httpx.AsyncClient, request_state: RequestState) -> dict[str, Any]:
    params = {
        "pn": "1",
        "pz": "60",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": "m:90 s:4",
        "stat": "1",
        "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
        "ut": "8dec03ba335b81bf4ebdf7b29ec27d15",
    }
    data = await fetch_eastmoney_json(f"{EASTMONEY}/api/qt/clist/get?{urlencode(params)}", client, request_state, EASTMONEY_BKZJ_URL)
    rows = data.get("data", {}).get("diff", []) or []
    if not rows:
        raise RuntimeError("empty Eastmoney industry rows")

    industries = [parse_eastmoney_industry(row) for row in rows]
    visible_codes = {item["code"] for item in industries[:20] if item.get("code")}
    perf_map = await fetch_china_performance_map(visible_codes, client, request_state)
    for item in industries:
        item.update(perf_map.get(item["code"], {}))
        item["summary"] = china_summary(item["name"], item.get("mainNetInflow"), item.get("dayPct"), item.get("weekPct"), item.get("monthPct"))

    inflow, outflow = split_flow_rank(industries)
    return {
        "title": "中国行业资金流",
        "source": "东方财富板块资金流向",
        "sourceUrl": EASTMONEY_BKZJ_URL,
        "note": "东财板块资金流向行业口径；日为今日涨跌幅，周/月/年来自可取到的行业 K 线。",
        "margin": await asyncio.to_thread(fetch_margin_from_ths_sync, request_state.timeout),
        "industries": industries[:60],
        "inflow": inflow,
        "outflow": outflow,
    }


def fetch_china_from_ths_sync(timeout: float) -> dict[str, Any]:
    session = requests.Session()
    try:
        current_html = request_text(session, THS_HYZJL_URL, ths_headers(THS_HYZJL_URL), timeout, encoding="gbk")
        time.sleep(random.uniform(1.2, 2.4))
        week_html = request_text(
            session,
            f"{THS_HYZJL_URL}board/5/field/tradezdf/order/DESC/page/1/",
            ths_headers(THS_HYZJL_URL),
            timeout,
            encoding="gbk",
        )
        time.sleep(random.uniform(1.2, 2.4))
        month_html = request_text(
            session,
            f"{THS_HYZJL_URL}board/20/field/tradezdf/order/DESC/page/1/",
            ths_headers(THS_HYZJL_URL),
            timeout,
            encoding="gbk",
        )

        rows = parse_ths_current_rows(current_html)
        if not rows:
            raise RuntimeError("empty THS industry rows")

        week_map = parse_ths_period_map(week_html)
        month_map = parse_ths_period_map(month_html)
        industries = []
        for row in rows:
            name = row["name"]
            row["weekPct"] = week_map.get(name, {}).get("stagePct")
            row["weekNetInflow"] = week_map.get(name, {}).get("netInflow")
            row["monthPct"] = month_map.get(name, {}).get("stagePct")
            row["monthNetInflow"] = month_map.get(name, {}).get("netInflow")
            row["yearPct"] = None
            row["summary"] = china_summary(name, row.get("mainNetInflow"), row.get("dayPct"), row.get("weekPct"), row.get("monthPct"))
            industries.append(row)

        inflow, outflow = split_flow_rank(industries)
        margin = fetch_margin_from_ths_sync(timeout, session=session)
        return {
            "title": "中国行业资金流",
            "source": "同花顺行业资金流向",
            "sourceUrl": THS_HYZJL_URL,
            "note": "东财接口断连时使用同花顺行业资金流向；日为即时涨跌幅，周/月用 5日/20日排行近似。",
            "margin": margin,
            "industries": industries[:60],
            "inflow": inflow,
            "outflow": outflow,
        }
    finally:
        session.close()


def parse_ths_current_rows(html: str) -> list[dict[str, Any]]:
    rows = []
    for values in extract_table_rows(html):
        if len(values) < 11 or not values[0].isdigit():
            continue
        net = yuan_from_yi(values[6])
        buy = yuan_from_yi(values[4])
        sell = yuan_from_yi(values[5])
        rows.append(
            {
                "code": f"ths:{values[1]}",
                "name": values[1],
                "proxy": values[8],
                "dayPct": safe_float(values[3].replace("%", "")),
                "weekPct": None,
                "monthPct": None,
                "yearPct": None,
                "price": safe_float(values[2]),
                "mainNetInflow": net,
                "mainNetInflowText": format_money(net),
                "mainNetRatio": None,
                "buyAmount": buy,
                "sellAmount": sell,
                "companyCount": safe_float(values[7]),
                "leader": values[8],
                "leaderPct": safe_float(values[9].replace("%", "")),
            }
        )
    return rows


def parse_ths_period_map(html: str) -> dict[str, dict[str, Any]]:
    result = {}
    for values in extract_table_rows(html):
        if len(values) < 8 or not values[0].isdigit():
            continue
        result[values[1]] = {
            "stagePct": safe_float(values[4].replace("%", "")),
            "netInflow": yuan_from_yi(values[7]),
        }
    return result


def fetch_margin_from_ths_sync(timeout: float, session: requests.Session | None = None) -> dict[str, Any]:
    own_session = session is None
    session = session or requests.Session()
    try:
        html = request_text(session, THS_MARGIN_URL, ths_headers("https://data.10jqka.com.cn/"), timeout, encoding="gbk")
        data = parse_margin_data_day(html)
        if not data:
            return margin_placeholder("同花顺融资融券页未返回最新曲线数据。")
        date, _, metrics = data
        metric_values = [item[1] for item in metrics if isinstance(item, list) and len(item) >= 2]
        balance = yuan_from_yi(metric_values[0]) if len(metric_values) > 0 else None
        finance_balance = yuan_from_yi(metric_values[3]) if len(metric_values) > 3 else None
        security_balance = yuan_from_yi(metric_values[4]) if len(metric_values) > 4 else None
        return {
            "source": "同花顺 A股融资融券",
            "sourceUrl": THS_MARGIN_URL,
            "status": "ok",
            "summary": f"截至 {date}，A股两融余额 {format_money(balance)}，融资余额 {format_money(finance_balance)}。",
            "balance": balance,
            "financeBalance": finance_balance,
            "securityBalance": security_balance,
            "date": date,
        }
    except Exception as error:
        return margin_placeholder(f"融资余额暂未取到：{error}")
    finally:
        if own_session:
            session.close()


def parse_margin_data_day(html: str) -> list[Any] | None:
    match = re.search(r"var\s+dataDay\s*=\s*(\[.*?\]);", html, re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    records: list[list[Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            if len(value) >= 3 and isinstance(value[0], str) and re.match(r"\d{4}-\d{2}-\d{2}", value[0]):
                records.append(value)
            for item in value:
                walk(item)

    walk(payload)
    return records[-1] if records else None


def extract_table_rows(html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", match.group(1), flags=re.S | re.I)
        values = []
        for cell in cells:
            cleaned = re.sub(r"<script.*?</script>", "", cell, flags=re.S | re.I)
            cleaned = re.sub(r"<style.*?</style>", "", cleaned, flags=re.S | re.I)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            cleaned = unescape(re.sub(r"\s+", " ", cleaned)).strip()
            if cleaned:
                values.append(cleaned)
        if values:
            rows.append(values)
    return rows


async def fetch_china_performance_map(
    codes: set[str],
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for code in sorted(codes):
        try:
            result[code] = await fetch_kline_performance(f"90.{code}", client, request_state)
        except Exception:
            result[code] = {"weekPct": None, "monthPct": None, "yearPct": None}
    return result


async def fetch_world_market(client: httpx.AsyncClient, request_state: RequestState) -> dict[str, Any]:
    if request_state.eastmoney_available is False:
        return {
            "title": "世界行业代理",
            "source": "东方财富美股 ETF 行情",
            "note": "本轮东财行情域已断连，为避免重复触发反爬，世界 ETF 暂保留占位，等待下次半小时刷新。",
            "industries": [world_placeholder(etf, "东财行情域本轮不可用，已跳过重复请求。") for etf in WORLD_ETFS],
        }

    industries = []
    for etf in WORLD_ETFS:
        try:
            perf = await fetch_kline_performance(f"107.{etf['symbol']}", client, request_state)
            quote = await fetch_quote(f"107.{etf['symbol']}", client, request_state)
            industries.append(
                {
                    "code": etf["symbol"],
                    "name": etf["sector"],
                    "proxy": etf["name"],
                    "dayPct": quote.get("dayPct", perf.get("dayPct")),
                    "weekPct": perf.get("weekPct"),
                    "monthPct": perf.get("monthPct"),
                    "yearPct": perf.get("yearPct"),
                    "price": quote.get("price"),
                    "amount": quote.get("amount"),
                    "marketCap": quote.get("marketCap"),
                    "mainNetInflow": None,
                    "mainNetInflowText": "暂无资金流",
                    "summary": world_summary(etf["sector"], perf),
                }
            )
        except Exception:
            industries.append(
                {
                    "code": etf["symbol"],
                    "name": etf["sector"],
                    "proxy": etf["name"],
                    "dayPct": None,
                    "weekPct": None,
                    "monthPct": None,
                    "yearPct": None,
                    "price": None,
                    "amount": None,
                    "marketCap": None,
                    "mainNetInflow": None,
                    "mainNetInflowText": "暂无资金流",
                    "summary": "东财暂未返回该 ETF 行情，保留占位。",
                }
            )

    return {
        "title": "世界行业代理",
        "source": "东方财富美股 ETF 行情",
        "note": "世界行业以美股行业 ETF 代理；东财不提供同口径资金流，展示价格表现与成交额/规模。",
        "industries": industries,
    }


def world_placeholder(etf: dict[str, str], summary: str) -> dict[str, Any]:
    return {
        "code": etf["symbol"],
        "name": etf["sector"],
        "proxy": etf["name"],
        "dayPct": None,
        "weekPct": None,
        "monthPct": None,
        "yearPct": None,
        "price": None,
        "amount": None,
        "marketCap": None,
        "mainNetInflow": None,
        "mainNetInflowText": "暂无资金流",
        "summary": summary,
    }


async def fetch_quote(secid: str, client: httpx.AsyncClient, request_state: RequestState) -> dict[str, Any]:
    params = {
        "secid": secid,
        "fields": "f57,f58,f43,f60,f170,f169,f171,f116,f47,f48",
    }
    data = await fetch_eastmoney_json(f"{EASTMONEY}/api/qt/stock/get?{urlencode(params)}", client, request_state)
    row = data.get("data") or {}
    return {
        "price": scaled(row.get("f43")),
        "dayPct": scaled(row.get("f170")),
        "amount": row.get("f48"),
        "marketCap": row.get("f116"),
    }


async def fetch_kline_performance(
    secid: str,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> dict[str, float | None]:
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": "260",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    data = await fetch_eastmoney_json(f"{EASTMONEY_HIS}/api/qt/stock/kline/get?{urlencode(params)}", client, request_state)
    klines = (data.get("data") or {}).get("klines") or []
    closes = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 3:
            closes.append((parts[0], safe_float(parts[2])))
    closes = [(date, close) for date, close in closes if close is not None and close > 0]
    if len(closes) < 2:
        return {"dayPct": None, "weekPct": None, "monthPct": None, "yearPct": None}

    latest = closes[-1][1]
    year = datetime.now().year
    year_start = next((close for date, close in closes if date.startswith(str(year))), closes[0][1])
    return {
        "dayPct": pct_change(latest, closes[-2][1]) if len(closes) >= 2 else None,
        "weekPct": pct_change(latest, closes[-6][1]) if len(closes) >= 6 else None,
        "monthPct": pct_change(latest, closes[-22][1]) if len(closes) >= 22 else None,
        "yearPct": pct_change(latest, year_start),
    }


async def fetch_eastmoney_json(
    url: str,
    client: httpx.AsyncClient,
    request_state: RequestState,
    referer: str = "https://quote.eastmoney.com/",
) -> dict[str, Any]:
    domain = "push2his.eastmoney.com" if "push2his" in url else "push2.eastmoney.com"
    sem = request_state.domain_sems[domain]
    async with request_state.global_sem, sem:
        await asyncio.sleep(random.uniform(1.2, 2.6))
        last_error: Exception | None = None
        for attempt in range(request_state.retries + 1):
            try:
                response = await client.get(url, headers=eastmoney_headers(referer))
                response.raise_for_status()
                text = response.text.strip()
                if not text:
                    raise RuntimeError("empty response")
                return json.loads(text)
            except Exception as error:
                last_error = error
                if attempt < request_state.retries:
                    await asyncio.sleep(1.4 + random.uniform(0.3, 0.9))
        raise RuntimeError(repr(last_error))


def request_text(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    timeout: float,
    encoding: str | None = None,
) -> str:
    response = session.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    if encoding:
        response.encoding = encoding
    return response.text


def parse_eastmoney_industry(row: dict[str, Any]) -> dict[str, Any]:
    main_net = row.get("f62")
    name = row.get("f14")
    return {
        "code": row.get("f12"),
        "name": name,
        "dayPct": row.get("f3"),
        "weekPct": None,
        "monthPct": None,
        "yearPct": None,
        "price": row.get("f2"),
        "mainNetInflow": main_net,
        "mainNetInflowText": format_money(main_net),
        "mainNetRatio": row.get("f184"),
        "superLargeNet": row.get("f66"),
        "largeNet": row.get("f72"),
        "middleNet": row.get("f78"),
        "smallNet": row.get("f84"),
        "leader": row.get("f204"),
        "leaderPct": row.get("f205"),
    }


def split_flow_rank(industries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inflow = sorted(
        [item for item in industries if value_or_zero(item.get("mainNetInflow")) > 0],
        key=lambda item: value_or_zero(item.get("mainNetInflow")),
        reverse=True,
    )[:20]
    outflow = sorted(
        [item for item in industries if value_or_zero(item.get("mainNetInflow")) < 0],
        key=lambda item: value_or_zero(item.get("mainNetInflow")),
    )[:20]
    return inflow, outflow


def china_summary(name: str, main_net: Any, day_pct: Any, week_pct: Any, month_pct: Any) -> str:
    direction = "流入" if value_or_zero(main_net) >= 0 else "流出"
    strength = "较强" if abs(value_or_zero(main_net)) >= 1_000_000_000 else "一般"
    return (
        f"{name}今日主力资金{direction}{format_money(abs(value_or_zero(main_net)))}，力度{strength}；"
        f"日{format_pct(day_pct)}，5日{format_pct(week_pct)}，20日{format_pct(month_pct)}。"
    )


def world_summary(sector: str, perf: dict[str, Any]) -> str:
    week = format_pct(perf.get("weekPct"))
    month = format_pct(perf.get("monthPct"))
    return f"{sector}行业以美股 ETF 代理观察；近一周{week}，近一月{month}，资金流口径暂缺。"


def margin_placeholder(summary: str | None = None) -> dict[str, Any]:
    return {
        "source": "同花顺 A股融资融券",
        "sourceUrl": THS_MARGIN_URL,
        "status": "pending",
        "summary": summary or "融资余额接口口径待接入；当前先展示行业资金流和行情表现。",
        "balance": None,
        "financeBalance": None,
        "securityBalance": None,
        "date": "",
    }


def eastmoney_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Origin": "https://data.eastmoney.com" if "eastmoney.com" in referer else "https://quote.eastmoney.com",
        "Connection": "close",
    }


def ths_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Connection": "close",
    }


def sina_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Connection": "close",
    }


def tencent_headers() -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://gu.qq.com/",
        "Connection": "close",
    }


def hkex_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/javascript,application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Connection": "close",
    }


def extract_jsonp_payload(text: str) -> str:
    cleaned = re.sub(r"^/\*.*?\*/\s*", "", text.strip(), flags=re.S)
    match = re.search(r"=\s*(\(.*\)|\[.*\]|\{.*\}|null)\s*;?\s*$", cleaned, flags=re.S)
    if not match:
        raise ValueError("invalid jsonp payload")
    payload = match.group(1).strip()
    if payload.startswith("(") and payload.endswith(")"):
        payload = payload[1:-1].strip()
    if payload == "null":
        return "[]"
    return payload


def random_user_agent() -> str:
    return random.choice(
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        ]
    )


def empty_china() -> dict[str, Any]:
    return {"title": "中国行业资金流", "source": "东方财富/同花顺", "note": "", "margin": margin_placeholder(), "industries": [], "inflow": [], "outflow": []}


def empty_world() -> dict[str, Any]:
    return {"title": "世界行业代理", "source": "东方财富", "note": "", "industries": []}


def empty_market(market_def: dict[str, Any], note: str = "本轮市场聚合数据暂未取到。") -> dict[str, Any]:
    return {
        "id": market_def["id"],
        "name": market_def["name"],
        "currency": market_def["currency"],
        "currencyName": market_def["currencyName"],
        "source": "公开来源",
        "universe": market_def["universe"],
        "marketCap": None,
        "marketCapLabel": "当前总市值",
        "marketCapCrossChecks": [],
        "gdp": GDP_REFERENCES[market_def["id"]],
        "marketCapToGdpPct": None,
        "turnover": None,
        "turnoverToMarketCapPct": None,
        "turnoverPercentile": None,
        "turnoverPercentileSample": 0,
        "turnoverPercentileSource": "",
        "turnoverPercentileNote": "暂无可靠历史基准",
        "pe": None,
        "pePercentile": None,
        "pePercentileSample": 0,
        "pePercentileSource": "",
        "pePercentileNote": "",
        "financingBalance": None,
        "financingToMarketCapPct": None,
        "financingPercentile": None,
        "financingPercentileSample": 0,
        "financingPercentileSource": "",
        "financingPercentileNote": "暂无可靠历史基准",
        "financingSource": "",
        "financingSourceUrl": "",
        "financingDataTimestamp": "",
        "totalCount": 0,
        "includedCount": 0,
        "indices": [],
        "topCompanies": [],
        "note": note,
    }


def empty_markets() -> list[dict[str, Any]]:
    return [empty_market(item) for item in MARKET_DEFS]


MARKET_METRIC_LABELS = {
    "marketCap": "总市值",
    "turnover": "成交额",
    "pe": "PE",
}


def append_market_candidate_error(
    candidates: list[dict[str, Any]],
    source: str,
    error: Exception,
    source_url: str = "",
) -> None:
    candidates.append(
        {
            "source": source,
            "sourceUrl": source_url,
            "error": str(error),
            "priority": 0,
        }
    )


def assess_market_data_candidates(candidates: list[dict[str, Any]], market_id: str) -> list[dict[str, Any]]:
    expected_date = expected_market_snapshot_date(market_id)
    for candidate in candidates:
        metrics = [
            metric
            for metric in MARKET_METRIC_LABELS
            if candidate_metric_value(candidate, metric) is not None
        ]
        snapshot_date = candidate_snapshot_date(candidate)
        is_stale, stale_reason = candidate_staleness(market_id, snapshot_date, expected_date)
        freshness_score = 30 if snapshot_date and not is_stale else 12 if not snapshot_date else -90
        completeness_score = len(metrics) * 8
        priority_score = int(candidate.get("priority") or 0)
        candidate["availableMetrics"] = [MARKET_METRIC_LABELS[metric] for metric in metrics]
        candidate["expectedDate"] = expected_date.isoformat()
        candidate["snapshotDate"] = snapshot_date.isoformat() if snapshot_date else ""
        candidate["isStale"] = is_stale
        candidate["stalenessReason"] = stale_reason
        candidate["score"] = priority_score + freshness_score + completeness_score
        if candidate.get("error"):
            candidate["score"] = 0
    return candidates


def select_market_metrics(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for metric in MARKET_METRIC_LABELS:
        metric_candidates = [
            candidate
            for candidate in candidates
            if candidate_metric_value(candidate, metric) is not None
        ]
        if not metric_candidates:
            continue
        fresh_candidates = [candidate for candidate in metric_candidates if not candidate.get("isStale")]
        pool = fresh_candidates or metric_candidates
        selected[metric] = max(
            pool,
            key=lambda candidate: (
                int(candidate.get(f"{metric}Priority") or candidate.get("priority") or 0),
                int(candidate.get("score") or 0),
            ),
        )
    return selected


def candidate_metric_value(candidate: dict[str, Any], metric: str) -> float | None:
    value = safe_float(candidate.get(metric))
    return value if value is not None and value > 0 else None


def expected_market_snapshot_date(market_id: str) -> date:
    if market_id == "us":
        now = datetime.now(US_EASTERN_TZ)
        expected = now.date()
        if now.weekday() >= 5 or now.hour < 16:
            expected = previous_business_day(expected)
        return expected

    now = datetime.now(CN_TZ)
    expected = now.date()
    if now.weekday() >= 5 or now.hour < 16:
        expected = previous_business_day(expected)
    return expected


def previous_business_day(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def candidate_staleness(market_id: str, snapshot_date: date | None, expected_date: date) -> tuple[bool, str]:
    if not snapshot_date:
        return False, ""

    if market_id in ("a_share", "hk") and snapshot_date < expected_date:
        return True, f"日期{snapshot_date.isoformat()}早于应有交易日{expected_date.isoformat()}"

    if market_id == "us" and snapshot_date < previous_business_day(expected_date):
        return True, f"日期{snapshot_date.isoformat()}早于可接受交易日{previous_business_day(expected_date).isoformat()}"

    return False, ""


def candidate_snapshot_date(candidate: dict[str, Any]) -> date | None:
    for key in ("date", "dataDate"):
        parsed = parse_candidate_date(candidate.get(key))
        if parsed:
            return parsed
    for key in ("updatedAt", "dataTimestamp"):
        parsed = parse_candidate_date(candidate.get(key))
        if parsed:
            return parsed
    return None


def parse_candidate_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        parsed = parse_dt(text)
        if parsed > datetime.min.replace(tzinfo=UTC):
            return parsed.astimezone(CN_TZ).date()
    normalized = text.replace("/", "-").split(" ")[0]
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def candidate_timestamp_iso(candidate: dict[str, Any], market_id: str) -> str:
    for key in ("updatedAt", "dataTimestamp"):
        value = candidate.get(key)
        if value:
            parsed = parse_dt(str(value))
            if parsed > datetime.min.replace(tzinfo=UTC):
                return parsed.isoformat()

    snapshot_date = candidate_snapshot_date(candidate)
    if not snapshot_date:
        return ""
    if market_id == "us":
        return datetime.fromisoformat(f"{snapshot_date.isoformat()}T20:00:00-04:00").astimezone(UTC).isoformat()
    return datetime.fromisoformat(f"{snapshot_date.isoformat()}T16:00:00+08:00").astimezone(UTC).isoformat()


def selected_market_timestamp(selected_metrics: dict[str, dict[str, Any]], market_id: str) -> str:
    timestamps = []
    for candidate in selected_metrics.values():
        timestamp = candidate_timestamp_iso(candidate, market_id)
        if timestamp:
            timestamps.append(parse_dt(timestamp))
    return max(timestamps).isoformat() if timestamps else ""


def selected_market_sources(selected_metrics: dict[str, dict[str, Any]]) -> str:
    sources: list[str] = []
    for metric in MARKET_METRIC_LABELS:
        candidate = selected_metrics.get(metric)
        source = str(candidate.get("source") or "") if candidate else ""
        if source and source not in sources:
            sources.append(source)
    return " / ".join(sources)


def selected_source_url(selected_metrics: dict[str, dict[str, Any]], fallback: str) -> str:
    for metric in ("marketCap", "turnover", "pe"):
        candidate = selected_metrics.get(metric)
        if candidate and candidate.get("sourceUrl"):
            return str(candidate["sourceUrl"])
    return fallback


def market_cap_label_from_candidate(market_id: str, candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "当前总市值"
    source = str(candidate.get("source") or "")
    if market_id == "a_share" and "SSE/SZSE" in source:
        return "官方总市值"
    if market_id == "hk" and "每日市场概况" in source:
        return "官方总市值(每日)"
    if market_id == "hk" and "市值归档" in source:
        return "官方总市值(最新归档)"
    return "当前总市值"


def build_market_selection_note(
    selected_metrics: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
    base_note: str,
) -> str:
    selected_parts = []
    for metric, label in MARKET_METRIC_LABELS.items():
        candidate = selected_metrics.get(metric)
        if not candidate:
            continue
        date_text = f"（{candidate.get('snapshotDate')}）" if candidate.get("snapshotDate") else ""
        selected_parts.append(f"{label}取{candidate.get('source')}{date_text}")

    stale_parts = [
        f"{candidate.get('source')} {candidate.get('stalenessReason')}"
        for candidate in candidates
        if candidate.get("isStale") and candidate.get("stalenessReason")
    ]
    error_parts = [
        f"{candidate.get('source')}失败：{candidate.get('error')}"
        for candidate in candidates
        if candidate.get("error")
    ]
    parts = []
    if selected_parts:
        parts.append(f"多源评估：{'，'.join(selected_parts)}")
    if stale_parts:
        parts.append(f"已降权/剔除旧数据：{'；'.join(stale_parts[:3])}")
    if error_parts:
        parts.append(f"异常来源：{'；'.join(error_parts[:2])}")
    if base_note:
        parts.append(base_note)
    return "；".join(parts)


def public_market_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in candidate.items() if key != "raw"}
        for candidate in candidates
    ]


def fetch_market_overviews_sync(db_path: Path, timeout: float) -> list[dict[str, Any]]:
    session = requests.Session()
    try:
        markets = []
        for market_def in MARKET_DEFS:
            try:
                markets.append(fetch_one_market_overview_sync(session, market_def, timeout))
            except Exception as error:
                markets.append(empty_market(market_def, f"本轮市场聚合数据暂未取到：{error}"))
            time.sleep(random.uniform(1.4, 2.4))
        apply_market_history(db_path, markets)
        return markets
    finally:
        session.close()


def fetch_one_market_overview_sync(
    session: requests.Session,
    market_def: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    tradingview_error = ""
    try:
        rows, total_count = fetch_tradingview_stock_rows(session, market_def["scanner"], timeout)
    except Exception as error:
        if market_def["id"] != "hk":
            raise
        rows = []
        total_count = 0
        tradingview_error = str(error)
    market_cap = 0.0
    turnover = 0.0
    pe_cap = 0.0
    earnings = 0.0
    top_companies: list[dict[str, Any]] = []

    for row in rows:
        cap = safe_float(row.get("marketCap"))
        value_traded = safe_float(row.get("turnover"))
        pe = safe_float(row.get("pe"))
        if cap is None or cap <= 0:
            continue
        market_cap += cap
        if value_traded and value_traded > 0:
            turnover += value_traded
        if pe and 0 < pe < 500:
            pe_cap += cap
            earnings += cap / pe
        if len(top_companies) < 6:
            top_companies.append(
                {
                    "symbol": row.get("symbol"),
                    "name": row.get("name"),
                    "marketCap": cap,
                    "turnover": value_traded,
                    "pe": pe,
                }
            )

    gdp_info = GDP_REFERENCES[market_def["id"]]
    gdp_value = safe_float(gdp_info["value"])
    pe_value = pe_cap / earnings if earnings > 0 else None
    turnover_ratio = (turnover / market_cap * 100) if market_cap > 0 else None
    source = "TradingView Scanner"
    source_url = f"https://www.tradingview.com/markets/{market_def['scanner']}/stocks-{market_def['scanner']}/market-movers-large-cap/"
    data_timestamp = ""
    hkex_turnover: dict[str, Any] | None = None
    market_cap_label = "当前总市值"
    market_data_candidates: list[dict[str, Any]] = [
        {
            "source": "TradingView Scanner",
            "sourceUrl": source_url,
            "marketCap": market_cap or None,
            "turnover": turnover or None,
            "pe": pe_value,
            "includedCount": len(rows),
            "totalCount": total_count,
            "priority": 62,
            "marketCapPriority": 66,
            "turnoverPriority": 54,
            "pePriority": 72,
        }
    ]
    if tradingview_error:
        market_data_candidates[0]["error"] = tradingview_error
    note = "总市值、成交额和PE按普通股主上市口径聚合；PE为市值加权口径，成交额为当日可取到的股票成交额合计。"

    if market_def["id"] == "a_share":
        try:
            official = fetch_a_share_official_market_snapshot_sync(session, timeout)
            market_data_candidates.append(
                {
                    **official,
                    "source": "SSE/SZSE官方统计",
                    "priority": 92,
                    "marketCapPriority": 96,
                    "turnoverPriority": 96,
                    "pePriority": 0,
                }
            )
        except Exception as error:
            append_market_candidate_error(market_data_candidates, "SSE/SZSE官方统计", error, f"{SSE_STOCK_STATISTIC_URL} / {SZSE_MARKET_OVERVIEW_URL}")

    if market_def["id"] == "hk":
        try:
            hkex_snapshot = fetch_hkex_market_highlights_sync(session, timeout)
            hkex_snapshot = {
                **hkex_snapshot,
                "source": "HKEX每日市场概况",
                "priority": 94,
                "marketCapPriority": 98,
                "turnoverPriority": 94,
                "pePriority": 92,
            }
            market_data_candidates.append(hkex_snapshot)
            hkex_turnover = {
                "source": hkex_snapshot.get("source"),
                "sourceUrl": hkex_snapshot.get("sourceUrl"),
                "turnover": hkex_snapshot.get("turnover"),
                "mainBoardTurnover": hkex_snapshot.get("mainBoardTurnover"),
                "gemTurnover": hkex_snapshot.get("gemTurnover"),
                "date": hkex_snapshot.get("date"),
            }
        except Exception as error:
            append_market_candidate_error(market_data_candidates, "HKEX每日市场概况", error, HKEX_STOCK_CONNECT_HIGHLIGHTS_URL)

        try:
            official_cap = fetch_hkex_market_capitalisation_sync(session, timeout)
            market_data_candidates.append(
                {
                    **official_cap,
                    "source": "HKEX市值归档",
                    "priority": 72,
                    "marketCapPriority": 82,
                    "turnoverPriority": 0,
                    "pePriority": 0,
                }
            )
        except Exception as fallback_error:
            append_market_candidate_error(market_data_candidates, "HKEX市值归档", fallback_error, HKEX_MARKET_CAPITALISATION_URL)

        try:
            hkex_turnover = fetch_hkex_market_turnover_sync(session, timeout)
            market_data_candidates.append(
                {
                    **hkex_turnover,
                    "source": "HKEX实时成交",
                    "priority": 90,
                    "marketCapPriority": 0,
                    "turnoverPriority": 98,
                    "pePriority": 0,
                }
            )
        except Exception as turnover_error:
            hkex_turnover = {"error": str(turnover_error)}
            append_market_candidate_error(market_data_candidates, "HKEX实时成交", turnover_error, HKEX_STOCK_CONNECT_HIGHLIGHTS_URL)

    if market_def["id"] == "us":
        try:
            cboe_turnover = fetch_cboe_us_equities_notional_sync(session, timeout)
            market_data_candidates.append(
                {
                    **cboe_turnover,
                    "source": "Cboe成交额",
                    "priority": 90,
                    "marketCapPriority": 0,
                    "turnoverPriority": 96,
                    "pePriority": 0,
                }
            )
        except Exception as error:
            append_market_candidate_error(market_data_candidates, "Cboe成交额", error, CBOE_US_EQUITIES_MARKET_SHARE_URL)

    market_data_candidates = assess_market_data_candidates(market_data_candidates, market_def["id"])
    selected_metrics = select_market_metrics(market_data_candidates)
    market_cap_candidate = selected_metrics.get("marketCap")
    turnover_candidate = selected_metrics.get("turnover")
    pe_candidate = selected_metrics.get("pe")

    market_cap = candidate_metric_value(market_cap_candidate or {}, "marketCap") or market_cap
    turnover = candidate_metric_value(turnover_candidate or {}, "turnover") or turnover
    pe_value = candidate_metric_value(pe_candidate or {}, "pe") or pe_value
    turnover_ratio = (turnover / market_cap * 100) if market_cap > 0 and turnover > 0 else None
    source = selected_market_sources(selected_metrics) or source
    source_url = selected_source_url(selected_metrics, source_url)
    data_timestamp = selected_market_timestamp(selected_metrics, market_def["id"]) or data_timestamp
    market_cap_label = market_cap_label_from_candidate(market_def["id"], market_cap_candidate)

    if market_def["id"] == "a_share":
        note = "A股总市值和成交额优先采用上交所、深交所官网统计；PE采用可用来源中评分最高的主上市普通股口径。"
    elif market_def["id"] == "hk":
        note = "港股在 TradingView、HKEX每日市场概况、HKEX市值归档和HKEX成交组件之间评分；日期早于应有交易日的数据不作为当前值。"
    elif market_def["id"] == "us":
        note = "美股总市值和PE通常来自 TradingView；成交额优先采用 Cboe Notional Value，覆盖交易所和 FINRA TRF。"

    note = build_market_selection_note(selected_metrics, market_data_candidates, note)

    market = {
        "id": market_def["id"],
        "name": market_def["name"],
        "currency": market_def["currency"],
        "currencyName": market_def["currencyName"],
        "source": source,
        "sourceUrl": source_url,
        "dataTimestamp": data_timestamp,
        "universe": market_def["universe"],
        "marketCapLabel": market_cap_label,
        "marketCap": market_cap or None,
        "marketCapCrossChecks": public_market_candidates(market_data_candidates),
        "marketDataCandidates": public_market_candidates(market_data_candidates),
        "gdp": gdp_info,
        "marketCapToGdpPct": (market_cap / gdp_value * 100) if market_cap and gdp_value else None,
        "turnover": turnover or None,
        "turnoverToMarketCapPct": turnover_ratio,
        "turnoverPercentile": None,
        "turnoverPercentileSample": 0,
        "turnoverPercentileSource": "",
        "turnoverPercentileNote": "",
        "pe": round(pe_value, 2) if pe_value else None,
        "pePercentile": None,
        "pePercentileSample": 0,
        "pePercentileSource": "",
        "pePercentileNote": "",
        "financingBalance": None,
        "financingToMarketCapPct": None,
        "financingPercentile": None,
        "financingPercentileSample": 0,
        "financingPercentileSource": "",
        "financingPercentileNote": "暂无可靠历史基准",
        "financingSource": "",
        "financingSourceUrl": "",
        "financingDataTimestamp": "",
        "totalCount": total_count,
        "includedCount": len(rows),
        "indices": fetch_market_indices_safe_sync(session, market_def, timeout),
        "topCompanies": top_companies,
        "hkexTurnover": hkex_turnover,
        "note": note,
    }
    apply_market_financing_sync(session, market, timeout)
    return market


def apply_market_financing_sync(session: requests.Session, market: dict[str, Any], timeout: float) -> None:
    try:
        if market["id"] == "a_share":
            financing = fetch_a_share_financing_sync(session, timeout)
        elif market["id"] == "hk":
            financing = fetch_hk_financing_sync(market)
        elif market["id"] == "us":
            financing = fetch_us_financing_sync(session, market, timeout)
        else:
            financing = financing_placeholder()
    except Exception as error:
        financing = financing_placeholder(f"融资数据暂未取到：{error}")

    market.update(financing)


def financing_placeholder(note: str = "暂无可靠历史基准") -> dict[str, Any]:
    return {
        "financingBalance": None,
        "financingToMarketCapPct": None,
        "financingToMarketCapBasis": "",
        "financingPercentile": None,
        "financingPercentileSample": 0,
        "financingPercentileSource": "",
        "financingPercentileNote": note,
        "financingSource": "",
        "financingSourceUrl": "",
        "financingDataTimestamp": "",
    }


def fetch_a_share_financing_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    page_number = 1
    pages = 1
    while page_number <= pages and page_number <= 20:
        params = {
            "reportName": "RPTA_RZRQ_LSHJ",
            "columns": "ALL",
            "source": "WEB",
            "sortColumns": "DIM_DATE",
            "sortTypes": "-1",
            "pageNumber": str(page_number),
            "pageSize": "800",
            "filter": "",
        }
        response = session.get(
            EASTMONEY_STOCK_STATS_API,
            params=params,
            headers=eastmoney_headers(EASTMONEY_RZRQ_URL),
            timeout=max(timeout, 20),
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") or {}
        rows.extend(result.get("data") or [])
        try:
            pages = int(result.get("pages") or pages)
        except (TypeError, ValueError):
            pages = page_number
        page_number += 1
        time.sleep(random.uniform(0.2, 0.5))

    records: list[dict[str, Any]] = []
    for row in rows:
        balance = safe_float(row.get("RZYE"))
        ratio = safe_float(row.get("RZYEZB"))
        date = str(row.get("DIM_DATE") or "").split(" ")[0]
        if balance is None or balance <= 0 or ratio is None or ratio <= 0:
            continue
        records.append({"date": date, "balance": balance, "ratio": ratio})

    if not records:
        return financing_placeholder("东方财富融资融券历史总量接口未返回可用数据")

    latest = records[0]
    ratio_values = [item["ratio"] for item in records if item.get("ratio")]
    percentile = percentile_rank(latest["ratio"], ratio_values)
    return {
        "financingBalance": latest["balance"],
        "financingToMarketCapPct": round(latest["ratio"], 4),
        "financingToMarketCapBasis": "流通市值",
        "financingPercentile": percentile,
        "financingPercentileSample": len(ratio_values),
        "financingPercentileSource": "东方财富融资融券历史总量（RZYEZB）",
        "financingPercentileNote": "" if percentile is not None else "暂无可靠历史基准",
        "financingSource": "东方财富融资融券历史总量",
        "financingSourceUrl": EASTMONEY_RZRQ_URL,
        "financingDataTimestamp": latest["date"],
    }


def fetch_hk_financing_sync(market: dict[str, Any]) -> dict[str, Any]:
    balance = safe_float(HK_SFC_MARGIN_BALANCE["balance"])
    market_cap = safe_float(market.get("marketCap"))
    ratio = (balance / market_cap * 100) if balance and market_cap and market_cap > 0 else None
    return {
        "financingBalance": balance,
        "financingToMarketCapPct": round(ratio, 4) if ratio is not None else None,
        "financingToMarketCapBasis": "总市值",
        "financingPercentile": None,
        "financingPercentileSample": 0,
        "financingPercentileSource": "",
        "financingPercentileNote": "暂无同口径历史市值基准",
        "financingSource": HK_SFC_MARGIN_BALANCE["source"],
        "financingSourceUrl": HK_SFC_MARGIN_BALANCE["sourceUrl"],
        "financingDataTimestamp": HK_SFC_MARGIN_BALANCE["date"],
    }


def fetch_us_financing_sync(session: requests.Session, market: dict[str, Any], timeout: float) -> dict[str, Any]:
    records = fetch_finra_margin_records_sync(session, timeout)
    if not records:
        return financing_placeholder("FINRA Margin Statistics 未返回可用数据")

    latest = records[0]
    balance = latest["balance"]
    market_cap = safe_float(market.get("marketCap"))
    ratio = (balance / market_cap * 100) if balance and market_cap and market_cap > 0 else None
    return {
        "financingBalance": balance,
        "financingToMarketCapPct": round(ratio, 4) if ratio is not None else None,
        "financingToMarketCapBasis": "总市值",
        "financingPercentile": None,
        "financingPercentileSample": 0,
        "financingPercentileSource": "",
        "financingPercentileNote": "暂无同口径历史市值基准",
        "financingSource": "FINRA Margin Statistics",
        "financingSourceUrl": FINRA_MARGIN_STATS_URL,
        "financingDataTimestamp": latest["date"],
    }


def fetch_finra_margin_records_sync(session: requests.Session, timeout: float) -> list[dict[str, Any]]:
    response = session.get(
        FINRA_MARGIN_STATS_XLSX_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=max(timeout, 20),
    )
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml")

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(sheet)
    records: list[dict[str, Any]] = []
    for row in root.findall(".//m:sheetData/m:row", ns):
        values: dict[str, str] = {}
        for cell in row.findall("m:c", ns):
            ref = cell.attrib.get("r", "")
            col_match = re.match(r"[A-Z]+", ref)
            if not col_match:
                continue
            col = col_match.group(0)
            if cell.attrib.get("t") == "inlineStr":
                text_node = cell.find("m:is/m:t", ns)
                values[col] = text_node.text if text_node is not None and text_node.text else ""
            else:
                value_node = cell.find("m:v", ns)
                values[col] = value_node.text if value_node is not None and value_node.text else ""

        date = values.get("A", "")
        debit_millions = safe_float(values.get("B"))
        if not re.match(r"\d{4}-\d{2}", date) or debit_millions is None or debit_millions <= 0:
            continue
        records.append({"date": date, "balance": debit_millions * 1_000_000})

    records.sort(key=lambda item: item["date"], reverse=True)
    return records


def fetch_tradingview_stock_rows(
    session: requests.Session,
    scanner: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], int]:
    columns = [
        "name",
        "description",
        "market_cap_basic",
        "Value.Traded",
        "price_earnings_ttm",
        "close",
        "change",
        "volume",
        "is_primary",
        "subtype",
        "typespecs",
    ]
    base_payload = {
        "columns": columns,
        "filter": [
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "market_cap_basic", "operation": "nempty"},
            {"left": "is_primary", "operation": "equal", "right": True},
        ],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
    }
    rows: list[dict[str, Any]] = []
    total_count = 0
    page_size = 1000
    start = 0

    while True:
        payload = dict(base_payload)
        payload["range"] = [start, start + page_size]
        data = post_tradingview_scan(session, scanner, payload, timeout)
        total_count = int(data.get("totalCount") or total_count or 0)
        page = data.get("data") or []
        if not page:
            break
        for item in page:
            parsed = parse_tradingview_stock_row(item)
            if parsed:
                rows.append(parsed)
        start += page_size
        if start >= total_count:
            break
        time.sleep(random.uniform(0.85, 1.75))

    return rows, total_count


def fetch_hkex_market_highlights_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    today = datetime.now(CN_TZ)
    response = session.get(
        HKEX_MARKET_HIGHLIGHTS_WS_URL,
        params={
            "LangCode": "tc",
            "TDD": str(today.day),
            "TMM": str(today.month),
            "TYYYY": str(today.year),
        },
        headers={
            **hkex_headers(HKEX_STOCK_CONNECT_HIGHLIGHTS_URL),
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") or []
    market_cap_row = find_hkex_highlight_row(rows, "總市值")
    turnover_row = find_hkex_highlight_row(rows, "總成交金額")
    pe_row = find_hkex_highlight_row(rows, "平均市盈率")
    if not market_cap_row:
        raise RuntimeError("HKEX daily market cap row is empty")
    if not turnover_row:
        raise RuntimeError("HKEX daily turnover row is empty")

    main_market_cap = hkex_highlight_money_to_hkd(flat_hkex_cell(market_cap_row, 1, 0), 100_000_000)
    gem_market_cap = hkex_highlight_money_to_hkd(flat_hkex_cell(market_cap_row, 1, 1), 100_000_000)
    main_turnover = hkex_highlight_money_to_hkd(flat_hkex_cell(turnover_row, 1, 0), 1_000_000)
    gem_turnover = hkex_highlight_money_to_hkd(flat_hkex_cell(turnover_row, 1, 1), 1_000_000)
    market_cap = value_or_zero(main_market_cap) + value_or_zero(gem_market_cap)
    turnover = value_or_zero(main_turnover) + value_or_zero(gem_turnover)
    if market_cap <= 0:
        raise RuntimeError("HKEX daily market cap is empty")

    main_pe = safe_float(flat_hkex_cell(pe_row, 1, 0)) if pe_row else None
    gem_pe = safe_float(flat_hkex_cell(pe_row, 1, 1)) if pe_row else None
    pe_value = weighted_pe_from_parts(
        [(main_market_cap, main_pe), (gem_market_cap, gem_pe)]
    )
    date = parse_hkex_highlight_date(payload.get("MaxRefDate") or "")
    return {
        "source": "HKEX Daily Market Highlights",
        "sourceUrl": HKEX_STOCK_CONNECT_HIGHLIGHTS_URL,
        "date": date,
        "marketCap": market_cap,
        "mainBoardMarketCap": main_market_cap,
        "gemMarketCap": gem_market_cap,
        "turnover": turnover or None,
        "mainBoardTurnover": main_turnover,
        "gemTurnover": gem_turnover,
        "pe": pe_value,
        "mainBoardPe": main_pe,
        "gemPe": gem_pe,
        "raw": payload,
    }


def find_hkex_highlight_row(rows: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for row in rows:
        first = flat_hkex_cell(row, 0, 0)
        if label in first:
            return row
    return None


def flat_hkex_cell(row: dict[str, Any], group_index: int, value_index: int = 0) -> str:
    cells = row.get("td") or []
    if group_index >= len(cells) or not isinstance(cells[group_index], list):
        return ""
    group = cells[group_index]
    if value_index >= len(group):
        return ""
    return str(group[value_index] or "").strip()


def hkex_highlight_money_to_hkd(value: Any, multiplier: float) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if text.upper().startswith("HKD"):
        text = text[3:].strip()
    number = safe_float(text)
    return number * multiplier if number is not None else None


def weighted_pe_from_parts(parts: list[tuple[float | None, float | None]]) -> float | None:
    market_cap = 0.0
    earnings = 0.0
    for cap, pe in parts:
        if cap and pe and cap > 0 and 0 < pe < 500:
            market_cap += cap
            earnings += cap / pe
    return market_cap / earnings if earnings > 0 else None


def parse_hkex_highlight_date(value: str) -> str:
    if not value:
        return ""
    for pattern in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def fetch_hkex_market_turnover_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    page_response = session.get(
        HKEX_STOCK_CONNECT_HIGHLIGHTS_URL,
        headers=hkex_headers(HKEX_STOCK_CONNECT_HIGHLIGHTS_URL),
        timeout=max(timeout, 15),
    )
    page_response.raise_for_status()
    token = unquote(extract_hkex_widget_token(page_response.text) or HKEX_WIDGET_FALLBACK_TOKEN)
    response = session.get(
        f"{HKEX_WIDGET_DATA_URL}/getmarketturnover",
        params={
            "lang": "chi",
            "token": token,
            "qid": str(int(time.time() * 1000)),
            "callback": "hkex_cb",
        },
        headers=hkex_headers(HKEX_STOCK_CONNECT_HIGHLIGHTS_URL),
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    payload = parse_callback_jsonp(response.text)
    data = payload.get("data") or {}
    response_code = data.get("responsecode") or data.get("responseCode")
    if response_code not in ("000", 0, None):
        raise RuntimeError(f"HKEX response {response_code}: {data.get('responsemsg') or ''}")
    boardlist = data.get("boardlist") or {}
    main = boardlist.get("main") or {}
    gem = boardlist.get("gem") or {}
    main_turnover = hkex_money_to_hkd(main.get("v"), main.get("u"))
    gem_turnover = hkex_money_to_hkd(gem.get("v"), gem.get("u"))
    turnover = (main_turnover or 0) + (gem_turnover or 0)
    if turnover <= 0:
        raise RuntimeError("HKEX market turnover is empty")
    return {
        "source": "HKEX Market Turnover",
        "sourceUrl": HKEX_STOCK_CONNECT_HIGHLIGHTS_URL,
        "turnover": turnover,
        "mainBoardTurnover": main_turnover,
        "gemTurnover": gem_turnover,
        "updatedAt": parse_hkex_hkt_datetime(data.get("lastupdate") or ""),
        "fairValueUpdatedAt": parse_hkex_hkt_datetime(data.get("FVlastupdate") or ""),
        "date": data.get("date") or "",
        "raw": {"main": main, "gem": gem},
    }


def extract_hkex_widget_token(html: str) -> str:
    block_match = re.search(r"LabCI\.getToken\s*=\s*function\s*\(\)\s*\{(.*?)\};", html, flags=re.S)
    block = block_match.group(1) if block_match else html
    for match in re.finditer(r"^\s*return\s+[\"']([^\"']+)", block, flags=re.M):
        token = match.group(1)
        if token and "Base64" not in token:
            return token
    return ""


def hkex_money_to_hkd(value: Any, unit: Any) -> float | None:
    number = safe_float(str(value).replace(",", "") if value is not None else None)
    if number is None:
        return None
    normalized = str(unit or "").strip().upper()
    multiplier = {
        "T": 1_000_000_000_000,
        "B": 1_000_000_000,
        "M": 1_000_000,
        "K": 1_000,
        "": 1,
    }.get(normalized, 1)
    return number * multiplier


def parse_callback_jsonp(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    match = re.search(r"^[\w$]+\((.*)\)\s*;?\s*$", cleaned, flags=re.S)
    if not match:
        raise ValueError("invalid callback jsonp payload")
    payload = json.loads(match.group(1))
    return payload if isinstance(payload, dict) else {}


def parse_hkex_hkt_datetime(value: str) -> str:
    if not value:
        return ""
    for pattern in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, pattern).replace(tzinfo=CN_TZ)
            return parsed.astimezone(UTC).isoformat()
        except ValueError:
            continue
    return ""


def fetch_a_share_official_market_snapshot_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    sse = fetch_sse_market_snapshot_sync(session, timeout)
    trade_date = sse.get("date") or datetime.now(CN_TZ).date().isoformat()
    szse = fetch_szse_market_snapshot_sync(session, trade_date, timeout)
    market_cap = value_or_zero(sse.get("marketCap")) + value_or_zero(szse.get("marketCap"))
    turnover = value_or_zero(sse.get("turnover")) + value_or_zero(szse.get("turnover"))
    if market_cap <= 0:
        raise RuntimeError("A-share official market cap is empty")
    return {
        "source": "SSE/SZSE official statistics",
        "sourceUrl": f"{SSE_STOCK_STATISTIC_URL} / {SZSE_MARKET_OVERVIEW_URL}",
        "marketCap": market_cap,
        "turnover": turnover or None,
        "date": trade_date,
        "parts": {"sse": sse, "szse": szse},
    }


def fetch_sse_market_snapshot_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    response = session.get(
        SSE_STOCK_STATISTIC_API,
        params={
            "isPagination": "false",
            "sqlId": "COMMON_SSE_SJ_GPSJ_GPSJZM_TJSJ_L",
            "PRODUCT_NAME": "股票,主板,科创板",
            "type": "inParams",
            "TRADE_DATE": "",
        },
        headers={
            **tradingview_headers(),
            "Referer": SSE_STOCK_STATISTIC_URL,
            "Host": "query.sse.com.cn",
        },
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    data = response.json()
    stock_row = next((row for row in data.get("result") or [] if row.get("PRODUCT_NAME") == "股票"), None)
    if not stock_row:
        raise RuntimeError("SSE stock statistics row is empty")
    trade_date = str(stock_row.get("TRADE_DATE") or "")
    date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}" if len(trade_date) == 8 else ""
    return {
        "source": "SSE stock statistics",
        "sourceUrl": SSE_STOCK_STATISTIC_URL,
        "date": date,
        "marketCap": yuan_from_yi(stock_row.get("TOTAL_VALUE")),
        "turnover": yuan_from_yi(stock_row.get("TOTAL_TRADE_AMT")),
        "raw": stock_row,
    }


def fetch_szse_market_snapshot_sync(session: requests.Session, trade_date: str, timeout: float) -> dict[str, Any]:
    response = session.get(
        SZSE_MARKET_OVERVIEW_API,
        params={"SHOWTYPE": "JSON", "CATALOGID": "1803_sczm", "txtQueryDate": trade_date},
        headers={**tradingview_headers(), "Referer": SZSE_MARKET_OVERVIEW_URL},
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    data = response.json()
    first_tab = data[0] if isinstance(data, list) and data else {}
    stock_row = next((row for row in first_tab.get("data") or [] if row.get("lbmc") == "股票"), None)
    if not stock_row:
        raise RuntimeError("SZSE stock statistics row is empty")
    return {
        "source": "SZSE market overview",
        "sourceUrl": SZSE_MARKET_OVERVIEW_URL,
        "date": trade_date,
        "marketCap": yuan_from_yi(stock_row.get("sjzz")),
        "turnover": yuan_from_yi(stock_row.get("cjje")),
        "raw": stock_row,
    }


def fetch_hkex_market_capitalisation_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    index_response = session.get(
        HKEX_MARKET_CAPITALISATION_INDEX_JSON,
        headers=hkex_headers(HKEX_MARKET_CAPITALISATION_URL),
        timeout=max(timeout, 15),
    )
    index_response.raise_for_status()
    archive_items = index_response.json()
    if not isinstance(archive_items, list) or not archive_items:
        raise RuntimeError("HKEX market cap archive index is empty")
    archive_url = archive_items[0].get("url") or ""
    if archive_url.startswith("/"):
        archive_url = f"https://www.hkex.com.hk{archive_url}"
    archive_response = session.get(
        archive_url,
        headers=hkex_headers(HKEX_MARKET_CAPITALISATION_URL),
        timeout=max(timeout, 15),
    )
    archive_response.raise_for_status()
    payload = archive_response.json()
    body = ((payload.get("tables") or [{}])[0].get("body") or [])
    latest_date = ""
    latest_cap = None
    for index in range(0, len(body) - 1, 2):
        date_cell = body[index] or {}
        cap_cell = body[index + 1] or {}
        cap = safe_float(cap_cell.get("text"))
        if date_cell.get("text") and cap:
            latest_date = str(date_cell.get("text")).replace("/", "-")
            latest_cap = cap
    if not latest_cap:
        raise RuntimeError("HKEX market cap archive is empty")
    return {
        "source": "HKEX Market Capitalisation",
        "sourceUrl": HKEX_MARKET_CAPITALISATION_URL,
        "date": latest_date,
        "marketCap": latest_cap,
    }


def fetch_cboe_us_equities_notional_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    try:
        response = session.get(
            CBOE_US_EQUITIES_NOTIONAL_CSV_URL,
            params={"bias": "Notional Value", "auctions": "y"},
            headers={**tradingview_headers(), "Referer": CBOE_US_EQUITIES_MARKET_SHARE_URL},
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        return parse_cboe_us_equities_notional_csv(response.text, live=True)
    except Exception:
        year = datetime.now(CN_TZ).year
        response = session.get(
            CBOE_US_EQUITIES_HISTORY_CSV_URL.format(year=year),
            headers={**tradingview_headers(), "Referer": CBOE_US_EQUITIES_MARKET_SHARE_URL},
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        return parse_cboe_us_equities_notional_csv(response.text, live=False)


def parse_cboe_us_equities_notional_csv(text: str, live: bool) -> dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RuntimeError("Cboe U.S. equities notional CSV is empty")
    day_field = "Date" if "Date" in rows[0] else "Day"
    value_field = "Market" if "Market" in rows[0] else "Total Notional"
    latest_day = max(str(row.get(day_field) or "") for row in rows)
    total = sum(value_or_zero(row.get(value_field)) for row in rows if row.get(day_field) == latest_day)
    if total <= 0:
        raise RuntimeError("Cboe U.S. equities notional total is empty")
    return {
        "source": "Cboe U.S. Equities Market Volume Summary",
        "sourceUrl": CBOE_US_EQUITIES_MARKET_SHARE_URL,
        "date": latest_day,
        "turnover": total,
        "live": live,
    }


def parse_tradingview_stock_row(item: dict[str, Any]) -> dict[str, Any] | None:
    values = item.get("d") or []
    if len(values) < 11:
        return None
    subtype = values[9]
    typespecs = values[10] if isinstance(values[10], list) else []
    if subtype and subtype != "common" and "common" not in typespecs:
        return None
    return {
        "symbol": item.get("s"),
        "code": values[0],
        "name": values[1],
        "marketCap": safe_float(values[2]),
        "turnover": safe_float(values[3]),
        "pe": safe_float(values[4]),
        "close": safe_float(values[5]),
        "changePct": safe_float(values[6]),
        "volume": safe_float(values[7]),
    }


def fetch_market_indices_safe_sync(
    session: requests.Session,
    market_def: dict[str, Any],
    timeout: float,
) -> list[dict[str, Any]]:
    try:
        return fetch_market_indices_sync(session, market_def, timeout)
    except Exception:
        return []


def fetch_market_indices_sync(
    session: requests.Session,
    market_def: dict[str, Any],
    timeout: float,
) -> list[dict[str, Any]]:
    columns = ["name", "description", "close", "change", "volume", "Value.Traded"]
    tickers = [item[0] for item in market_def["indices"]]
    label_map = dict(market_def["indices"])
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": columns,
        "range": [0, len(tickers)],
    }
    try:
        data = post_tradingview_scan(session, market_def["indexMarket"], payload, timeout)
    except Exception:
        return []
    result = []
    for item in data.get("data") or []:
        values = item.get("d") or []
        if len(values) < 4:
            continue
        ticker = item.get("s")
        result.append(
            {
                "symbol": ticker,
                "name": label_map.get(ticker, values[1] or values[0]),
                "close": safe_float(values[2]),
                "changePct": safe_float(values[3]),
                "volume": safe_float(values[4]) if len(values) > 4 else None,
                "turnover": safe_float(values[5]) if len(values) > 5 else None,
            }
        )
    order = {ticker: index for index, ticker in enumerate(tickers)}
    result = sorted(result, key=lambda row: order.get(row.get("symbol", ""), 999))
    for row in result:
        trend, trend_source = fetch_index_trend_sync(session, row.get("symbol", ""), timeout)
        row["trend"] = trend
        row["trendSource"] = trend_source
        if trend:
            row["trendStart"] = trend[0]
            row["trendEnd"] = trend[-1]
        time.sleep(random.uniform(0.15, 0.4))
    return result


def fetch_index_trend_sync(session: requests.Session, ticker: str, timeout: float) -> tuple[list[float], str]:
    kline_def = INDEX_KLINE_DEFS.get(ticker)
    if not kline_def:
        return [], ""

    try:
        provider = kline_def["provider"]
        if provider == "sina_cn":
            rows = fetch_sina_cn_index_kline(session, kline_def["symbol"], timeout)
        elif provider == "sina_us":
            rows = fetch_sina_us_index_kline(session, kline_def["symbol"], timeout)
        elif provider == "tencent_hk":
            rows = fetch_tencent_hk_index_kline(session, kline_def["symbol"], timeout)
        else:
            rows = []
    except Exception:
        return [], ""

    closes = [safe_float(row.get("close")) for row in rows[-60:]]
    trend = [round(value, 3) for value in closes if value is not None and value > 0]
    return (trend, kline_def["source"]) if len(trend) >= 2 else ([], "")


def fetch_sina_cn_index_kline(session: requests.Session, symbol: str, timeout: float) -> list[dict[str, Any]]:
    response = session.get(
        SINA_CN_KLINE_URL,
        params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": "60"},
        headers=sina_headers("https://finance.sina.com.cn/"),
        timeout=max(timeout, 10),
    )
    response.raise_for_status()
    payload = extract_jsonp_payload(response.text)
    rows = json.loads(payload)
    if not isinstance(rows, list):
        return []
    return [
        {
            "date": row.get("day"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def fetch_sina_us_index_kline(session: requests.Session, symbol: str, timeout: float) -> list[dict[str, Any]]:
    response = session.get(
        SINA_US_KLINE_URL,
        params={"symbol": symbol},
        headers=sina_headers("https://finance.sina.com.cn/"),
        timeout=max(timeout, 10),
    )
    response.raise_for_status()
    payload = extract_jsonp_payload(response.text)
    rows = json.loads(payload)
    if not isinstance(rows, list):
        return []
    return [
        {
            "date": row.get("d"),
            "open": row.get("o"),
            "high": row.get("h"),
            "low": row.get("l"),
            "close": row.get("c"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def fetch_tencent_hk_index_kline(session: requests.Session, symbol: str, timeout: float) -> list[dict[str, Any]]:
    response = session.get(
        TENCENT_HK_KLINE_URL,
        params={"param": f"{symbol},day,,,60,qfq"},
        headers=tencent_headers(),
        timeout=max(timeout, 10),
    )
    response.raise_for_status()
    payload = response.json()
    rows = ((payload.get("data") or {}).get(symbol) or {}).get("day") or []
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        parsed.append(
            {
                "date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
            }
        )
    return parsed


def post_tradingview_scan(
    session: requests.Session,
    scanner: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    url = f"{TRADINGVIEW_SCAN}/{scanner}/scan"
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = session.post(url, headers=tradingview_headers(), json=payload, timeout=max(timeout, 12))
            response.raise_for_status()
            return response.json()
        except Exception as error:
            last_error = error
            if attempt == 0:
                time.sleep(1.2 + random.uniform(0.2, 0.8))
    raise RuntimeError(f"TradingView {scanner} scan failed: {last_error!r}")


def tradingview_headers() -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
        "Connection": "close",
    }


def apply_market_history(db_path: Path, markets: list[dict[str, Any]]) -> None:
    ensure_stock_market_history_table(db_path)
    ensure_stock_turnover_history_cache_table(db_path)
    ensure_stock_pe_history_cache_table(db_path)
    today = datetime.now(CN_TZ).date().isoformat()
    with sqlite3.connect(db_path) as conn:
        for market in markets:
            turnover_values, turnover_source, turnover_note = load_market_turnover_history_values(conn, market["id"])
            pe_values, pe_source, pe_note = load_market_pe_history_values(conn, market["id"])
            market["turnoverPercentileSample"] = len(turnover_values)
            market["pePercentileSample"] = len(pe_values)
            market["turnoverPercentile"] = percentile_rank(
                safe_float(market.get("turnoverToMarketCapPct")),
                turnover_values,
            )
            market["turnoverPercentileSource"] = turnover_source
            market["turnoverPercentileNote"] = "" if market["turnoverPercentile"] is not None else turnover_note
            market["pePercentile"] = percentile_rank(safe_float(market.get("pe")), pe_values)
            market["pePercentileSource"] = pe_source
            market["pePercentileNote"] = "" if market["pePercentile"] is not None else pe_note
            conn.execute(
                """
                INSERT INTO stock_market_history
                    (market_id, snapshot_date, captured_at, market_cap, turnover, turnover_ratio, pe)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    snapshot_date = excluded.snapshot_date,
                    captured_at = excluded.captured_at,
                    market_cap = excluded.market_cap,
                    turnover = excluded.turnover,
                    turnover_ratio = excluded.turnover_ratio,
                    pe = excluded.pe
                """,
                (
                    market["id"],
                    today,
                    datetime.now(UTC).isoformat(),
                    market.get("marketCap"),
                    market.get("turnover"),
                    market.get("turnoverToMarketCapPct"),
                    market.get("pe"),
                ),
            )
        prune_stock_market_history(conn)


def load_market_turnover_history_values(conn: sqlite3.Connection, market_id: str) -> tuple[list[float], str, str]:
    if market_id != "a_share":
        return [], "", "暂无可靠历史基准"

    source = "东方财富股票交易统计（月成交额/总市值折算日频）"
    cached = conn.execute(
        """
        SELECT fetched_at, payload_json
        FROM stock_turnover_history_cache
        WHERE market_id = ?
        """,
        (market_id,),
    ).fetchone()
    cached_values: list[float] = []
    if cached:
        cached_values = parse_cached_numeric_values(cached[1])
        fetched_at = parse_dt(cached[0])
        if cached_values and datetime.now(UTC) - fetched_at < timedelta(seconds=TURNOVER_HISTORY_CACHE_TTL_SECONDS):
            return cached_values, source, ""

    try:
        values = fetch_a_share_turnover_history_values()
    except Exception:
        return (cached_values, source, "") if cached_values else ([], "", "暂无可靠历史基准")

    if values:
        conn.execute(
            """
            INSERT INTO stock_turnover_history_cache (market_id, fetched_at, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                payload_json = excluded.payload_json
            """,
            (market_id, datetime.now(UTC).isoformat(), json.dumps(values)),
        )
    return values, source, "" if values else "暂无可靠历史基准"


def load_market_pe_history_values(conn: sqlite3.Connection, market_id: str) -> tuple[list[float], str, str]:
    disabled_note = MARKET_PE_DISABLED_NOTES.get(market_id)
    if disabled_note:
        return [], "", disabled_note

    history_def = MARKET_PE_HISTORY_DEFS.get(market_id)
    if not history_def:
        return [], "", "暂无可靠历史基准"

    cached = conn.execute(
        """
        SELECT fetched_at, payload_json
        FROM stock_pe_history_cache
        WHERE market_id = ?
        """,
        (market_id,),
    ).fetchone()
    cached_values: list[float] = []
    if cached:
        cached_values = parse_cached_pe_values(cached[1])
        fetched_at = parse_dt(cached[0])
        if cached_values and datetime.now(UTC) - fetched_at < timedelta(seconds=PE_HISTORY_CACHE_TTL_SECONDS):
            return cached_values, history_def["source"], ""

    try:
        values = fetch_market_pe_history_values(history_def)
    except Exception:
        return (cached_values, history_def["source"], "") if cached_values else ([], "", "暂无可靠历史基准")

    if values:
        conn.execute(
            """
            INSERT INTO stock_pe_history_cache (market_id, fetched_at, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                payload_json = excluded.payload_json
            """,
            (market_id, datetime.now(UTC).isoformat(), json.dumps(values)),
        )
    return values, history_def["source"], "" if values else "暂无可靠历史基准"


def prune_stock_market_history(conn: sqlite3.Connection) -> None:
    market_ids = [
        row[0]
        for row in conn.execute("SELECT DISTINCT market_id FROM stock_market_history").fetchall()
        if row[0]
    ]
    for market_id in market_ids:
        keep_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT id
                FROM stock_market_history
                WHERE market_id = ?
                ORDER BY snapshot_date DESC, captured_at DESC, id DESC
                LIMIT ?
                """,
                (market_id, STOCK_MARKET_HISTORY_MAX_SNAPSHOTS_PER_MARKET),
            ).fetchall()
        ]
        if not keep_ids:
            continue
        placeholders = ",".join("?" for _ in keep_ids)
        conn.execute(
            f"DELETE FROM stock_market_history WHERE market_id = ? AND id NOT IN ({placeholders})",
            (market_id, *keep_ids),
        )


def fetch_a_share_turnover_history_values() -> list[float]:
    values: list[float] = []
    session = requests.Session()
    try:
        page_number = 1
        pages = 1
        while page_number <= pages and page_number <= 20:
            params = {
                "reportName": "RPT_ECONOMY_STOCK_STATISTICS",
                "columns": "REPORT_DATE,TOTAL_MARKE_SH,DEAL_AMOUNT_SH,TOTAL_MARKE_SZ,DEAL_AMOUNT_SZ",
                "sortColumns": "REPORT_DATE",
                "sortTypes": "-1",
                "pageSize": "200",
                "pageNumber": str(page_number),
                "source": "WEB",
                "client": "WEB",
            }
            response = session.get(
                EASTMONEY_STOCK_STATS_API,
                params=params,
                headers=eastmoney_headers(EASTMONEY_STOCK_STATS_URL),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") or {}
            rows = result.get("data") or []
            try:
                pages = int(result.get("pages") or pages)
            except (TypeError, ValueError):
                pages = page_number

            for row in rows:
                sh_market = safe_float(row.get("TOTAL_MARKE_SH"))
                sz_market = safe_float(row.get("TOTAL_MARKE_SZ"))
                sh_turnover = safe_float(row.get("DEAL_AMOUNT_SH"))
                sz_turnover = safe_float(row.get("DEAL_AMOUNT_SZ"))
                market_cap = (sh_market or 0) + (sz_market or 0)
                turnover = (sh_turnover or 0) + (sz_turnover or 0)
                if market_cap <= 0 or turnover <= 0:
                    continue
                monthly_ratio = turnover / market_cap * 100
                daily_ratio = monthly_ratio / A_SHARE_TURNOVER_MONTHLY_TRADING_DAYS
                if 0 < daily_ratio < 20:
                    values.append(round(daily_ratio, 4))
            page_number += 1
            time.sleep(random.uniform(0.3, 0.8))
    finally:
        session.close()
    return values


def fetch_market_pe_history_values(history_def: dict[str, Any]) -> list[float]:
    page = history_def["page"]
    session = requests.Session()
    try:
        page_response = session.get(page, headers=legulegu_headers(page), timeout=15)
        page_response.raise_for_status()
        csrf_token = extract_csrf_token(page_response.text)
        token = hashlib.md5(datetime.now().date().isoformat().encode("utf-8")).hexdigest()
        headers = legulegu_headers(page)
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token

        if history_def.get("field") == "aggregation_series":
            response = session.post(
                history_def["api"],
                params={"token": token},
                json={
                    "requestedDataKeys": ["sp500Pe", "sp500UsMarketIndex"],
                    "types": ["line", "line"],
                    "requestedDataColors": ["#1f97c4", "#e74c3c", "#3498db", "#2ecc71", "#9b59b6"],
                    "splitLines": [False, True],
                    "inverses": ["false", "false", "false", "false", "false"],
                    "gridIndices": [0, 0, 0, 0, 0],
                    "markLinesOfQuantile": [0, 0, 0, 0, 0],
                    "userAggregationChartId": "630",
                },
                cookies=page_response.cookies,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            series = data.get("series") or []
            values = series[0] if series and isinstance(series[0], list) else []
            return [value for value in (safe_float(item) for item in values) if value is not None and value > 0]

        params = dict(history_def.get("params") or {})
        params["token"] = token
        api_response = session.get(
            history_def["api"],
            params=params,
            cookies=page_response.cookies,
            headers=headers,
            timeout=15,
        )
        api_response.raise_for_status()
        data = api_response.json()
        rows = data.get("data") if isinstance(data, dict) else data
        field = history_def["field"]
        return [value for value in (safe_float(row.get(field)) for row in rows or []) if value is not None and value > 0]
    finally:
        session.close()


def parse_cached_pe_values(payload: str) -> list[float]:
    return parse_cached_numeric_values(payload)


def parse_cached_numeric_values(payload: str) -> list[float]:
    try:
        values = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    return [value for value in (safe_float(item) for item in values) if value is not None and value > 0]


def extract_csrf_token(html: str) -> str:
    match = re.search(r'<meta[^>]+name=["\']_csrf["\'][^>]+content=["\']([^"\']+)', html, flags=re.I)
    return match.group(1) if match else ""


def legulegu_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/html,application/xhtml+xml,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Connection": "close",
    }


def percentile_rank(value: float | None, history: list[float], min_samples: int = 20) -> float | None:
    if value is None or len(history) < min_samples:
        return None
    rank = sum(1 for item in history if item <= value) / len(history) * 100
    return round(rank, 1)


def has_stock_payload(data: dict[str, Any]) -> bool:
    markets = data.get("markets") or []
    if any(market.get("marketCap") or market.get("indices") for market in markets):
        return True
    china_rows = data.get("china", {}).get("inflow", []) or data.get("china", {}).get("industries", [])
    if china_rows:
        return True
    world_rows = data.get("world", {}).get("industries", [])
    return any(row.get("dayPct") is not None or row.get("weekPct") is not None for row in world_rows)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_sqlite_path(config: dict[str, Any]) -> Path:
    configured = config.get("storage", {}).get("sqlite_path", "data/news.sqlite")
    path = Path(configured)
    return path if path.is_absolute() else ROOT_DIR / path


async def load_latest_stocks(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_stocks_sync, db_path)


async def save_latest_stocks(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_stocks_sync, db_path, data)


def load_latest_stocks_sync(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_stocks_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_stocks WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_stocks_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_stocks_table(db_path)
    payload = json.dumps(data, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_stocks WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_stocks (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (data.get("generatedAt", ""), data.get("savedAt", ""), data.get("expiresAt", ""), payload),
        )


def ensure_stocks_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_stocks (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def ensure_stock_market_history_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_market_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                market_cap REAL,
                turnover REAL,
                turnover_ratio REAL,
                pe REAL,
                UNIQUE(market_id, snapshot_date)
            )
            """
        )
        prune_stock_market_history(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_market_history_market_id
            ON stock_market_history (market_id)
            """
        )


def ensure_stock_turnover_history_cache_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_turnover_history_cache (
                market_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def ensure_stock_pe_history_cache_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_pe_history_cache (
                market_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def effective_expires_at(data: dict[str, Any], ttl_seconds: int) -> datetime:
    saved_at = parse_dt(data.get("savedAt", ""))
    expires_at = parse_dt(data.get("expiresAt", ""))
    return max(expires_at, saved_at + timedelta(seconds=ttl_seconds))


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def pct_change(latest: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((latest / previous - 1) * 100, 2)


def scaled(value: Any) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return round(number / 100, 2)


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "-", ""):
            return None
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def yuan_from_yi(value: Any) -> float | None:
    number = safe_float(value)
    return None if number is None else number * 100_000_000


def value_or_zero(value: Any) -> float:
    return safe_float(value) or 0.0


def format_money(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "暂无"
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000_000:
        return f"{sign}{number / 1_000_000_000_000:.2f}万亿"
    if number >= 100_000_000:
        return f"{sign}{number / 100_000_000:.2f}亿"
    if number >= 10_000:
        return f"{sign}{number / 10_000:.2f}万"
    return f"{sign}{number:.0f}"


def format_pct(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "暂无"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"
