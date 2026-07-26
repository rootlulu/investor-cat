from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import random
import re
import sqlite3
import statistics
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urlparse
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
DB_LOCK = asyncio.Lock()
STOCK_CACHE_LOCK = asyncio.Lock()
STOCK_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
INDUSTRY_FINANCING_GROUP_LOCKS: dict[str, asyncio.Lock] = {}
STOCK_SCHEMA_VERSION = 15
CN_TZ = timezone(timedelta(hours=8))
try:
    US_EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    US_EASTERN_TZ = timezone(timedelta(hours=-5))
STOCK_MARKET_HISTORY_MAX_SNAPSHOTS_PER_MARKET = 1
TURNOVER_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60
FINANCING_HISTORY_CACHE_TTL_SECONDS = 24 * 60 * 60
A_SHARE_TURNOVER_MONTHLY_TRADING_DAYS = 21
INSTITUTION_HOLDINGS_SAMPLE_SIZE = 500
ETF_SAMPLE_SIZE = 12
ETF_LIST_PAGE_SIZE = 100
ETF_LIST_MAX_PAGES = 20
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
BROWSER_CLIENT_HINTS = '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"'

EASTMONEY = "https://push2.eastmoney.com"
EASTMONEY_HIS = "https://push2his.eastmoney.com"
EASTMONEY_BKZJ_URL = "https://data.eastmoney.com/bkzj/"
EASTMONEY_STOCK_STATS_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_STOCK_STATS_URL = "https://data.eastmoney.com/cjsj/gpjytj.html"
EASTMONEY_RZRQ_URL = "https://data.eastmoney.com/rzrq/"
EASTMONEY_RZRQ_INDUSTRY_URL = "https://data.eastmoney.com/rzrq/hy.html"
EASTMONEY_BUYBACK_URL = "https://data.eastmoney.com/gphg/"
EASTMONEY_SHAREHOLDER_CHANGE_URL = "https://data.eastmoney.com/executive/gdzjc.html"
EASTMONEY_INSTITUTION_HOLDINGS_URL = "https://data.eastmoney.com/zlsj/jj.html"
EASTMONEY_NATIONAL_TEAM_URL = "https://data.eastmoney.com/gjdcg/"
EASTMONEY_ETF_LIST_API = "https://push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_A_SHARE_LIST_URL = "https://quote.eastmoney.com/center/gridlist.html#hs_a_board"
EASTMONEY_FUND_HOLDINGS_API = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
PRIVATE_FUND_Q1_SOURCE_URL = "https://finance.eastmoney.com/a/202605063728332280.html"
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
SSE_ETF_DETAIL_URL = "https://etf.sse.com.cn/fundlist/funddetail/index.shtml"
SSE_OPTIONS_STATISTICS_URL = "https://www.sse.com.cn/assortment/options/date/"
CHINA_MONEY_REPO_URL = "https://www.chinamoney.com.cn/chinese/bkfrr/"
CHINA_MONEY_REPO_HISTORY_API = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/FrrHis"
CFFEX_DAILY_STATISTICS_URL = "https://www.cffex.com.cn/cn/rtj.html"
CFFEX_DAILY_DATA_BASE = "http://www.cffex.com.cn/sj/hqsj/rtj"
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

INSTITUTION_ORG_TYPES = [
    {"id": "public_fund", "label": "公募基金", "orgType": "01", "note": "季报按重仓披露口径；取披露持仓市值前 500 只股票。"},
    {"id": "social_security", "label": "社保基金", "orgType": "03", "note": "取披露持仓市值前 500 只股票。"},
    {"id": "insurance", "label": "保险资金", "orgType": "05", "note": "取披露持仓市值前 500 只股票。"},
    {"id": "qfii", "label": "QFII", "orgType": "02", "note": "取披露持仓市值前 500 只股票。"},
]

# 东方财富持仓接口返回申万二级行业。统一归并到申万一级，确保各类资金可横向比较。
SW_INDUSTRY_GROUPS = {
    "农林牧渔": ("种植业", "渔业", "林业", "饲料", "农产品加工", "养殖业", "动物保健"),
    "基础化工": ("化学原料", "化学制品", "化学纤维", "农化制品", "塑料", "橡胶", "非金属材料"),
    "钢铁": ("普钢", "特钢", "冶钢原料"),
    "有色金属": ("贵金属", "工业金属", "能源金属", "小金属", "金属新材料"),
    "电子": ("半导体", "元件", "光学光电子", "消费电子", "其他电子", "电子化学品"),
    "家用电器": ("白色家电", "黑色家电", "小家电", "厨卫电器", "照明设备", "家电零部件"),
    "食品饮料": ("白酒", "非白酒", "调味发酵品", "食品加工", "休闲食品", "饮料乳品"),
    "纺织服饰": ("纺织制造", "服装家纺", "饰品"),
    "轻工制造": ("造纸", "包装印刷", "家居用品", "文娱用品", "个护用品"),
    "医药生物": ("化学制药", "生物制品", "中药", "医药商业", "医疗器械", "医疗服务"),
    "公用事业": ("电力", "燃气"),
    "交通运输": ("航空机场", "航运港口", "铁路公路", "物流"),
    "房地产": ("房地产开发", "房地产服务"),
    "商贸零售": ("一般零售", "专业连锁", "互联网电商", "贸易", "旅游零售"),
    "社会服务": ("酒店餐饮", "旅游及景区", "教育", "专业服务"),
    "综合": ("综合",),
    "建筑材料": ("水泥", "玻璃玻纤", "装修建材"),
    "建筑装饰": ("房屋建设", "基础建设", "专业工程", "工程咨询服务", "装修装饰"),
    "电力设备": ("电池", "光伏设备", "风电设备", "电网设备", "电机", "其他电源设备"),
    "国防军工": ("地面兵装", "航海装备", "航空装备", "航天装备", "军工电子"),
    "计算机": ("计算机设备", "软件开发", "IT服务"),
    "传媒": ("出版", "电视广播", "广告营销", "数字媒体", "影视院线", "游戏"),
    "通信": ("通信服务", "通信设备"),
    "银行": ("银行",),
    "非银金融": ("保险", "多元金融", "证券"),
    "汽车": ("乘用车", "商用车", "汽车零部件", "摩托车及其他"),
    "机械设备": ("工程机械", "轨交设备", "环保设备", "通用设备", "专用设备", "自动化设备"),
    "煤炭": ("煤炭开采", "焦炭"),
    "石油石化": ("炼化及贸易", "油服工程", "油气开采"),
    "环保": ("环境治理",),
    "美容护理": ("化妆品", "医疗美容"),
}
SW_INDUSTRY_LOOKUP = {
    child: parent
    for parent, children in SW_INDUSTRY_GROUPS.items()
    for child in children
}

PRIVATE_FUND_Q1_INDUSTRIES_YUAN = {
    "食品饮料": 13_794_093_800,
    "石油石化": 10_695_086_700,
    "计算机": 9_693_395_500,
    "电子": 7_435_218_500,
    "煤炭": 7_289_469_000,
    "通信": 5_467_322_900,
    "机械设备": 2_678_420_600,
    "交通运输": 2_343_438_500,
    "银行": 2_212_084_100,
    "基础化工": 2_183_228_100,
}
PRIVATE_FUND_Q1_TOTAL_YUAN = 78_194_000_000

ETF_EXCLUDED_NAME_PARTS = (
    "货币", "日利", "添益", "黄金", "白银", "债", "纳指", "标普", "恒生", "港股", "中概",
    "香港", "海外", "日经", "德国", "法国", "沙特", "印度", "越南", "商品", "原油", "豆粕",
)

INDUSTRY_FINANCING_WINDOW_YEARS = 3
INDUSTRY_FINANCING_TITLE = "近三年，各行业的融资盘累计净买入"
INDUSTRY_FINANCING_PAGE_SIZE = 500
INDUSTRY_FINANCING_MAX_PAGES = 120
INDUSTRY_FINANCING_DETAIL_MAX_PAGES = 20
INDUSTRY_FINANCING_DETAIL_CACHE_TTL_SECONDS = 24 * 60 * 60
INDUSTRY_FINANCING_NOTE = "每日融资净买入按行业逐日累计，单位为亿元；行业名称按看板口径统一展示。"
INDUSTRY_FINANCING_SERIES = (
    {"id": "agriculture", "code": "433", "name": "农林牧渔", "level": 1},
    {"id": "basic_chemicals", "code": "1206", "name": "基础化工", "level": 1},
    {"id": "steel", "code": "479", "name": "钢铁", "level": 1},
    {"id": "nonferrous_metals", "code": "478", "name": "有色金属", "level": 1},
    {"id": "electronics", "code": "1201", "name": "电子", "level": 1},
    {"id": "home_appliances", "code": "456", "name": "家用电器", "level": 1},
    {"id": "food_beverage", "code": "438", "name": "食品饮料", "level": 1},
    {"id": "textiles", "code": "436", "name": "纺织服饰", "level": 1},
    {"id": "light_manufacturing", "code": "1212", "name": "轻工制造", "level": 1},
    {"id": "medicine", "code": "1216", "name": "医药生物", "level": 1},
    {"id": "utilities", "code": "427", "name": "公用事业", "level": 1},
    {"id": "transportation", "code": "1210", "name": "交通运输", "level": 1},
    {"id": "real_estate", "code": "1202", "name": "房地产", "level": 1},
    {"id": "retail", "code": "1213", "name": "商贸零售", "level": 1},
    {"id": "social_services", "code": "1214", "name": "社会服务", "level": 1},
    {"id": "conglomerates", "code": "1217", "name": "综合", "level": 1},
    {"id": "building_materials", "code": "1208", "name": "建筑材料", "level": 1},
    {"id": "construction", "code": "1209", "name": "建筑装饰", "level": 1},
    {"id": "power_equipment", "code": "1200", "name": "电力设备", "level": 1},
    {"id": "defense", "code": "1204", "name": "国防军工", "level": 1},
    {"id": "computers", "code": "1207", "name": "计算机", "level": 1},
    {"id": "media", "code": "486", "name": "传媒", "level": 1},
    {"id": "communication", "code": "1215", "name": "通信", "level": 1},
    {"id": "banks", "code": "1283", "name": "银行", "level": 1},
    {"id": "non_bank_finance", "code": "1203", "name": "非银金融", "level": 1},
    {"id": "automobiles", "code": "1211", "name": "汽车", "level": 1},
    {"id": "machinery", "code": "1205", "name": "机械设备", "level": 1},
    {"id": "coal", "code": "437", "name": "煤炭", "level": 1},
    {"id": "petrochemicals", "code": "464", "name": "石油石化", "level": 1},
    {"id": "environmental", "code": "728", "name": "环保", "level": 1},
    {"id": "beauty_care", "code": "1035", "name": "美容护理", "level": 1},
)

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
        "universe": "东方财富沪深 A 股行情列表；市值与成交额优先采用交易所官方统计",
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

    previous_industry_financing = (stored or {}).get("industryFinancingTrend")
    try:
        industry_financing_trend = await asyncio.to_thread(
            fetch_industry_financing_trend_sync,
            request_state.timeout,
            previous_industry_financing,
        )
    except Exception as error:
        errors.append(f"行业融资累计净买入：{error}")
        if industry_financing_previous_is_extendable(previous_industry_financing):
            industry_financing_trend = stale_industry_financing_trend(previous_industry_financing, str(error))
        else:
            industry_financing_trend = empty_industry_financing_trend(f"行业融资历史暂未取到：{error}")

    try:
        institution_allocation = await asyncio.to_thread(
            fetch_institution_industry_allocation_sync,
            request_state.timeout,
        )
    except Exception as error:
        errors.append(f"机构行业占比：{error}")
        institution_allocation = empty_institution_industry_allocation(str(error))

    try:
        marginal_signals = await asyncio.to_thread(
            fetch_marginal_signals_sync,
            markets,
            request_state.timeout,
        )
    except Exception as error:
        errors.append(f"A股边际信号：{error}")
        marginal_signals = empty_marginal_signals(str(error))

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
        "source": "TradingView Scanner / SSE与SZSE官方统计 / 东方财富融资融券、行业两融明细、回购及增减持 / 同花顺行业资金流向 / 上交所ETF与期权统计 / 中国货币网回购定盘利率 / CFFEX日统计 / FINRA Margin Statistics / SFC Financial Review / 东方财富机构持仓 / 天天基金 ETF 持仓",
        "cadence": "半小时最多真实抓取一次",
        "errors": errors,
        "markets": markets,
        "industryFinancingTrend": industry_financing_trend,
        "marginalSignals": marginal_signals,
        "institutionIndustryAllocation": institution_allocation,
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


async def get_industry_financing_group(
    parent_industry: str,
    refresh: bool = False,
) -> dict[str, Any]:
    parent_industry = clean_sw_industry_name(parent_industry)
    if parent_industry not in SW_INDUSTRY_GROUPS:
        raise ValueError(f"未知申万一级行业：{parent_industry}")
    lock = INDUSTRY_FINANCING_GROUP_LOCKS.setdefault(parent_industry, asyncio.Lock())
    async with lock:
        config = load_config()
        fetch_config = config.get("fetch", {})
        timeout = float(fetch_config.get("request_timeout_seconds", 8))
        db_path = resolve_sqlite_path(config)
        async with DB_LOCK:
            cached = await asyncio.to_thread(
                load_industry_financing_group_cache_sync,
                db_path,
                parent_industry,
            )
        cached_is_fresh = bool(
            cached
            and parse_dt(str(cached.get("savedAt") or ""))
            + timedelta(seconds=INDUSTRY_FINANCING_DETAIL_CACHE_TTL_SECONDS)
            > datetime.now(UTC)
        )
        if cached_is_fresh and not refresh:
            return {**cached, "cached": True, "stale": False}

        try:
            payload = await asyncio.to_thread(
                fetch_industry_financing_group_sync,
                parent_industry,
                timeout,
                cached,
            )
        except Exception as error:
            if cached and industry_financing_trend_has_data(cached):
                return {
                    **cached,
                    "status": "stale",
                    "cached": True,
                    "stale": True,
                    "note": f"{cached.get('note') or INDUSTRY_FINANCING_NOTE} 本轮刷新失败：{error}",
                }
            raise

        payload["savedAt"] = datetime.now(UTC).isoformat()
        payload["cached"] = False
        payload["stale"] = False
        async with DB_LOCK:
            await asyncio.to_thread(
                save_industry_financing_group_cache_sync,
                db_path,
                parent_industry,
                payload,
            )
        return payload


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
    session = new_browser_session()
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
    session = session or new_browser_session()
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


def industry_financing_window_start(as_of: date | None = None) -> date:
    anchor = as_of or datetime.now(CN_TZ).date()
    target_year = anchor.year - INDUSTRY_FINANCING_WINDOW_YEARS
    try:
        return anchor.replace(year=target_year)
    except ValueError:
        return anchor.replace(year=target_year, day=28)


def empty_industry_financing_trend(
    note: str = "行业融资历史暂未取到。",
    requested_start_date: date | None = None,
) -> dict[str, Any]:
    window_start = requested_start_date or industry_financing_window_start()
    return {
        "status": "unavailable",
        "title": INDUSTRY_FINANCING_TITLE,
        "requestedStartDate": window_start.isoformat(),
        "startDate": "",
        "endDate": "",
        "balanceDate": "",
        "unit": "亿元",
        "source": "东方财富Choice行业融资融券",
        "sourceUrl": EASTMONEY_RZRQ_INDUSTRY_URL,
        "note": note,
        "dates": [],
        "series": [],
        "detailUrlTemplate": "/api/stocks/industry-financing/{industry}",
    }


def industry_financing_trend_has_data(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    dates = value.get("dates")
    series = value.get("series")
    if not isinstance(dates, list) or not dates or not isinstance(series, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("values"), list)
        and any(point is not None for point in item["values"])
        for item in series
    )


def stale_industry_financing_trend(previous: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        **previous,
        "status": "stale",
        "note": f"{INDUSTRY_FINANCING_NOTE} 本轮刷新失败，继续展示上次快照：{error}",
    }


def industry_financing_previous_is_extendable(
    previous: Any,
    requested_start_date: date | None = None,
    series_definitions: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> bool:
    if not industry_financing_trend_has_data(previous):
        return False

    window_start = requested_start_date or industry_financing_window_start()
    try:
        previous_start = date.fromisoformat(str(previous.get("requestedStartDate") or ""))
    except ValueError:
        return False
    if previous_start > window_start:
        return False

    dates = previous.get("dates") or []
    try:
        parsed_dates = [date.fromisoformat(str(item)) for item in dates]
    except (TypeError, ValueError):
        return False
    if parsed_dates != sorted(set(parsed_dates)):
        return False
    if parsed_dates[-1] < window_start:
        return False

    definitions = series_definitions if series_definitions is not None else INDUSTRY_FINANCING_SERIES
    expected_codes = {item["code"] for item in definitions}
    previous_series = previous.get("series") or []
    series_by_code = {
        str(item.get("code")): item
        for item in previous_series
        if isinstance(item, dict) and item.get("code") is not None
    }
    if set(series_by_code) != expected_codes:
        return False
    return all(
        isinstance(series_by_code[code].get("values"), list)
        and len(series_by_code[code]["values"]) == len(dates)
        for code in expected_codes
    )


def industry_financing_query_start(
    previous: Any,
    requested_start_date: date | None = None,
    series_definitions: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> date:
    window_start = requested_start_date or industry_financing_window_start()
    if not industry_financing_previous_is_extendable(previous, window_start, series_definitions):
        return window_start
    return date.fromisoformat(previous["dates"][-1])


def fetch_industry_financing_rows_sync(
    session: requests.Session,
    series_definitions: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    query_start: date,
    timeout: float,
    max_pages: int,
) -> list[dict[str, Any]]:
    codes = ",".join(f'"{item["code"]}"' for item in series_definitions)
    if not codes:
        return []
    filter_expression = f"(BOARD_CODE in ({codes}))(TRADE_DATE>='{query_start.isoformat()}')"
    rows: list[dict[str, Any]] = []
    page_number = 1
    pages = 1
    while page_number <= pages:
        params = {
            "reportName": "RPTA_WEB_BKJYMX",
            "columns": "BOARD_CODE,BOARD_NAME,TRADE_DATE,FIN_NETBUY_AMT,FIN_BALANCE",
            "source": "WEB",
            "pageNumber": str(page_number),
            "pageSize": str(INDUSTRY_FINANCING_PAGE_SIZE),
            "sortColumns": "TRADE_DATE,BOARD_CODE",
            "sortTypes": "1,1",
            "filter": filter_expression,
        }
        response = session.get(
            EASTMONEY_STOCK_STATS_API,
            params=params,
            headers=eastmoney_headers(EASTMONEY_RZRQ_INDUSTRY_URL),
            timeout=max(timeout, 20),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(payload.get("message") or "东方财富行业融资接口返回失败")
        result = payload.get("result") or {}
        rows.extend(result.get("data") or [])
        if page_number == 1:
            try:
                pages = max(1, int(result.get("pages") or 1))
            except (TypeError, ValueError) as error:
                raise RuntimeError("东方财富行业融资接口分页信息无效") from error
            if pages > max_pages:
                raise RuntimeError(f"东方财富行业融资历史分页异常：{pages} 页")
        page_number += 1
    return rows


def fetch_industry_financing_trend_sync(
    timeout: float,
    previous: dict[str, Any] | None = None,
    session: requests.Session | None = None,
    requested_start_date: date | None = None,
) -> dict[str, Any]:
    window_start = requested_start_date or industry_financing_window_start()
    previous_for_merge = (
        previous
        if industry_financing_previous_is_extendable(previous, window_start, INDUSTRY_FINANCING_SERIES)
        else None
    )
    query_start = industry_financing_query_start(previous_for_merge, window_start)
    own_session = session is None
    session = session or requests.Session()

    try:
        rows = fetch_industry_financing_rows_sync(
            session,
            INDUSTRY_FINANCING_SERIES,
            query_start,
            timeout,
            INDUSTRY_FINANCING_MAX_PAGES,
        )
    finally:
        if own_session:
            session.close()

    if not rows:
        raise RuntimeError("东方财富行业融资接口未返回可用历史")
    return build_industry_financing_trend(rows, previous_for_merge, window_start)


def build_industry_financing_trend(
    rows: list[dict[str, Any]],
    previous: dict[str, Any] | None = None,
    requested_start_date: date | None = None,
    series_definitions: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
    *,
    title: str = INDUSTRY_FINANCING_TITLE,
    note: str = INDUSTRY_FINANCING_NOTE,
    parent_industry: str = "",
) -> dict[str, Any]:
    definitions = tuple(series_definitions) if series_definitions is not None else INDUSTRY_FINANCING_SERIES
    window_start = requested_start_date or industry_financing_window_start()
    previous_for_merge = (
        previous
        if industry_financing_previous_is_extendable(previous, window_start, definitions)
        else None
    )
    query_start = industry_financing_query_start(previous_for_merge, window_start, definitions)
    expected_codes = {item["code"] for item in definitions}
    daily_by_code: dict[str, dict[str, float]] = {code: {} for code in expected_codes}
    balances_by_code: dict[str, dict[str, float]] = {code: {} for code in expected_codes}
    source_names: dict[str, str] = {}

    for row in rows:
        code = str(row.get("BOARD_CODE") or "")
        if code not in expected_codes:
            continue
        date_text = str(row.get("TRADE_DATE") or "").split(" ")[0]
        try:
            trade_date = date.fromisoformat(date_text)
        except ValueError:
            continue
        if trade_date < query_start:
            continue
        amount = safe_float(row.get("FIN_NETBUY_AMT"))
        balance = safe_float(row.get("FIN_BALANCE"))
        if amount is not None:
            daily_by_code[code][date_text] = amount
        if balance is not None:
            balances_by_code[code][date_text] = balance
        source_names[code] = str(row.get("BOARD_NAME") or source_names.get(code) or "")

    new_dates = sorted({date_text for values in daily_by_code.values() for date_text in values})
    if not new_dates:
        raise RuntimeError("东方财富行业融资历史缺少有效日期或净买入数据")

    prefix_dates: list[str] = []
    prefix_start = 0
    prefix_end = 0
    previous_series_by_code: dict[str, dict[str, Any]] = {}
    if previous_for_merge:
        previous_dates = previous_for_merge["dates"]
        prefix_start = sum(1 for item in previous_dates if item < window_start.isoformat())
        prefix_end = sum(1 for item in previous_dates if item < query_start.isoformat())
        prefix_dates = previous_dates[prefix_start:prefix_end]
        previous_series_by_code = {str(item["code"]): item for item in previous_for_merge["series"]}

    dates = [*prefix_dates, *new_dates]
    series: list[dict[str, Any]] = []
    balance_dates: list[str] = []
    for definition in definitions:
        code = definition["code"]
        previous_series = previous_series_by_code.get(code, {})
        previous_values = previous_series.get("values") or []
        values: list[float | None] = []
        baseline = next(
            (number for number in reversed([safe_float(point) for point in previous_values[:prefix_start]]) if number is not None),
            0.0,
        )
        for point in previous_values[prefix_start:prefix_end]:
            number = safe_float(point)
            values.append(round(number - baseline, 2) if number is not None else None)

        running = next((point for point in reversed(values) if point is not None), None)
        for date_text in new_dates:
            amount = daily_by_code[code].get(date_text)
            if amount is not None:
                running = (running or 0.0) + amount / 100_000_000
            values.append(round(running, 2) if running is not None else None)

        latest = next((point for point in reversed(values) if point is not None), None)
        latest_balance = safe_float(previous_series.get("latestBalance"))
        latest_balance_date = str(previous_series.get("latestBalanceDate") or "")
        for balance_date in sorted(balances_by_code[code]):
            latest_balance = balances_by_code[code][balance_date] / 100_000_000
            latest_balance_date = balance_date
        if latest_balance_date:
            balance_dates.append(latest_balance_date)
        series.append(
            {
                **definition,
                "sourceName": (
                    source_names.get(code)
                    or previous_series_by_code.get(code, {}).get("sourceName")
                    or definition["name"]
                ),
                "latest": latest,
                "latestBalance": round(latest_balance, 2) if latest_balance is not None else None,
                "latestBalanceDate": latest_balance_date,
                "values": values,
            }
        )

    return {
        "status": "ok",
        "title": title,
        "parentIndustry": parent_industry,
        "requestedStartDate": window_start.isoformat(),
        "startDate": dates[0],
        "endDate": dates[-1],
        "balanceDate": max(balance_dates) if balance_dates else "",
        "unit": "亿元",
        "source": "东方财富Choice行业融资融券",
        "sourceUrl": EASTMONEY_RZRQ_INDUSTRY_URL,
        "note": note,
        "dates": dates,
        "series": series,
        "detailUrlTemplate": "/api/stocks/industry-financing/{industry}",
    }


def fetch_latest_industry_financing_rows_sync(
    session: requests.Session,
    timeout: float,
) -> tuple[str, list[dict[str, Any]]]:
    latest_response = session.get(
        EASTMONEY_STOCK_STATS_API,
        params={
            "reportName": "RPTA_WEB_BKJYMX",
            "columns": "BOARD_CODE,BOARD_NAME,BOARD_TYPE_CODE,TRADE_DATE",
            "source": "WEB",
            "pageNumber": "1",
            "pageSize": "1",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
        },
        headers=eastmoney_headers(EASTMONEY_RZRQ_INDUSTRY_URL),
        timeout=max(timeout, 20),
    )
    latest_response.raise_for_status()
    latest_payload = latest_response.json()
    latest_rows = (latest_payload.get("result") or {}).get("data") or []
    latest_date = str((latest_rows[0] if latest_rows else {}).get("TRADE_DATE") or "").split(" ")[0]
    if not latest_payload.get("success") or not latest_date:
        raise RuntimeError("东方财富行业融资接口缺少最新交易日")

    filter_expression = f"(TRADE_DATE='{latest_date}')"
    rows: list[dict[str, Any]] = []
    page_number = 1
    pages = 1
    while page_number <= pages:
        response = session.get(
            EASTMONEY_STOCK_STATS_API,
            params={
                "reportName": "RPTA_WEB_BKJYMX",
                "columns": "BOARD_CODE,BOARD_NAME,BOARD_TYPE_CODE,TRADE_DATE,FIN_NETBUY_AMT,FIN_BALANCE",
                "source": "WEB",
                "pageNumber": str(page_number),
                "pageSize": str(INDUSTRY_FINANCING_PAGE_SIZE),
                "sortColumns": "BOARD_CODE",
                "sortTypes": "1",
                "filter": filter_expression,
            },
            headers=eastmoney_headers(EASTMONEY_RZRQ_INDUSTRY_URL),
            timeout=max(timeout, 20),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(payload.get("message") or "东方财富行业融资接口返回失败")
        result = payload.get("result") or {}
        rows.extend(result.get("data") or [])
        if page_number == 1:
            pages = max(1, int(result.get("pages") or 1))
            if pages > 3:
                raise RuntimeError(f"东方财富行业融资当日板块数量异常：{pages} 页")
        page_number += 1
    return latest_date, rows


def discover_industry_financing_group_definitions(
    parent_industry: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_children = SW_INDUSTRY_GROUPS.get(parent_industry)
    if not expected_children:
        return []
    candidates: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in rows:
        raw_name = str(row.get("BOARD_NAME") or "").strip()
        if re.search(r"(?:Ⅲ|III)$", raw_name):
            continue
        clean_name = clean_sw_industry_name(raw_name)
        if clean_name not in expected_children:
            continue
        code = str(row.get("BOARD_CODE") or "")
        if not code:
            continue
        score = 2 if re.search(r"(?:Ⅱ|II)$", raw_name) else 1
        definition = {
            "id": f"{parent_industry}/{clean_name}",
            "code": code,
            "name": clean_name,
            "parent": parent_industry,
            "level": 2,
        }
        if clean_name not in candidates or score > candidates[clean_name][0]:
            candidates[clean_name] = (score, definition)
    return [candidates[name][1] for name in expected_children if name in candidates]


def fetch_industry_financing_group_sync(
    parent_industry: str,
    timeout: float,
    previous: dict[str, Any] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if parent_industry not in SW_INDUSTRY_GROUPS:
        raise ValueError(f"未知申万一级行业：{parent_industry}")
    own_session = session is None
    session = session or new_browser_session()
    window_start = industry_financing_window_start()
    try:
        latest_date, latest_rows = fetch_latest_industry_financing_rows_sync(session, timeout)
        definitions = discover_industry_financing_group_definitions(parent_industry, latest_rows)
        if not definitions:
            raise RuntimeError(f"{parent_industry}二级行业融资代码未取到")
        previous_for_merge = (
            previous
            if industry_financing_previous_is_extendable(previous, window_start, definitions)
            else None
        )
        query_start = industry_financing_query_start(previous_for_merge, window_start, definitions)
        rows = fetch_industry_financing_rows_sync(
            session,
            definitions,
            query_start,
            timeout,
            INDUSTRY_FINANCING_DETAIL_MAX_PAGES,
        )
    finally:
        if own_session:
            session.close()
    if not rows:
        raise RuntimeError(f"{parent_industry}二级行业融资历史未返回")
    payload = build_industry_financing_trend(
        rows,
        previous_for_merge,
        window_start,
        definitions,
        title=f"近三年，{parent_industry}二级行业融资盘累计净买入",
        note=f"{INDUSTRY_FINANCING_NOTE} 二级行业按申万一级“{parent_industry}”分组。",
        parent_industry=parent_industry,
    )
    payload["discoveredAt"] = latest_date
    payload["allChildren"] = list(SW_INDUSTRY_GROUPS[parent_industry])
    available = {item["name"] for item in definitions}
    payload["unavailableChildren"] = [
        child for child in SW_INDUSTRY_GROUPS[parent_industry] if child not in available
    ]
    return payload


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
    parsed_referer = urlparse(referer)
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Origin": f"{parsed_referer.scheme}://{parsed_referer.netloc}",
        "Sec-CH-UA": BROWSER_CLIENT_HINTS,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }


def ths_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
    }


def sina_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
    }


def tencent_headers() -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://gu.qq.com/",
    }


def hkex_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/javascript,application/json,text/javascript,*/*;q=0.8",
        "Accept-Language": "zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
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
    # A real browser keeps one fingerprint for the lifetime of a session. Rotating the
    # User-Agent on every request is both less realistic and more likely to trigger WAFs.
    return BROWSER_USER_AGENT


def new_browser_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-CH-UA": BROWSER_CLIENT_HINTS,
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        }
    )
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def warm_browser_session(session: requests.Session, landing_url: str, timeout: float) -> None:
    host = urlparse(landing_url).netloc.lower()
    warmed_hosts = getattr(session, "_browser_warmed_hosts", set())
    if host in warmed_hosts:
        return
    try:
        response = session.get(
            landing_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": f"{urlparse(landing_url).scheme}://{host}/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=min(max(timeout, 8), 15),
        )
        try:
            if response.status_code >= 500:
                response.raise_for_status()
        finally:
            response.close()
    except requests.RequestException:
        # Cookie warming is best effort. The data request remains authoritative and
        # reports its own failure instead of pretending that the warm-up succeeded.
        pass
    warmed_hosts.add(host)
    setattr(session, "_browser_warmed_hosts", warmed_hosts)
    time.sleep(random.uniform(0.15, 0.45))


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


def latest_completed_disclosure_period(reference_date: date | None = None) -> date:
    reference_date = reference_date or datetime.now(CN_TZ).date()
    candidates: list[tuple[date, date]] = []
    for year in range(reference_date.year - 2, reference_date.year + 1):
        candidates.extend(
            [
                (date(year, 3, 31), date(year, 4, 30)),
                (date(year, 6, 30), date(year, 8, 31)),
                (date(year, 9, 30), date(year, 10, 31)),
                (date(year, 12, 31), date(year + 1, 4, 30)),
            ]
        )
    available = [period for period, disclosure_deadline in candidates if disclosure_deadline <= reference_date]
    return max(available)


def clean_sw_industry_name(value: Any) -> str:
    industry = str(value or "").strip()
    return re.sub(r"(?:Ⅰ|Ⅱ|Ⅲ|III|II|IV|I)+$", "", industry).strip()


def split_sw_industry(value: Any) -> tuple[str, str | None]:
    industry = clean_sw_industry_name(value)
    if not industry:
        return "未分类", None
    parent = SW_INDUSTRY_LOOKUP.get(industry)
    if parent:
        return parent, industry
    if industry in SW_INDUSTRY_GROUPS:
        return industry, None
    return industry, None


def normalize_sw_industry(value: Any) -> str:
    return split_sw_industry(value)[0]


def empty_institution_industry_allocation(error: str = "") -> dict[str, Any]:
    report_date = latest_completed_disclosure_period().isoformat()
    return {
        "reportDate": report_date,
        "generatedAt": datetime.now(UTC).isoformat(),
        "basis": "各类资金已披露持仓市值内的申万一级/二级行业占比",
        "categories": [],
        "industries": [],
        "industryGroups": [],
        "notes": [
            "占比的分母是该类资金当前展示样本的已披露持仓市值，不是行业总市值或流通市值。",
            "不同资金类别可能重叠，例如 ETF 也属于公募基金，不能横向相加。",
        ],
        "errors": [error] if error else [],
    }


def fetch_institution_industry_allocation_sync(timeout: float) -> dict[str, Any]:
    report_date = latest_completed_disclosure_period().isoformat()
    categories: list[dict[str, Any]] = []
    errors: list[str] = []
    session = new_browser_session()
    try:
        for category_def in INSTITUTION_ORG_TYPES:
            try:
                categories.append(fetch_org_holding_category_sync(session, category_def, report_date, timeout))
            except Exception as error:
                errors.append(f"{category_def['label']}：{error}")

        categories.append(private_fund_category())

        try:
            categories.append(fetch_national_team_category_sync(session, report_date, timeout))
        except Exception as error:
            errors.append(f"国家队：{error}")

        try:
            categories.append(fetch_etf_category_sync(session, report_date, timeout))
        except Exception as error:
            errors.append(f"股票 ETF 样本：{error}")
    finally:
        session.close()

    return build_institution_industry_payload(report_date, categories, errors)


def fetch_org_holding_category_sync(
    session: requests.Session,
    category_def: dict[str, str],
    report_date: str,
    timeout: float,
) -> dict[str, Any]:
    params = {
        "reportName": "RPT_MAIN_ORGHOLD",
        "columns": "ALL",
        "sortColumns": "HOLD_VALUE",
        "sortTypes": "-1",
        "pageNumber": "1",
        "pageSize": str(INSTITUTION_HOLDINGS_SAMPLE_SIZE),
        "source": "WEB",
        "client": "WEB",
        "filter": f"(REPORT_DATE='{report_date}')(ORG_TYPE=\"{category_def['orgType']}\")",
        "quoteColumns": "f100~01~SECURITY_CODE~INDUSTRY",
    }
    result = fetch_eastmoney_datacenter_result(
        session,
        params,
        EASTMONEY_INSTITUTION_HOLDINGS_URL,
        timeout,
    )
    rows = result.get("data") or []
    values, level_two_values = aggregate_industry_hierarchy(rows, "HOLD_VALUE")
    if not values:
        raise RuntimeError("接口未返回可聚合的行业持仓")
    total_count = int(result.get("count") or len(rows))
    return institution_category(
        category_id=category_def["id"],
        label=category_def["label"],
        report_date=report_date,
        values=values,
        sample_count=len(rows),
        total_count=total_count,
        source="东方财富机构持仓",
        source_url=EASTMONEY_INSTITUTION_HOLDINGS_URL,
        note=category_def["note"],
        coverage_label="披露股票数量覆盖",
        coverage_pct=len(rows) / total_count * 100 if total_count else None,
        level_two_values=level_two_values,
    )


def fetch_national_team_category_sync(
    session: requests.Session,
    report_date: str,
    timeout: float,
) -> dict[str, Any]:
    params = {
        "reportName": "RPT_NATIONAL_STATISTICS",
        "columns": "ALL",
        "sortColumns": "MARKET_CAP_SUM",
        "sortTypes": "-1",
        "pageNumber": "1",
        "pageSize": str(INSTITUTION_HOLDINGS_SAMPLE_SIZE),
        "source": "WEB",
        "client": "WEB",
        "filter": f"(REPORT_DATE='{report_date}')",
        "quoteColumns": "f100~01~SECURITY_CODE~INDUSTRY",
    }
    result = fetch_eastmoney_datacenter_result(session, params, EASTMONEY_NATIONAL_TEAM_URL, timeout)
    rows = result.get("data") or []
    values, level_two_values = aggregate_industry_hierarchy(rows, "MARKET_CAP_SUM")
    if not values:
        raise RuntimeError("接口未返回可聚合的行业持仓")
    total_count = int(result.get("count") or len(rows))
    return institution_category(
        category_id="national_team",
        label="国家队",
        report_date=report_date,
        values=values,
        sample_count=len(rows),
        total_count=total_count,
        source="东方财富国家队持股",
        source_url=EASTMONEY_NATIONAL_TEAM_URL,
        note="国家队机构披露持仓按股票汇总；取持仓市值前 500 只股票。",
        coverage_label="披露股票数量覆盖",
        coverage_pct=len(rows) / total_count * 100 if total_count else None,
        level_two_values=level_two_values,
    )


def private_fund_category() -> dict[str, Any]:
    values = dict(PRIVATE_FUND_Q1_INDUSTRIES_YUAN)
    disclosed_top_total = sum(values.values())
    values["其他20个行业"] = max(PRIVATE_FUND_Q1_TOTAL_YUAN - disclosed_top_total, 0)
    return institution_category(
        category_id="private_fund",
        label="百亿私募",
        report_date="2026-03-31",
        values=values,
        sample_count=203,
        total_count=203,
        source="私募排排网公开统计（东方财富转载）",
        source_url=PRIVATE_FUND_Q1_SOURCE_URL,
        note="47 家百亿私募进入 203 家公司前十大流通股东的公开样本；原文仅公开行业前十，其余 20 个行业合并展示。",
        coverage_label="公开样本股票",
        coverage_pct=None,
    )


def fetch_etf_category_sync(
    session: requests.Session,
    report_date: str,
    timeout: float,
) -> dict[str, Any]:
    rows = fetch_etf_universe_rows_sync(session, timeout)
    eligible = [row for row in rows if is_domestic_equity_etf(row)]
    eligible.sort(key=lambda row: value_or_zero(row.get("f20")), reverse=True)
    selected = eligible[:ETF_SAMPLE_SIZE]
    if not selected:
        raise RuntimeError("ETF 列表未返回境内股票 ETF")

    holdings_by_code: dict[str, float] = {}
    successful: list[dict[str, Any]] = []
    failed_names: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_one_etf_holdings_sync, row, report_date, timeout): row
            for row in selected
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                holdings = future.result()
            except Exception:
                failed_names.append(str(row.get("f14") or row.get("f12") or "未知 ETF"))
                continue
            if not holdings:
                failed_names.append(str(row.get("f14") or row.get("f12") or "未知 ETF"))
                continue
            successful.append(row)
            for holding in holdings:
                code = holding["code"]
                holdings_by_code[code] = holdings_by_code.get(code, 0.0) + holding["marketValue"]

    if not holdings_by_code:
        raise RuntimeError("选取的 ETF 未返回目标报告期持仓")
    successful.sort(key=lambda row: value_or_zero(row.get("f20")), reverse=True)
    failed_names.sort()
    industry_map = fetch_stock_industry_map_sync(session, set(holdings_by_code), timeout)
    values: dict[str, float] = {}
    level_two_values: dict[str, dict[str, float]] = {}
    for code, market_value in holdings_by_code.items():
        parent, child = split_sw_industry(industry_map.get(code))
        values[parent] = values.get(parent, 0.0) + market_value
        if child:
            child_values = level_two_values.setdefault(parent, {})
            child_values[child] = child_values.get(child, 0.0) + market_value

    eligible_cap = sum(value_or_zero(row.get("f20")) for row in eligible)
    selected_cap = sum(value_or_zero(row.get("f20")) for row in successful)
    selected_names = "、".join(str(row.get("f14") or row.get("f12")) for row in successful)
    failure_note = f"；{len(failed_names)} 只未取得目标季报" if failed_names else ""
    return institution_category(
        category_id="etf",
        label="股票 ETF",
        report_date=report_date,
        values=values,
        sample_count=len(successful),
        total_count=len(eligible),
        source="东方财富 ETF 行情 / 天天基金持仓明细",
        source_url="https://fund.eastmoney.com/data/fundranking.html#tETF",
        note=f"按当前规模选取头部 {ETF_SAMPLE_SIZE} 只境内股票 ETF，并聚合目标报告期全部披露股票持仓；样本：{selected_names}{failure_note}。",
        coverage_label="样本 ETF 当前规模覆盖",
        coverage_pct=selected_cap / eligible_cap * 100 if eligible_cap else None,
        level_two_values=level_two_values,
    )


def fetch_etf_universe_rows_sync(session: requests.Session, timeout: float) -> list[dict[str, Any]]:
    warm_browser_session(session, "https://quote.eastmoney.com/center/gridlist.html#fund_etf", timeout)
    base_params = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f20",
        "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
        "fields": "f12,f14,f20,f38",
    }
    rows: list[dict[str, Any]] = []
    total = 0
    page = 1
    while page <= ETF_LIST_MAX_PAGES and (page == 1 or len(rows) < total):
        response = session.get(
            EASTMONEY_ETF_LIST_API,
            params={**base_params, "pn": str(page), "pz": str(ETF_LIST_PAGE_SIZE)},
            headers=eastmoney_headers("https://quote.eastmoney.com/center/gridlist.html#fund_etf"),
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        page_rows = data.get("diff") or []
        if isinstance(page_rows, dict):
            page_rows = list(page_rows.values())
        if not page_rows:
            break
        rows.extend(page_rows)
        total = int(data.get("total") or len(rows))
        page += 1
        time.sleep(0.05)
    return rows


def fetch_one_etf_holdings_sync(
    etf: dict[str, Any],
    report_date: str,
    timeout: float,
) -> list[dict[str, Any]]:
    code = str(etf.get("f12") or "")
    if not code:
        return []
    with new_browser_session() as session:
        landing_url = f"https://fundf10.eastmoney.com/ccmx_{code}.html"
        warm_browser_session(session, landing_url, timeout)
        response = session.get(
            EASTMONEY_FUND_HOLDINGS_API,
            params={
                "type": "jjcc",
                "code": code,
                "topline": "10000",
                "year": report_date[:4],
                "month": str(int(report_date[5:7])),
                "rt": f"{random.random():.12f}",
            },
            headers={
                **eastmoney_headers(landing_url),
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return parse_etf_holdings_page(response.text, report_date)


def parse_etf_holdings_page(text: str, report_date: str) -> list[dict[str, Any]]:
    date_match = re.search(
        rf"截止至：\s*<font[^>]*>\s*{re.escape(report_date)}\s*</font>",
        text,
        re.I,
    )
    if not date_match:
        return []
    box_pattern = re.compile(r"<div\s+class=['\"]box['\"]", re.I)
    starts = [match.start() for match in box_pattern.finditer(text, 0, date_match.start())]
    section_start = starts[-1] if starts else 0
    next_box = box_pattern.search(text, date_match.end())
    section_end = next_box.start() if next_box else len(text)
    parser = HoldingsTableParser()
    parser.feed(text[section_start:section_end])

    holdings: list[dict[str, Any]] = []
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        code = cells[1].strip()
        market_value_wan = safe_float(cells[-1])
        if not re.fullmatch(r"\d{6}", code) or market_value_wan is None or market_value_wan <= 0:
            continue
        holdings.append({"code": code, "marketValue": market_value_wan * 10_000})
    return holdings


class HoldingsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None


def fetch_stock_industry_map_sync(
    session: requests.Session,
    codes: set[str],
    timeout: float,
) -> dict[str, str]:
    industry_map: dict[str, str] = {}
    ordered_codes = sorted(code for code in codes if re.fullmatch(r"\d{6}", code))
    for offset in range(0, len(ordered_codes), 60):
        chunk = ordered_codes[offset : offset + 60]
        secids = ",".join(f"{'1' if code.startswith(('5', '6', '9')) else '0'}.{code}" for code in chunk)
        response = session.get(
            f"{EASTMONEY}/api/qt/ulist.np/get",
            params={
                "fltt": "2",
                "secids": secids,
                "fields": "f12,f14,f100",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            },
            headers=eastmoney_headers("https://quote.eastmoney.com/"),
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        rows = (response.json().get("data") or {}).get("diff") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        for row in rows:
            code = str(row.get("f12") or "")
            industry = str(row.get("f100") or "").strip()
            if code and industry:
                industry_map[code] = industry
    return industry_map


def is_domestic_equity_etf(row: dict[str, Any]) -> bool:
    name = str(row.get("f14") or "")
    market_cap = value_or_zero(row.get("f20"))
    return bool(name and market_cap > 0 and not any(part in name for part in ETF_EXCLUDED_NAME_PARTS))


def fetch_eastmoney_datacenter_result(
    session: requests.Session,
    params: dict[str, str],
    referer: str,
    timeout: float,
) -> dict[str, Any]:
    warm_browser_session(session, referer, timeout)
    response = session.get(
        EASTMONEY_STOCK_STATS_API,
        params=params,
        headers=eastmoney_headers(referer),
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not payload.get("result"):
        raise RuntimeError(str(payload.get("message") or "东方财富数据中心未返回结果"))
    return payload["result"]


def aggregate_industry_hierarchy(
    rows: list[dict[str, Any]],
    value_field: str,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    values: dict[str, float] = {}
    level_two_values: dict[str, dict[str, float]] = {}
    for row in rows:
        market_value = safe_float(row.get(value_field))
        if market_value is None or market_value <= 0:
            continue
        parent, child = split_sw_industry(row.get("INDUSTRY"))
        values[parent] = values.get(parent, 0.0) + market_value
        if child:
            child_values = level_two_values.setdefault(parent, {})
            child_values[child] = child_values.get(child, 0.0) + market_value
    return values, level_two_values


def aggregate_industry_values(rows: list[dict[str, Any]], value_field: str) -> dict[str, float]:
    return aggregate_industry_hierarchy(rows, value_field)[0]


def institution_category(
    *,
    category_id: str,
    label: str,
    report_date: str,
    values: dict[str, float],
    sample_count: int,
    total_count: int,
    source: str,
    source_url: str,
    note: str,
    coverage_label: str,
    coverage_pct: float | None,
    level_two_values: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    clean_values = {
        industry: value
        for industry, value in values.items()
        if value > 0
    }
    return {
        "id": category_id,
        "label": label,
        "reportDate": report_date,
        "sampleCount": sample_count,
        "totalCount": total_count,
        "totalMarketValue": round(sum(clean_values.values()), 2),
        "source": source,
        "sourceUrl": source_url,
        "note": note,
        "coverageLabel": coverage_label,
        "coveragePct": round(coverage_pct, 2) if coverage_pct is not None else None,
        "hasLevel2Data": level_two_values is not None,
        "_industryValues": clean_values,
        "_industryLevel2Values": {
            parent: {
                industry: value
                for industry, value in children.items()
                if value > 0
            }
            for parent, children in (level_two_values or {}).items()
        },
    }


def build_institution_industry_payload(
    report_date: str,
    categories: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    category_order = {
        "public_fund": 0,
        "private_fund": 1,
        "national_team": 2,
        "etf": 3,
        "social_security": 4,
        "insurance": 5,
        "qfii": 6,
    }
    categories.sort(key=lambda item: category_order.get(str(item.get("id")), 99))
    industry_scores: dict[str, float] = {}
    for category in categories:
        total = value_or_zero(category.get("totalMarketValue"))
        if total <= 0:
            continue
        for industry, market_value in category.get("_industryValues", {}).items():
            industry_scores[industry] = industry_scores.get(industry, 0.0) + market_value / total * 100

    industries = []
    for industry in sorted(industry_scores, key=lambda name: (-industry_scores[name], name)):
        values: dict[str, dict[str, float]] = {}
        for category in categories:
            category_id = str(category.get("id"))
            market_value = value_or_zero(category.get("_industryValues", {}).get(industry))
            total = value_or_zero(category.get("totalMarketValue"))
            if market_value <= 0 or total <= 0:
                continue
            values[category_id] = {
                "marketValue": round(market_value, 2),
                "sharePct": round(market_value / total * 100, 2),
            }
        industries.append({"name": industry, "values": values})

    def category_value(category: dict[str, Any], market_value: float) -> dict[str, float] | None:
        total = value_or_zero(category.get("totalMarketValue"))
        if market_value <= 0 or total <= 0:
            return None
        return {
            "marketValue": round(market_value, 2),
            "sharePct": round(market_value / total * 100, 2),
        }

    industry_groups: list[dict[str, Any]] = []
    for parent, child_names in SW_INDUSTRY_GROUPS.items():
        parent_values: dict[str, dict[str, float]] = {}
        for category in categories:
            category_id = str(category.get("id"))
            cell = category_value(category, value_or_zero(category.get("_industryValues", {}).get(parent)))
            if cell:
                parent_values[category_id] = cell

        children = []
        for child in child_names:
            child_values: dict[str, dict[str, float]] = {}
            for category in categories:
                if not category.get("hasLevel2Data"):
                    continue
                category_id = str(category.get("id"))
                market_value = value_or_zero(
                    category.get("_industryLevel2Values", {}).get(parent, {}).get(child)
                )
                cell = category_value(category, market_value)
                if cell:
                    child_values[category_id] = cell
            children.append(
                {
                    "id": f"{parent}/{child}",
                    "name": child,
                    "parent": parent,
                    "level": 2,
                    "values": child_values,
                }
            )

        industry_groups.append(
            {
                "id": parent,
                "name": parent,
                "level": 1,
                "values": parent_values,
                "children": children,
            }
        )

    official_parents = set(SW_INDUSTRY_GROUPS)
    residual_names = sorted(
        {
            industry
            for category in categories
            for industry in category.get("_industryValues", {})
            if industry not in official_parents
        }
    )
    for industry in residual_names:
        values: dict[str, dict[str, float]] = {}
        for category in categories:
            category_id = str(category.get("id"))
            cell = category_value(category, value_or_zero(category.get("_industryValues", {}).get(industry)))
            if cell:
                values[category_id] = cell
        industry_groups.append(
            {
                "id": f"unclassified/{industry}",
                "name": industry,
                "level": 1,
                "values": values,
                "children": [],
                "isUnclassified": True,
            }
        )

    public_categories = [
        {key: value for key, value in category.items() if not key.startswith("_")}
        for category in categories
    ]
    return {
        "reportDate": report_date,
        "generatedAt": datetime.now(UTC).isoformat(),
        "basis": "各类资金已披露持仓市值内的申万一级/二级行业占比",
        "categories": public_categories,
        "industries": industries,
        "industryGroups": industry_groups,
        "notes": [
            "每列占比以该类资金当前展示样本的已披露持仓市值为 100%，不是该行业总市值或流通市值占比。",
            "公募季报按重仓披露口径；国家队、社保、保险、QFII 按上市公司机构持仓披露口径。",
            "公募、国家队、社保、保险与 QFII 来自东方财富 Choice 对基金/上市公司披露的聚合，并非交易所全量原始仓位；页面同时展示样本数与数量覆盖率。",
            "百亿私募来自私募排排网公开样本的媒体转载，只公开行业前十，其余行业合并为“其他”，不能外推为全私募行业配置。",
            "不同资金类别可能重叠，例如 ETF 也属于公募基金，不能横向相加。",
        ],
        "errors": errors,
    }


def fetch_market_overviews_sync(db_path: Path, timeout: float) -> list[dict[str, Any]]:
    session = new_browser_session()
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
    vendor_error = ""
    vendor_source = "TradingView Scanner"
    vendor_source_url = f"https://www.tradingview.com/markets/{market_def['scanner']}/stocks-{market_def['scanner']}/market-movers-large-cap/"
    try:
        if market_def["id"] == "a_share":
            rows, total_count = fetch_eastmoney_a_share_rows_sync(session, timeout)
            vendor_source = "东方财富沪深 A 股行情列表"
            vendor_source_url = EASTMONEY_A_SHARE_LIST_URL
        else:
            rows, total_count = fetch_tradingview_stock_rows(session, market_def["scanner"], timeout)
    except Exception as error:
        rows = []
        total_count = 0
        vendor_error = str(error)
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
    source = vendor_source
    source_url = vendor_source_url
    data_timestamp = ""
    hkex_turnover: dict[str, Any] | None = None
    market_cap_label = "当前总市值"
    market_data_candidates: list[dict[str, Any]] = [
        {
            "source": vendor_source,
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
    if vendor_error:
        market_data_candidates[0]["error"] = vendor_error
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
    if market_def["id"] == "a_share":
        if rows:
            market["marketBreadthSignal"] = build_market_breadth_signal(
                rows,
                total_count,
                source="东方财富沪深 A 股行情列表",
                source_url=EASTMONEY_A_SHARE_LIST_URL,
                source_badge="东方财富扫描 · 覆盖率可见",
            )
        else:
            market["marketBreadthSignal"] = empty_signal_card(
                "breadth",
                "市场宽度",
                f"东方财富沪深 A 股行情列表未返回可用样本：{vendor_error}",
                source="东方财富沪深 A 股行情列表",
                source_url=EASTMONEY_A_SHARE_LIST_URL,
            )
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
        "financingMomentumSignal": empty_signal_card(
            "financing",
            "融资边际",
            note,
            source="东方财富融资融券",
            source_url=EASTMONEY_RZRQ_URL,
        ),
    }


def fetch_a_share_financing_sync(session: requests.Session, timeout: float) -> dict[str, Any]:
    warm_browser_session(session, EASTMONEY_RZRQ_URL, timeout)
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
        reported_ratio = safe_float(row.get("RZYEZB"))
        float_market_cap = safe_float(row.get("LTSZ"))
        buy = safe_float(row.get("RZMRE"))
        repayment = safe_float(row.get("RZCHE"))
        reported_net_buy = safe_float(row.get("RZJME"))
        record_date = str(row.get("DIM_DATE") or "").split(" ")[0]
        if balance is None or balance <= 0 or float_market_cap is None or float_market_cap <= 0 or not record_date:
            continue
        ratio = balance / float_market_cap * 100
        if reported_ratio is None or abs(reported_ratio - ratio) > 0.01:
            continue
        calculated_net_buy = buy - repayment if buy is not None and repayment is not None else None
        if (
            calculated_net_buy is not None
            and reported_net_buy is not None
            and abs(calculated_net_buy - reported_net_buy) > max(abs(buy or 0), abs(repayment or 0)) * 0.001
        ):
            continue
        records.append(
            {
                "date": record_date,
                "balance": balance,
                "ratio": ratio,
                "netBuy": reported_net_buy if reported_net_buy is not None else calculated_net_buy,
                "buy": buy,
                "repayment": repayment,
                "shortBalance": safe_float(row.get("RQYE")),
                "shortNetSell": safe_float(row.get("RQJMG")),
                "floatMarketCap": float_market_cap,
            }
        )

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
        "financingPercentileSource": "东方财富融资融券历史总量（RZYE/LTSZ，并校验 RZYEZB）",
        "financingPercentileNote": "" if percentile is not None else "暂无可靠历史基准",
        "financingSource": "东方财富融资融券历史总量",
        "financingSourceUrl": EASTMONEY_RZRQ_URL,
        "financingDataTimestamp": latest["date"],
        "financingMomentumSignal": build_financing_momentum_signal(records),
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
    warm_browser_session(
        session,
        "https://www.tradingview.com/markets/stocks-china/market-movers-all-stocks/",
        timeout,
    )
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
    warm_browser_session(session, f"https://finance.sina.com.cn/realstock/company/{symbol}/nc.shtml", timeout)
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
    try:
        response = session.post(url, headers=tradingview_headers(), json=payload, timeout=max(timeout, 12))
        response.raise_for_status()
        return response.json()
    except Exception as error:
        raise RuntimeError(f"TradingView {scanner} scan failed: {error!r}") from error


def tradingview_headers() -> dict[str, str]:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
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
    session = new_browser_session()
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
    session = new_browser_session()
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


def signal_metric(label: str, value: Any, value_format: str, note: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "format": value_format, "note": note}


def signal_chart(
    chart_id: str,
    title: str,
    kind: str,
    unit: str,
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    return {"id": chart_id, "title": title, "kind": kind, "unit": unit, "series": series}


def empty_signal_card(
    signal_id: str,
    title: str,
    note: str,
    *,
    source: str = "公开数据",
    source_url: str = "",
) -> dict[str, Any]:
    return {
        "id": signal_id,
        "title": title,
        "eyebrow": "边际信号",
        "description": "本轮未取得可验证数据。",
        "status": "unavailable",
        "dataTimestamp": "",
        "metrics": [],
        "charts": [],
        "details": [],
        "source": source,
        "sourceUrl": source_url,
        "sourceBadge": "待验证",
        "cadence": "随大盘快照刷新",
        "note": note,
    }


def build_financing_momentum_signal(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (record for record in records if record.get("date") and safe_float(record.get("netBuy")) is not None),
        key=lambda record: str(record["date"]),
    )
    if len(ordered) < 10:
        return empty_signal_card(
            "financing",
            "融资边际",
            "融资历史中可用净买入记录不足 10 个交易日。",
            source="东方财富融资融券",
            source_url=EASTMONEY_RZRQ_URL,
        )

    daily = [safe_float(record.get("netBuy")) or 0.0 for record in ordered]
    rolling_five: list[float] = []
    rolling_points: list[dict[str, Any]] = []
    for index in range(4, len(ordered)):
        value = sum(daily[index - 4 : index + 1])
        rolling_five.append(value)
        rolling_points.append({"label": ordered[index]["date"], "value": round(value / 100_000_000, 3)})

    latest_five = sum(daily[-5:])
    previous_five = sum(daily[-10:-5])
    latest_twenty = sum(daily[-20:]) if len(daily) >= 20 else sum(daily)
    acceleration = latest_five - previous_five
    latest_cap = safe_float(ordered[-1].get("floatMarketCap"))
    intensity = latest_five / latest_cap * 100 if latest_cap and latest_cap > 0 else None
    z_score = None
    if len(rolling_five) >= 10:
        deviation = statistics.pstdev(rolling_five)
        if deviation > 0:
            z_score = (rolling_five[-1] - statistics.mean(rolling_five)) / deviation

    daily_points = [
        {"label": record["date"], "value": round((safe_float(record.get("netBuy")) or 0) / 100_000_000, 3)}
        for record in ordered[-45:]
    ]
    rolling_points = rolling_points[-45:]
    latest_short = safe_float(ordered[-1].get("shortBalance"))
    previous_short = safe_float(ordered[-6].get("shortBalance")) if len(ordered) >= 6 else None
    short_change = latest_short - previous_short if latest_short is not None and previous_short is not None else None

    return {
        "id": "financing",
        "title": "融资边际",
        "eyebrow": "杠杆资金",
        "description": "看净买入的速度与加速度，而不是只看融资余额。",
        "status": "ok",
        "dataTimestamp": ordered[-1]["date"],
        "metrics": [
            signal_metric("5日净买入", round(latest_five, 2), "cny"),
            signal_metric("较前5日加速度", round(acceleration, 2), "cny"),
            signal_metric("20日净买入", round(latest_twenty, 2), "cny"),
            signal_metric("5日/流通市值", round(intensity, 5) if intensity is not None else None, "pct"),
            signal_metric("5日动量 Z 分数", round(z_score, 2) if z_score is not None else None, "number"),
            signal_metric("融券余额5日变化", round(short_change, 2) if short_change is not None else None, "cny"),
        ],
        "charts": [
            signal_chart(
                "financing-flow",
                "融资净买入与5日滚动",
                "line",
                "亿元",
                [
                    {"key": "daily", "label": "单日净买入", "color": "#4f8fd8", "points": daily_points},
                    {"key": "rolling5", "label": "5日滚动", "color": "#f59e0b", "points": rolling_points},
                ],
            )
        ],
        "details": [],
        "source": "东方财富融资融券历史总量",
        "sourceUrl": EASTMONEY_RZRQ_URL,
        "sourceBadge": "Choice 聚合 · 运行时校验",
        "cadence": "交易日",
        "note": "采用接口披露的 RZJME（融资净买额），并在运行时与融资买入额减融资偿还额做 0.1% 总额容差校验；强度分母采用 RZYE/LTSZ，且与接口 RZYEZB 对账。",
    }


def fetch_eastmoney_a_share_rows_sync(
    session: requests.Session,
    timeout: float,
) -> tuple[list[dict[str, Any]], int]:
    warm_browser_session(session, EASTMONEY_A_SHARE_LIST_URL, timeout)
    base_params = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f6,f9,f20,f124",
    }
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    total_count = 0
    scanned_count = 0
    page = 1
    page_size = 100
    while page <= 70 and (page == 1 or scanned_count < total_count):
        response = session.get(
            EASTMONEY_ETF_LIST_API,
            params={**base_params, "pn": str(page), "pz": str(page_size)},
            headers=eastmoney_headers(EASTMONEY_A_SHARE_LIST_URL),
            timeout=max(timeout, 15),
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        page_rows = data.get("diff") or []
        if isinstance(page_rows, dict):
            page_rows = list(page_rows.values())
        if not page_rows:
            break
        total_count = int(data.get("total") or total_count or len(page_rows))
        scanned_count += len(page_rows)
        for row in page_rows:
            symbol = str(row.get("f12") or "")
            change_pct = safe_float(row.get("f3"))
            if not symbol:
                continue
            quote_date = ""
            quote_timestamp = safe_float(row.get("f124"))
            if quote_timestamp is not None and quote_timestamp > 0:
                if quote_timestamp > 10_000_000_000:
                    quote_timestamp /= 1000
                try:
                    quote_date = datetime.fromtimestamp(quote_timestamp, CN_TZ).date().isoformat()
                except (OSError, OverflowError, ValueError):
                    quote_date = ""
            rows_by_symbol[symbol] = {
                "symbol": symbol,
                "name": str(row.get("f14") or ""),
                "close": safe_float(row.get("f2")),
                "changePct": change_pct,
                "turnover": safe_float(row.get("f6")),
                "pe": safe_float(row.get("f9")),
                "marketCap": safe_float(row.get("f20")),
                "date": quote_date,
            }
        page += 1
        time.sleep(random.uniform(0.18, 0.45))
    rows = sorted(
        rows_by_symbol.values(),
        key=lambda item: value_or_zero(item.get("marketCap")),
        reverse=True,
    )
    if not any(safe_float(row.get("changePct")) is not None for row in rows):
        raise RuntimeError("东方财富 A 股行情列表未返回有效涨跌幅")
    return rows, total_count


def build_market_breadth_signal(
    rows: list[dict[str, Any]],
    total_count: int = 0,
    *,
    source: str = "TradingView Scanner A股普通股样本",
    source_url: str = "https://www.tradingview.com/markets/stocks-china/market-movers-all-stocks/",
    source_badge: str = "行情商扫描 · 覆盖率可见",
) -> dict[str, Any]:
    changes = [value for value in (safe_float(row.get("changePct")) for row in rows) if value is not None]
    if not changes:
        return empty_signal_card(
            "breadth",
            "市场宽度",
            "本轮 A 股行情样本未返回可用涨跌幅。",
            source=source,
            source_url=source_url,
        )

    advances = sum(1 for value in changes if value > 0.05)
    declines = sum(1 for value in changes if value < -0.05)
    flat = len(changes) - advances - declines
    turnovers = sorted(
        (value for value in (safe_float(row.get("turnover")) for row in rows) if value is not None and value > 0),
        reverse=True,
    )
    total_turnover = sum(turnovers)
    concentration = sum(turnovers[:50]) / total_turnover * 100 if total_turnover > 0 else None
    advance_pct = advances / len(changes) * 100
    coverage = len(changes) / total_count * 100 if total_count > 0 else None
    limit_up = sum(1 for value in changes if value >= 9.5)
    limit_down = sum(1 for value in changes if value <= -9.5)
    quote_dates = [
        str(row.get("date"))
        for row in rows
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("date") or ""))
    ]

    return {
        "id": "breadth",
        "title": "市场宽度",
        "eyebrow": "扩散程度",
        "description": "指数上涨是否由多数股票共同推动，以及成交是否过度集中。",
        "status": "ok",
        "dataTimestamp": max(quote_dates) if quote_dates else expected_market_snapshot_date("a_share").isoformat(),
        "metrics": [
            signal_metric("上涨家数占比", round(advance_pct, 2), "pct"),
            signal_metric("涨跌家数比", round(advances / max(declines, 1), 2), "ratio"),
            signal_metric("个股中位涨跌", round(statistics.median(changes), 2), "pct"),
            signal_metric("有效样本/扫描总数", f"{len(changes)}/{total_count}" if total_count else len(changes), "text"),
            signal_metric("涨停近似", limit_up, "count"),
            signal_metric("跌停近似", limit_down, "count"),
            signal_metric("成交额Top50集中度", round(concentration, 2) if concentration is not None else None, "pct"),
            signal_metric("样本覆盖", round(coverage, 2) if coverage is not None else None, "pct"),
        ],
        "charts": [
            signal_chart(
                "breadth-distribution",
                "上涨 / 平盘 / 下跌",
                "bar",
                "家",
                [
                    {
                        "key": "breadth",
                        "label": "股票家数",
                        "color": "#4f8fd8",
                        "points": [
                            {"label": "上涨", "value": advances, "color": "#ef5350"},
                            {"label": "平盘", "value": flat, "color": "#94a3b8"},
                            {"label": "下跌", "value": declines, "color": "#22a06b"},
                        ],
                    }
                ],
            )
        ],
        "details": [],
        "source": source,
        "sourceUrl": source_url,
        "sourceBadge": source_badge,
        "cadence": "盘中快照",
        "note": "仅统计扫描器返回且具备有效涨跌幅的主要上市普通股；涨跌停按 ±9.5% 近似，未逐只校正 ST、主板与注册制不同涨跌幅限制。",
    }


def empty_marginal_signals(note: str = "本轮边际信号暂未取到") -> dict[str, Any]:
    definitions = [
        ("financing", "融资边际"),
        ("etf_flow", "ETF 估算净申购"),
        ("index_futures", "股指期货基差与持仓"),
        ("options", "期权保护需求"),
        ("industrial_capital", "产业资本披露"),
        ("breadth", "市场宽度"),
        ("funding", "资金价格"),
    ]
    return {
        "cards": [empty_signal_card(signal_id, title, note) for signal_id, title in definitions],
        "errors": [note] if note else [],
        "notes": ["北向资金不再提供可比的每日净买入公开口径，因此不纳入边际卡片。"],
    }


def fetch_marginal_signals_sync(markets: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
    a_market = next((market for market in markets if market.get("id") == "a_share"), {})
    market_cap = safe_float(a_market.get("marketCap"))
    cards: dict[str, dict[str, Any]] = {
        "financing": a_market.get("financingMomentumSignal")
        or empty_signal_card("financing", "融资边际", "A股融资边际数据暂未取到。"),
        "breadth": a_market.get("marketBreadthSignal")
        or empty_signal_card("breadth", "市场宽度", "A股市场宽度暂未取到。"),
    }
    jobs = {
        "etf_flow": (fetch_etf_flow_signal_sync, (timeout,)),
        "index_futures": (fetch_index_futures_signal_sync, (timeout,)),
        "options": (fetch_options_signal_sync, (timeout,)),
        "industrial_capital": (fetch_industrial_capital_signal_sync, (timeout, market_cap)),
        "funding": (fetch_funding_signal_sync, (timeout,)),
    }
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(function, *args): signal_id for signal_id, (function, args) in jobs.items()}
        for future in as_completed(futures):
            signal_id = futures[future]
            try:
                cards[signal_id] = future.result()
            except Exception as error:
                title = {
                    "etf_flow": "ETF 估算净申购",
                    "index_futures": "股指期货基差与持仓",
                    "options": "期权保护需求",
                    "industrial_capital": "产业资本披露",
                    "funding": "资金价格",
                }[signal_id]
                errors.append(f"{title}：{error}")
                cards[signal_id] = empty_signal_card(signal_id, title, str(error))

    ordered_ids = ["financing", "etf_flow", "index_futures", "options", "industrial_capital", "breadth", "funding"]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "cards": [cards[signal_id] for signal_id in ordered_ids],
        "errors": errors,
        "notes": [
            "每张卡片标注来源层级；凡经过模型或价格代理计算的指标均明确标为估算，不与交易所原始值混写。",
            "机构行业配置属于季度慢变量，保留在下方独立展示；这里优先呈现交易日级边际流量。",
            "北向资金自披露口径调整后不再有连续可比的每日净买入公开数据，因此不以估算值替代。",
        ],
    }


ETF_FLOW_BROAD_KEYWORDS = (
    "沪深300", "上证50", "中证500", "中证1000", "中证2000", "中证A500", "A500",
    "科创50", "创业板", "科创创业", "上证180", "上证指数", "深证100", "中证800",
)


def etf_flow_bucket(name: str) -> str:
    normalized = str(name or "").replace(" ", "")
    return "broad" if any(keyword in normalized for keyword in ETF_FLOW_BROAD_KEYWORDS) else "industry"


def estimate_etf_flow_from_aum(
    previous_aum: float,
    current_aum: float,
    previous_close: float,
    current_close: float,
) -> float:
    if min(previous_aum, current_aum, previous_close, current_close) <= 0:
        raise ValueError("ETF 规模与收盘价必须为正数")
    return current_aum - previous_aum * current_close / previous_close


def etf_implied_share_change_is_plausible(
    previous_aum: float,
    current_aum: float,
    previous_close: float,
    current_close: float,
) -> bool:
    if min(previous_aum, current_aum, previous_close, current_close) <= 0:
        return False
    implied_share_ratio = (current_aum / current_close) / (previous_aum / previous_close)
    return 0.5 <= implied_share_ratio <= 1.5


def fetch_sse_etf_scale_history_sync(session: requests.Session, code: str, timeout: float) -> list[dict[str, Any]]:
    warm_browser_session(session, f"{SSE_ETF_DETAIL_URL}?code={code}", timeout)
    response = session.get(
        SSE_STOCK_STATISTIC_API,
        params={
            "isPagination": "true",
            "sqlId": "COMMON_JJZWZ_JJLB_JJXQ_JJGM_CKLSGM_L",
            "pageHelp.cacheSize": "1",
            "pageHelp.pageSize": "45",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.endPage": "1",
            "FUND_CODE": code,
        },
        headers={
            "User-Agent": random_user_agent(),
            "Referer": f"{SSE_ETF_DETAIL_URL}?code={code}",
        },
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    rows = response.json().get("result") or []
    result = []
    for row in rows:
        scale = safe_float(row.get("SCALE"))
        trade_date = str(row.get("TRADE_DATE") or "")
        if scale is None or scale <= 0 or not trade_date:
            continue
        # 上交所基金档案将 SCALE 展示为“基金规模（亿元）”，不是基金份额。
        result.append({"date": trade_date, "aumCny": scale * 100_000_000})
    return sorted(result, key=lambda item: item["date"])


def fetch_one_etf_flow_sync(etf: dict[str, Any], timeout: float) -> dict[str, Any]:
    code = str(etf.get("f12") or "")
    name = str(etf.get("f14") or code)
    if not code.startswith("5"):
        raise ValueError(f"{code} 不是上交所 ETF")
    with new_browser_session() as session:
        scales = fetch_sse_etf_scale_history_sync(session, code, timeout)
        prices = fetch_sina_cn_index_kline(session, f"sh{code}", timeout)
    close_by_date = {
        str(row.get("date") or ""): value
        for row in prices
        if (value := safe_float(row.get("close"))) is not None and value > 0
    }
    points: list[dict[str, Any]] = []
    excluded_corporate_action_days = 0
    for previous, current in zip(scales, scales[1:]):
        previous_close = close_by_date.get(previous["date"])
        current_close = close_by_date.get(current["date"])
        if previous_close is None or current_close is None or previous_close <= 0:
            continue
        if not etf_implied_share_change_is_plausible(
            previous["aumCny"],
            current["aumCny"],
            previous_close,
            current_close,
        ):
            excluded_corporate_action_days += 1
            continue
        # 用价格收益剔除规模随市场涨跌的被动变化；剩余项近似申赎、分红与跟踪误差的合计影响。
        flow = estimate_etf_flow_from_aum(
            previous["aumCny"],
            current["aumCny"],
            previous_close,
            current_close,
        )
        points.append({"date": current["date"], "flow": flow})
    if not points:
        raise RuntimeError(f"{name} 缺少可匹配的基金规模与收盘价历史")
    return {
        "code": code,
        "name": name,
        "bucket": etf_flow_bucket(name),
        "marketValue": value_or_zero(etf.get("f20")),
        "points": points,
        "excludedCorporateActionDays": excluded_corporate_action_days,
    }


def build_etf_flow_signal(samples: list[dict[str, Any]], eligible_market_value: float) -> dict[str, Any]:
    if not samples:
        return empty_signal_card(
            "etf_flow",
            "ETF 估算净申购",
            "头部境内股票 ETF 未返回可匹配的基金规模和价格历史。",
            source="上交所 ETF / 新浪行情",
            source_url=SSE_ETF_DETAIL_URL,
        )
    daily: dict[str, dict[str, float]] = {}
    sample_totals: list[dict[str, Any]] = []
    for sample in samples:
        total = 0.0
        for point in sample.get("points") or []:
            trade_date = str(point.get("date") or "")
            flow = safe_float(point.get("flow"))
            if not trade_date or flow is None:
                continue
            bucket = sample.get("bucket") if sample.get("bucket") in {"broad", "industry"} else "industry"
            day = daily.setdefault(trade_date, {"broad": 0.0, "industry": 0.0})
            day[bucket] += flow
            total += flow
        sample_totals.append({"name": sample.get("name"), "value": total})
    dates = sorted(daily)[-30:]
    if not dates:
        return empty_signal_card(
            "etf_flow",
            "ETF 估算净申购",
            "ETF 基金规模历史未形成可用聚合日期。",
            source="上交所 ETF / 新浪行情",
            source_url=SSE_ETF_DETAIL_URL,
        )

    broad_values = [daily[trade_date]["broad"] for trade_date in dates]
    industry_values = [daily[trade_date]["industry"] for trade_date in dates]
    total_values = [broad + industry for broad, industry in zip(broad_values, industry_values)]
    last_five = sum(total_values[-5:])
    last_twenty = sum(total_values[-20:])
    selected_market_value = sum(value_or_zero(sample.get("marketValue")) for sample in samples)
    coverage = selected_market_value / eligible_market_value * 100 if eligible_market_value > 0 else None
    latest_date = dates[-1]
    excluded_corporate_action_days = sum(
        round(value_or_zero(sample.get("excludedCorporateActionDays")))
        for sample in samples
    )
    top_five = sorted(sample_totals, key=lambda item: abs(value_or_zero(item.get("value"))), reverse=True)[:5]

    return {
        "id": "etf_flow",
        "title": "ETF 估算净申购",
        "eyebrow": "规模变动剔除涨跌",
        "description": "用头部股票 ETF 的官方基金规模，剔除价格收益后估算申赎资金的边际方向。",
        "status": "ok",
        "dataTimestamp": latest_date,
        "metrics": [
            signal_metric("最新单日", round(total_values[-1], 2), "cny"),
            signal_metric("5日合计", round(last_five, 2), "cny"),
            signal_metric("20日合计", round(last_twenty, 2), "cny"),
            signal_metric("宽基5日", round(sum(broad_values[-5:]), 2), "cny"),
            signal_metric("行业主题5日", round(sum(industry_values[-5:]), 2), "cny"),
            signal_metric("样本规模覆盖", round(coverage, 2) if coverage is not None else None, "pct"),
            signal_metric("异常日期排除", excluded_corporate_action_days, "count"),
        ],
        "charts": [
            signal_chart(
                "etf-flow-history",
                "宽基与行业主题估算净申购",
                "line",
                "亿元",
                [
                    {
                        "key": "broad",
                        "label": "宽基",
                        "color": "#2563eb",
                        "points": [{"label": item, "value": round(value / 100_000_000, 3)} for item, value in zip(dates, broad_values)],
                    },
                    {
                        "key": "industry",
                        "label": "行业主题",
                        "color": "#f59e0b",
                        "points": [{"label": item, "value": round(value / 100_000_000, 3)} for item, value in zip(dates, industry_values)],
                    },
                ],
            )
        ],
        "details": [
            {"label": str(item.get("name") or "ETF"), "value": round(value_or_zero(item.get("value")), 2), "format": "cny"}
            for item in top_five
        ],
        "source": "上交所 ETF 基金规模 / 新浪 ETF 日线",
        "sourceUrl": SSE_ETF_DETAIL_URL,
        "sourceBadge": "上交所规模 · 明确估算",
        "cadence": "交易日",
        "note": f"按当前规模选取 {len(samples)} 只上交所头部境内股票 ETF；估算净申购=当日官方基金规模-前日官方基金规模×当日收盘价/前日收盘价。收盘价仅作为净值收益代理，分红、折溢价和跟踪误差会造成偏差；若规模/收盘价推算的份额单日变化超过 ±50%，视为拆分或数据时点错配并排除（本窗口 {excluded_corporate_action_days} 个样本日），因此不等同于全市场精确资金流。",
    }


def fetch_etf_flow_signal_sync(timeout: float) -> dict[str, Any]:
    with new_browser_session() as session:
        universe = fetch_etf_universe_rows_sync(session, timeout)
    eligible = [
        row for row in universe
        if str(row.get("f12") or "").startswith("5") and is_domestic_equity_etf(row)
    ]
    eligible.sort(key=lambda row: value_or_zero(row.get("f20")), reverse=True)
    broad = [row for row in eligible if etf_flow_bucket(str(row.get("f14") or "")) == "broad"][:6]
    industry = [row for row in eligible if etf_flow_bucket(str(row.get("f14") or "")) == "industry"][:6]
    selected = broad + industry
    samples: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_one_etf_flow_sync, row, timeout) for row in selected]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except Exception:
                continue
    eligible_market_value = sum(value_or_zero(row.get("f20")) for row in eligible)
    return build_etf_flow_signal(samples, eligible_market_value)


INDEX_FUTURES_DEFS = {
    "IF": {"spotSymbol": "sh000300", "spotName": "沪深300"},
    "IH": {"spotSymbol": "sh000016", "spotName": "上证50"},
    "IC": {"spotSymbol": "sh000905", "spotName": "中证500"},
    "IM": {"spotSymbol": "sh000852", "spotName": "中证1000"},
}


def parse_cffex_daily_rows(payload: bytes) -> list[dict[str, Any]]:
    if not payload or len(payload) > 5_000_000:
        raise ValueError("中金所日统计 XML 为空或体积异常")
    upper_payload = payload.upper()
    if b"<!DOCTYPE" in upper_payload or b"<!ENTITY" in upper_payload:
        raise ValueError("中金所日统计 XML 包含不允许的实体声明")
    root = ET.fromstring(payload)
    rows: list[dict[str, Any]] = []
    for node in root.findall(".//dailydata"):
        instrument_id = str(node.findtext("instrumentid") or "").strip()
        if not re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}", instrument_id):
            continue
        trade_day = str(node.findtext("tradingday") or "").strip()
        if not re.fullmatch(r"\d{8}", trade_day):
            continue
        rows.append(
            {
                "symbol": instrument_id[:2],
                "instrumentId": instrument_id,
                "tradeDate": f"{trade_day[:4]}-{trade_day[4:6]}-{trade_day[6:]}",
                "close": safe_float(node.findtext("closeprice")),
                "volume": safe_float(node.findtext("volume")),
                "openInterest": safe_float(node.findtext("openinterest")),
                "previousOpenInterest": safe_float(node.findtext("preopeninterest")),
            }
        )
    return rows


def fetch_cffex_daily_rows_sync(session: requests.Session, timeout: float) -> list[dict[str, Any]]:
    warm_browser_session(session, CFFEX_DAILY_STATISTICS_URL, timeout)
    for offset in range(12):
        candidate = datetime.now(CN_TZ).date() - timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        try:
            response = session.get(
                f"{CFFEX_DAILY_DATA_BASE}/{candidate:%Y%m}/{candidate:%d}/index.xml",
                headers={"User-Agent": random_user_agent(), "Referer": CFFEX_DAILY_STATISTICS_URL},
                timeout=max(timeout, 18),
            )
        except requests.RequestException:
            continue
        if response.status_code != 200 or "xml" not in str(response.headers.get("Content-Type") or "").lower():
            continue
        try:
            rows = parse_cffex_daily_rows(response.content)
        except (ET.ParseError, ValueError):
            continue
        if rows:
            return rows
    raise RuntimeError("中金所最近 12 个自然日未返回可用股指期货日统计")


def build_index_futures_signal(rows: list[dict[str, Any]], spots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contracts: list[dict[str, Any]] = []
    for symbol, definition in INDEX_FUTURES_DEFS.items():
        candidates = [
            row
            for row in rows
            if row.get("symbol") == symbol and safe_float(row.get("openInterest")) is not None
        ]
        if not candidates:
            continue
        row = max(candidates, key=lambda item: value_or_zero(item.get("openInterest")))
        spot = spots.get(symbol) or {}
        future_price = safe_float(row.get("close"))
        spot_price = safe_float(spot.get("close"))
        trade_date = str(row.get("tradeDate") or "")
        if (
            future_price is None
            or spot_price is None
            or spot_price <= 0
            or not trade_date
            or str(spot.get("date") or "") != trade_date
        ):
            continue
        basis_pct = (future_price / spot_price - 1) * 100
        open_interest = safe_float(row.get("openInterest"))
        previous_open_interest = safe_float(row.get("previousOpenInterest"))
        open_interest_change = (
            open_interest - previous_open_interest
            if open_interest is not None and previous_open_interest is not None
            else None
        )
        open_interest_change_pct = (
            open_interest_change / previous_open_interest * 100
            if open_interest_change is not None and previous_open_interest and previous_open_interest > 0
            else None
        )
        contracts.append(
            {
                "symbol": symbol,
                "name": str(row.get("instrumentId") or symbol),
                "spotName": definition["spotName"],
                "future": future_price,
                "spot": spot_price,
                "basisPct": basis_pct,
                "openInterest": open_interest,
                "openInterestChange": open_interest_change,
                "openInterestChangePct": open_interest_change_pct,
                "volume": safe_float(row.get("volume")),
                "tradeDate": trade_date,
            }
        )
    if not contracts:
        return empty_signal_card(
            "index_futures",
            "股指期货基差与持仓",
            "中金所 IF/IH/IC/IM 日统计或同日现货指数收盘价未返回可用数据。",
            source="中金所日统计 / 新浪指数日线",
            source_url=CFFEX_DAILY_STATISTICS_URL,
        )

    basis_values = [item["basisPct"] for item in contracts]
    open_interest = sum(value_or_zero(item.get("openInterest")) for item in contracts)
    volume = sum(value_or_zero(item.get("volume")) for item in contracts)
    open_interest_change = sum(value_or_zero(item.get("openInterestChange")) for item in contracts)
    data_timestamp = max((str(item.get("tradeDate") or "") for item in contracts), default="")

    return {
        "id": "index_futures",
        "title": "股指期货基差与持仓",
        "eyebrow": "对冲与杠杆",
        "description": "贴水扩大且持仓上升，通常比指数本身更快反映对冲需求。",
        "status": "ok",
        "dataTimestamp": data_timestamp,
        "metrics": [
            signal_metric("四合约平均基差", round(statistics.mean(basis_values), 3), "pct"),
            signal_metric("主力持仓合计", round(open_interest), "contracts"),
            signal_metric("主力持仓日变动", round(open_interest_change), "contracts"),
            signal_metric("主力成交合计", round(volume), "contracts"),
        ],
        "charts": [
            signal_chart(
                "futures-basis",
                "最高持仓合约相对现货基差",
                "bar",
                "%",
                [
                    {
                        "key": "basis",
                        "label": "基差",
                        "color": "#7c3aed",
                        "points": [
                            {
                                "label": item["symbol"],
                                "value": round(item["basisPct"], 3),
                                "color": "#22a06b" if item["basisPct"] >= 0 else "#7c3aed",
                            }
                            for item in contracts
                        ],
                    }
                ],
            )
        ],
        "details": [
            {
                "label": f"{item['name']} · {item['spotName']}",
                "value": round(item["basisPct"], 3),
                "format": "pct",
                "note": f"持仓 {format(round(value_or_zero(item.get('openInterest'))), ',')} 手，较前日 {format(round(value_or_zero(item.get('openInterestChange'))), ',')} 手（{round(value_or_zero(item.get('openInterestChangePct')), 2)}%）",
            }
            for item in contracts
        ],
        "source": "中金所官方日统计 / 新浪指数收盘价",
        "sourceUrl": CFFEX_DAILY_STATISTICS_URL,
        "sourceBadge": "中金所官方 · 同日基差",
        "cadence": "交易日收盘后",
        "note": "每个品种选取中金所当日持仓量最高的具体交割合约；基差=中金所合约收盘价/同日现货指数收盘价-1。持仓日变动由中金所 openinterest-preopeninterest 直接计算；换月附近仍需结合期限结构判断。",
    }


def fetch_index_futures_signal_sync(timeout: float) -> dict[str, Any]:
    with new_browser_session() as session:
        rows = fetch_cffex_daily_rows_sync(session, timeout)
        trade_date = max((str(row.get("tradeDate") or "") for row in rows), default="")
        spots: dict[str, dict[str, Any]] = {}
        for symbol, definition in INDEX_FUTURES_DEFS.items():
            history = fetch_sina_cn_index_kline(session, definition["spotSymbol"], timeout)
            matched = next((item for item in reversed(history) if item.get("date") == trade_date), None)
            if matched:
                spots[symbol] = {"date": trade_date, "close": matched.get("close")}
    return build_index_futures_signal(rows, spots)


def fetch_sse_option_statistics_rows_sync(
    session: requests.Session,
    timeout: float,
    trade_date: str = "",
) -> list[dict[str, Any]]:
    warm_browser_session(session, SSE_OPTIONS_STATISTICS_URL, timeout)
    response = session.get(
        SSE_STOCK_STATISTIC_API,
        params={
            "isPagination": "true",
            "sqlId": "COMMON_SSE_ZQPZ_YSP_QQ_SJTJ_MRTJ_CX",
            "tradeDate": trade_date,
            "pageHelp.pageSize": "50",
            "pageHelp.cacheSize": "1",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.endPage": "1",
        },
        headers={"User-Agent": random_user_agent(), "Referer": SSE_OPTIONS_STATISTICS_URL},
        timeout=max(timeout, 15),
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("result") or (payload.get("pageHelp") or {}).get("data") or []


def fetch_sse_option_risk_rows_sync(session: requests.Session, timeout: float) -> list[dict[str, Any]]:
    warm_browser_session(session, SSE_OPTIONS_STATISTICS_URL, timeout)
    response = session.get(
        SSE_STOCK_STATISTIC_API,
        params={
            "isPagination": "false",
            "sqlId": "SSE_ZQPZ_YSP_GGQQZSXT_YSHQ_QQFXZB_DATE_L",
            "trade_date": "",
            "contractSymbol": "",
        },
        headers={"User-Agent": random_user_agent(), "Referer": SSE_OPTIONS_STATISTICS_URL},
        timeout=max(timeout, 18),
    )
    response.raise_for_status()
    return response.json().get("result") or []


def summarize_option_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    call_volume = sum(value_or_zero(row.get("CALL_VOLUME")) for row in rows)
    put_volume = sum(value_or_zero(row.get("PUT_VOLUME")) for row in rows)
    call_open_interest = sum(value_or_zero(row.get("LEAVES_CALL_QTY")) for row in rows)
    put_open_interest = sum(value_or_zero(row.get("LEAVES_PUT_QTY")) for row in rows)
    trade_date = max((str(row.get("TRADE_DATE") or "") for row in rows), default="")
    return {
        "date": trade_date,
        "callVolume": call_volume,
        "putVolume": put_volume,
        "volumePutCall": put_volume / call_volume if call_volume > 0 else None,
        "callOpenInterest": call_open_interest,
        "putOpenInterest": put_open_interest,
        "openInterestPutCall": put_open_interest / call_open_interest if call_open_interest > 0 else None,
    }


def calculate_option_skew(risk_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, list[dict[str, float]]]]] = {}
    for row in risk_rows:
        contract_id = str(row.get("CONTRACT_ID") or "")
        if not re.fullmatch(r"\d{6}[CP]\d{4}M\d+", contract_id):
            continue
        code = contract_id[:6]
        option_type = contract_id[6]
        expiry = contract_id[7:11]
        delta = safe_float(row.get("DELTA_VALUE"))
        implied_volatility = safe_float(row.get("IMPLC_VOLATLTY"))
        if delta is None or implied_volatility is None or implied_volatility <= 0 or implied_volatility > 5:
            continue
        grouped.setdefault(code, {}).setdefault(expiry, {"C": [], "P": []})[option_type].append(
            {"delta": delta, "iv": implied_volatility}
        )

    results: list[dict[str, Any]] = []
    for code, expiries in grouped.items():
        for expiry in sorted(expiries):
            calls = expiries[expiry]["C"]
            puts = expiries[expiry]["P"]
            if not calls or not puts:
                continue
            call = min(calls, key=lambda item: abs(item["delta"] - 0.25))
            put = min(puts, key=lambda item: abs(item["delta"] + 0.25))
            if abs(call["delta"] - 0.25) > 0.2 or abs(put["delta"] + 0.25) > 0.2:
                continue
            results.append(
                {
                    "code": code,
                    "expiry": expiry,
                    "callIv": call["iv"] * 100,
                    "putIv": put["iv"] * 100,
                    "skewPp": (put["iv"] - call["iv"]) * 100,
                    "callDelta": call["delta"],
                    "putDelta": put["delta"],
                }
            )
            break
    return results


def build_options_signal(
    latest_rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = summarize_option_statistics(latest_rows)
    if latest.get("volumePutCall") is None:
        return empty_signal_card(
            "options",
            "期权保护需求",
            "上交所股票期权每日统计未返回认购、认沽成交量。",
            source="上交所股票期权",
            source_url=SSE_OPTIONS_STATISTICS_URL,
        )
    skews = calculate_option_skew(risk_rows)
    skew_values = [item["skewPp"] for item in skews]
    name_by_code = {
        str(row.get("SECURITY_CODE") or ""): str(row.get("SECURITY_ABBR") or row.get("SECURITY_CODE") or "")
        for row in latest_rows
    }
    history = sorted(
        (item for item in history if item.get("date") and item.get("volumePutCall") is not None),
        key=lambda item: str(item["date"]),
    )[-15:]

    return {
        "id": "options",
        "title": "期权保护需求",
        "eyebrow": "尾部风险",
        "description": "Put/Call 与 25Δ 隐波偏度可识别保护性买盘是否突然升温。",
        "status": "ok",
        "dataTimestamp": latest.get("date") or "",
        "metrics": [
            signal_metric("成交量 Put/Call", round(value_or_zero(latest.get("volumePutCall")), 3), "ratio"),
            signal_metric("持仓量 Put/Call", round(value_or_zero(latest.get("openInterestPutCall")), 3), "ratio"),
            signal_metric("25Δ 隐波偏度中位数", round(statistics.median(skew_values), 2) if skew_values else None, "pp"),
            signal_metric("期权总成交", round(value_or_zero(latest.get("callVolume")) + value_or_zero(latest.get("putVolume"))), "contracts"),
        ],
        "charts": [
            signal_chart(
                "option-put-call",
                "成交量 Put/Call",
                "line",
                "倍",
                [
                    {
                        "key": "putCall",
                        "label": "Put/Call",
                        "color": "#dc2626",
                        "points": [
                            {"label": item["date"], "value": round(value_or_zero(item.get("volumePutCall")), 3)}
                            for item in history
                        ],
                    }
                ],
            ),
            signal_chart(
                "option-skew",
                "最近到期月 25Δ 隐波偏度",
                "bar",
                "百分点",
                [
                    {
                        "key": "skew",
                        "label": "Put IV - Call IV",
                        "color": "#b91c1c",
                        "points": [
                            {
                                "label": name_by_code.get(item["code"], item["code"]).replace("ETF", ""),
                                "value": round(item["skewPp"], 2),
                            }
                            for item in skews
                        ],
                    }
                ],
            ),
        ],
        "details": [
            {
                "label": name_by_code.get(item["code"], item["code"]),
                "value": round(item["skewPp"], 2),
                "format": "pp",
                "note": f"{item['expiry'][:2]}年{item['expiry'][2:]}月",
            }
            for item in skews
        ],
        "source": "上交所股票期权每日统计与风险指标",
        "sourceUrl": SSE_OPTIONS_STATISTICS_URL,
        "sourceBadge": "上交所官方 · 派生指标",
        "cadence": "交易日收盘后",
        "note": "Put/Call 汇总上交所已上市 ETF 期权；偏度取各标的最近到期月、最接近 ±0.25 Delta 的有效隐波，正值代表下行保护更贵。",
    }


def fetch_option_statistics_for_date_sync(trade_date: date, timeout: float) -> dict[str, Any]:
    with new_browser_session() as session:
        rows = fetch_sse_option_statistics_rows_sync(session, timeout, trade_date.strftime("%Y%m%d"))
    return summarize_option_statistics(rows)


def fetch_options_signal_sync(timeout: float) -> dict[str, Any]:
    with new_browser_session() as session:
        latest_rows = fetch_sse_option_statistics_rows_sync(session, timeout)
        risk_rows = fetch_sse_option_risk_rows_sync(session, timeout)
        latest = summarize_option_statistics(latest_rows)
        try:
            latest_date = date.fromisoformat(str(latest.get("date") or ""))
        except ValueError:
            latest_date = datetime.now(CN_TZ).date()
        candidate_dates = [
            latest_date - timedelta(days=offset)
            for offset in range(1, 23)
            if (latest_date - timedelta(days=offset)).weekday() < 5
        ][:14]
        history = [latest]
        for candidate_date in candidate_dates:
            try:
                rows = fetch_sse_option_statistics_rows_sync(
                    session,
                    timeout,
                    candidate_date.strftime("%Y%m%d"),
                )
                summary = summarize_option_statistics(rows)
                if summary.get("date") and summary.get("volumePutCall") is not None:
                    history.append(summary)
            except Exception:
                continue
            time.sleep(random.uniform(0.12, 0.35))
    return build_options_signal(latest_rows, history, risk_rows)


def fetch_eastmoney_report_rows_sync(
    session: requests.Session,
    timeout: float,
    *,
    report_name: str,
    sort_column: str,
    filter_text: str,
    referer: str,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    warm_browser_session(session, referer, timeout)
    rows: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages and page <= max_pages:
        response = session.get(
            EASTMONEY_STOCK_STATS_API,
            params={
                "reportName": report_name,
                "columns": "ALL",
                "source": "WEB",
                "sortColumns": sort_column,
                "sortTypes": "-1",
                "pageNumber": str(page),
                "pageSize": "500",
                "filter": filter_text,
            },
            headers=eastmoney_headers(referer),
            timeout=max(timeout, 18),
        )
        response.raise_for_status()
        result = response.json().get("result") or {}
        page_rows = result.get("data") or []
        rows.extend(page_rows)
        try:
            pages = int(result.get("pages") or pages)
        except (TypeError, ValueError):
            pages = page
        page += 1
        time.sleep(0.05)
    return rows


def build_industrial_capital_signal(
    plan_rows: list[dict[str, Any]],
    shareholder_rows: list[dict[str, Any]],
    market_cap: float | None,
) -> dict[str, Any]:
    daily: dict[str, dict[str, float]] = {}
    company_buybacks: dict[str, float] = {}
    seen_plans: set[str] = set()
    for row in plan_rows:
        plan_code = str(row.get("REPURCODE") or "")
        if plan_code and plan_code in seen_plans:
            continue
        if plan_code:
            seen_plans.add(plan_code)
        trade_date = str(row.get("DIM_TRADEDATE") or row.get("DIM_DATE") or "").split(" ")[0]
        upper = safe_float(row.get("REPURAMOUNTLIMIT") or row.get("JESX"))
        lower = safe_float(row.get("REPURAMOUNTLOWER") or row.get("JEXX"))
        if upper is not None and lower is not None:
            plan_amount = (upper + lower) / 2
        else:
            plan_amount = upper or lower
        actual_amount = safe_float(row.get("REPURAMOUNT"))
        if not trade_date or not any(value is not None and value > 0 for value in (plan_amount, actual_amount)):
            continue
        day = daily.setdefault(trade_date, {"buyback": 0.0, "increase": 0.0, "decrease": 0.0, "plan": 0.0})
        if plan_amount is not None and plan_amount > 0:
            day["plan"] += plan_amount
        if actual_amount is not None and actual_amount > 0:
            day["buyback"] += actual_amount
            name = str(row.get("SECURITYSHORTNAME") or row.get("DIM_SCODE") or "回购")
            company_buybacks[name] = company_buybacks.get(name, 0.0) + actual_amount

    seen_changes: set[tuple[Any, ...]] = set()
    eligible_shareholder_changes = 0
    priced_shareholder_changes = 0
    for row in shareholder_rows:
        trade_date = str(row.get("TRADE_DATE") or row.get("END_DATE") or "").split(" ")[0]
        direction = str(row.get("DIRECTION") or "")
        change_num = safe_float(row.get("CHANGE_NUM"))
        price = (
            safe_float(row.get("TRADE_AVERAGE_PRICE"))
            or safe_float(row.get("REAL_PRICE"))
            or safe_float(row.get("CLOSE_PRICE"))
        )
        dedupe_key = (
            row.get("SECURITY_CODE"), row.get("HOLDER_NAME"), row.get("START_DATE"), row.get("END_DATE"),
            direction, change_num,
        )
        if dedupe_key in seen_changes:
            continue
        seen_changes.add(dedupe_key)
        if not trade_date or change_num is None or change_num == 0:
            continue
        eligible_shareholder_changes += 1
        if price is None or price <= 0:
            continue
        priced_shareholder_changes += 1
        amount = abs(change_num) * 10_000 * price
        day = daily.setdefault(trade_date, {"buyback": 0.0, "increase": 0.0, "decrease": 0.0, "plan": 0.0})
        if "减" in direction:
            day["decrease"] += amount
        elif "增" in direction:
            day["increase"] += amount

    all_dates = sorted(daily)
    try:
        cutoff = (date.fromisoformat(all_dates[-1]) - timedelta(days=29)).isoformat()
        dates = [item for item in all_dates if item >= cutoff]
    except (IndexError, ValueError):
        dates = all_dates[-35:]
    if not dates:
        return empty_signal_card(
            "industrial_capital",
            "产业资本披露",
            "最近窗口未取得回购方案、已回购金额或股东增减持数据。",
            source="东方财富公司行为数据",
            source_url=EASTMONEY_BUYBACK_URL,
        )
    buybacks = [daily[item]["buyback"] for item in dates]
    plans = [daily[item]["plan"] for item in dates]
    insider_net = [daily[item]["increase"] - daily[item]["decrease"] for item in dates]
    net_absorption = [buyback + insider for buyback, insider in zip(buybacks, insider_net)]
    window_buyback = sum(buybacks)
    window_plan = sum(plans)
    window_insider = sum(insider_net)
    window_net = sum(net_absorption)
    buyback_ratio = window_buyback / market_cap * 100 if market_cap and market_cap > 0 else None
    plan_ratio = window_plan / market_cap * 100 if market_cap and market_cap > 0 else None
    shareholder_price_coverage = (
        priced_shareholder_changes / eligible_shareholder_changes * 100
        if eligible_shareholder_changes > 0
        else None
    )
    top_buybacks = sorted(company_buybacks.items(), key=lambda item: item[1], reverse=True)[:5]

    return {
        "id": "industrial_capital",
        "title": "产业资本披露",
        "eyebrow": "回购与增减持",
        "description": "把回购方案、项目累计已回购额和股东增减持分开，观察产业资本披露的边际变化。",
        "status": "ok",
        "dataTimestamp": dates[-1],
        "metrics": [
            signal_metric("近30日披露已回购累计额", round(window_buyback, 2), "cny"),
            signal_metric("近30日披露方案中值", round(window_plan, 2), "cny"),
            signal_metric("近30日截止股东净增持", round(window_insider, 2), "cny"),
            signal_metric("披露口径净吸收代理", round(window_net, 2), "cny"),
            signal_metric("披露已回购/总市值", round(buyback_ratio, 5) if buyback_ratio is not None else None, "pct"),
            signal_metric("方案中值/总市值", round(plan_ratio, 5) if plan_ratio is not None else None, "pct"),
            signal_metric("增减持估价覆盖", round(shareholder_price_coverage, 2) if shareholder_price_coverage is not None else None, "pct"),
        ],
        "charts": [
            signal_chart(
                "industrial-net-absorption",
                "按披露日归集的已回购累计额、股东净增持与净吸收代理",
                "line",
                "亿元",
                [
                    {
                        "key": "buyback",
                        "label": "披露项目累计已回购额",
                        "color": "#2563eb",
                        "points": [{"label": item, "value": round(value / 100_000_000, 3)} for item, value in zip(dates, buybacks)],
                    },
                    {
                        "key": "insider",
                        "label": "股东净增持",
                        "color": "#f59e0b",
                        "points": [{"label": item, "value": round(value / 100_000_000, 3)} for item, value in zip(dates, insider_net)],
                    },
                    {
                        "key": "net",
                        "label": "披露口径净吸收代理",
                        "color": "#7c3aed",
                        "points": [{"label": item, "value": round(value / 100_000_000, 3)} for item, value in zip(dates, net_absorption)],
                    },
                ],
            ),
            signal_chart(
                "buyback-plan-ratio",
                "披露方案金额中值 / 当前A股总市值",
                "line",
                "%",
                [
                    {
                        "key": "planRatio",
                        "label": "方案中值占比",
                        "color": "#0f766e",
                        "points": [
                            {
                                "label": item,
                                "value": round(value / market_cap * 100, 6) if market_cap and market_cap > 0 else 0,
                            }
                            for item, value in zip(dates, plans)
                        ],
                    }
                ],
            ),
        ],
        "details": [
            {"label": name, "value": round(amount, 2), "format": "cny", "note": "最新披露的项目累计已回购额"}
            for name, amount in top_buybacks
        ],
        "source": "东方财富 Choice 回购全览与股东增减持",
        "sourceUrl": EASTMONEY_BUYBACK_URL,
        "sourceBadge": "公告聚合 · 披露口径",
        "cadence": "公告更新",
        "note": "回购 REPURAMOUNT 为各项目最新公告披露的累计已回购额，并按该项目最新事件日归集，不代表该日或近30日实际成交额；方案金额优先取计划上下限中值。股东增减持按变动截止日归集，CHANGE_NUM 单位为万股，金额按成交均价估算（缺失时用收盘价）。净吸收仅是披露口径代理，方案金额不计入净吸收；占比统一使用当前A股总市值。",
    }


def fetch_industrial_capital_signal_sync(timeout: float, market_cap: float | None) -> dict[str, Any]:
    start_date = (datetime.now(CN_TZ).date() - timedelta(days=50)).isoformat()
    with new_browser_session() as session:
        plans = fetch_eastmoney_report_rows_sync(
            session,
            timeout,
            report_name="RPTA_WEB_GETHGLIST_NEW",
            sort_column="DIM_TRADEDATE",
            filter_text=f"(DIM_TRADEDATE>='{start_date}')",
            referer=EASTMONEY_BUYBACK_URL,
        )
        shareholder_changes = fetch_eastmoney_report_rows_sync(
            session,
            timeout,
            report_name="RPT_SHARE_HOLDER_INCREASE",
            sort_column="TRADE_DATE",
            filter_text=f"(TRADE_DATE>='{start_date}')",
            referer=EASTMONEY_SHAREHOLDER_CHANGE_URL,
        )
    return build_industrial_capital_signal(plans, shareholder_changes, market_cap)


def build_funding_signal(records: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for row in records:
        values = row.get("frValueMap") or {}
        trade_date = str(values.get("date") or row.get("lfiProducDate") or "")
        fr007 = safe_float(values.get("FR007"))
        fdr007 = safe_float(values.get("FDR007"))
        if not trade_date or fr007 is None or fdr007 is None:
            continue
        points.append({"date": trade_date, "fr007": fr007, "fdr007": fdr007, "spreadBp": (fr007 - fdr007) * 100})
    points.sort(key=lambda item: item["date"])
    points = points[-30:]
    if not points:
        return empty_signal_card(
            "funding",
            "资金价格",
            "中国货币网回购定盘利率接口未返回 FR007/FDR007。",
            source="中国货币网",
            source_url=CHINA_MONEY_REPO_URL,
        )
    latest = points[-1]
    spreads = [item["spreadBp"] for item in points]
    return {
        "id": "funding",
        "title": "资金价格",
        "eyebrow": "银行间流动性",
        "description": "FR007 相对 FDR007 的利差可反映非银融资压力是否边际抬升。",
        "status": "ok",
        "dataTimestamp": latest["date"],
        "metrics": [
            signal_metric("FR007", round(latest["fr007"], 4), "pct"),
            signal_metric("FDR007", round(latest["fdr007"], 4), "pct"),
            signal_metric("FR-FDR利差", round(latest["spreadBp"], 2), "bp"),
            signal_metric("窗口利差中位数", round(statistics.median(spreads), 2), "bp"),
        ],
        "charts": [
            signal_chart(
                "funding-rates",
                "7天回购定盘利率",
                "line",
                "%",
                [
                    {
                        "key": "fr007",
                        "label": "FR007",
                        "color": "#dc2626",
                        "points": [{"label": item["date"], "value": round(item["fr007"], 4)} for item in points],
                    },
                    {
                        "key": "fdr007",
                        "label": "FDR007",
                        "color": "#2563eb",
                        "points": [{"label": item["date"], "value": round(item["fdr007"], 4)} for item in points],
                    },
                ],
            )
        ],
        "details": [],
        "source": "中国货币网回购定盘利率",
        "sourceUrl": CHINA_MONEY_REPO_URL,
        "sourceBadge": "中国货币网官方 · 原始值",
        "cadence": "交易日上午11:30后",
        "note": "采用官方 FR007/FDR007 定盘利率。二者分别以 R007、DR007 上午成交样本编制，比直接混用不同时间点的全天加权价更可比。",
    }


def fetch_funding_signal_sync(timeout: float) -> dict[str, Any]:
    end_date = datetime.now(CN_TZ).date()
    start_date = end_date - timedelta(days=45)
    with new_browser_session() as session:
        warm_browser_session(session, CHINA_MONEY_REPO_URL, timeout)
        response = session.post(
            CHINA_MONEY_REPO_HISTORY_API,
            params={"lang": "CN", "startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
            data=b"",
            headers={
                "User-Agent": random_user_agent(),
                "Referer": CHINA_MONEY_REPO_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=max(timeout, 18),
        )
        response.raise_for_status()
        records = response.json().get("records") or []
    return build_funding_signal(records)


def has_stock_payload(data: dict[str, Any]) -> bool:
    markets = data.get("markets") or []
    if any(market.get("marketCap") or market.get("indices") for market in markets):
        return True
    if industry_financing_trend_has_data(data.get("industryFinancingTrend")):
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


def ensure_industry_financing_group_cache_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_industry_financing_group_cache (
                industry TEXT PRIMARY KEY,
                saved_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def load_industry_financing_group_cache_sync(
    db_path: Path,
    parent_industry: str,
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_industry_financing_group_cache_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM stock_industry_financing_group_cache WHERE industry = ?",
            (parent_industry,),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def save_industry_financing_group_cache_sync(
    db_path: Path,
    parent_industry: str,
    payload: dict[str, Any],
) -> None:
    ensure_industry_financing_group_cache_table(db_path)
    saved_at = str(payload.get("savedAt") or datetime.now(UTC).isoformat())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stock_industry_financing_group_cache (industry, saved_at, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(industry) DO UPDATE SET
                saved_at = excluded.saved_at,
                payload_json = excluded.payload_json
            """,
            (parent_industry, saved_at, json.dumps(payload, ensure_ascii=False)),
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
