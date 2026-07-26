from __future__ import annotations

import asyncio
import copy
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .request_coordinator import coordinate_httpx_client

from .commodity_service import load_config, resolve_sqlite_path

CONSUMPTION_CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
CONSUMPTION_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
CONSUMPTION_SCHEMA_VERSION = 3
SOCIAL_RETAIL_CATEGORY = "社零总览"
SOCIAL_RETAIL_SOURCE_URL = "https://www.stats.gov.cn/sj/zxfb/202606/t20260616_1963949.html"

CONSUMPTION_CHANNELS: dict[str, tuple[str, str]] = {
    "total_retail": ("total", "社零总量"),
    "total_retail_ytd": ("total", "累计社零"),
    "retail_ex_auto": ("offline", "除汽车外"),
    "limited_retail": ("offline", "限额以上"),
    "goods_retail": ("offline", "商品零售"),
    "catering": ("offline", "餐饮"),
    "online_retail": ("online", "线上电商"),
    "online_goods": ("online", "线上商品"),
    "online_services": ("online", "线上服务"),
    "offline_retail_estimated": ("offline", "线下估算"),
}

NBS_RELEASE_INDEXES = [
    "https://www.stats.gov.cn/sj/zxfb/index.html",
    "https://www.stats.gov.cn/sj/zxfbhjd/index.html",
]
CUSTOMS_INDEX = "https://www.customs.gov.cn/customs/302249/zfxxgk/fdzdgknr/302274/index.html"

OFFICIAL_TREND_HISTORY: dict[str, list[dict[str, Any]]] = {
    "total_retail": [
        {"period": "2025-09", "periodLabel": "9月", "value": 41971, "yoy": 3.0},
        {"period": "2025-10", "periodLabel": "10月", "value": 46291, "yoy": 2.9},
        {"period": "2025-11", "periodLabel": "11月", "value": 43898, "yoy": 1.3},
        {"period": "2025-12", "periodLabel": "12月", "value": 45136, "yoy": 0.9, "mom": -0.12},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 86079, "yoy": 2.8},
        {"period": "2026-03", "periodLabel": "3月", "value": 41616, "yoy": 1.7},
        {"period": "2026-04", "periodLabel": "4月", "value": 37247, "yoy": 0.2, "mom": -0.48},
    ],
    "grain_food": [
        {"period": "2025-09", "periodLabel": "9月", "value": 2221, "yoy": 6.3},
        {"period": "2025-10", "periodLabel": "10月", "value": 2068, "yoy": 9.1},
        {"period": "2025-11", "periodLabel": "11月", "value": 2060, "yoy": 6.1},
        {"period": "2025-12", "periodLabel": "12月", "value": 2323, "yoy": 3.9},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 4507, "yoy": 10.2},
        {"period": "2026-03", "periodLabel": "3月", "value": 2058, "yoy": 9.5},
        {"period": "2026-04", "periodLabel": "4月", "value": 1806, "yoy": 4.1},
    ],
    "beverages": [
        {"period": "2025-09", "periodLabel": "9月", "value": 308, "yoy": -0.8},
        {"period": "2025-10", "periodLabel": "10月", "value": 282, "yoy": 7.1},
        {"period": "2025-11", "periodLabel": "11月", "value": 269, "yoy": 2.9},
        {"period": "2025-12", "periodLabel": "12月", "value": 275, "yoy": 1.7},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 553, "yoy": 6.0},
        {"period": "2026-03", "periodLabel": "3月", "value": 264, "yoy": 8.2},
        {"period": "2026-04", "periodLabel": "4月", "value": 248, "yoy": 3.6},
    ],
    "catering": [
        {"period": "2025-09", "periodLabel": "9月", "value": 4509, "yoy": 0.9},
        {"period": "2025-10", "periodLabel": "10月", "value": 5199, "yoy": 3.8},
        {"period": "2025-11", "periodLabel": "11月", "value": 6057, "yoy": 3.2},
        {"period": "2025-12", "periodLabel": "12月", "value": 5738, "yoy": 2.2},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 10264, "yoy": 4.8},
        {"period": "2026-03", "periodLabel": "3月", "value": 4359, "yoy": 2.9},
        {"period": "2026-04", "periodLabel": "4月", "value": 4260, "yoy": 2.2},
    ],
    "medicine": [
        {"period": "2025-09", "periodLabel": "9月", "value": 637, "yoy": 1.9},
        {"period": "2025-10", "periodLabel": "10月", "value": 612, "yoy": 3.6},
        {"period": "2025-11", "periodLabel": "11月", "value": 660, "yoy": 4.9},
        {"period": "2025-12", "periodLabel": "12月", "value": 711, "yoy": 1.2},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 1156, "yoy": 0.7},
        {"period": "2026-03", "periodLabel": "3月", "value": 668, "yoy": 5.7},
        {"period": "2026-04", "periodLabel": "4月", "value": 601, "yoy": 4.2},
    ],
    "auto_retail": [
        {"period": "2025-09", "periodLabel": "9月", "value": 4711, "yoy": 1.6},
        {"period": "2025-10", "periodLabel": "10月", "value": 4255, "yoy": -6.6},
        {"period": "2025-11", "periodLabel": "11月", "value": 4454, "yoy": -8.3},
        {"period": "2025-12", "periodLabel": "12月", "value": 5482, "yoy": -5.0},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 6252, "yoy": -7.3},
        {"period": "2026-03", "periodLabel": "3月", "value": 3741, "yoy": -11.8},
        {"period": "2026-04", "periodLabel": "4月", "value": 3029, "yoy": -15.3},
    ],
    "home_appliance": [
        {"period": "2025-09", "periodLabel": "9月", "value": 904, "yoy": 3.3},
        {"period": "2025-10", "periodLabel": "10月", "value": 891, "yoy": -14.6},
        {"period": "2025-11", "periodLabel": "11月", "value": 1000, "yoy": -19.4},
        {"period": "2025-12", "periodLabel": "12月", "value": 971, "yoy": -18.7},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 1572, "yoy": 3.3},
        {"period": "2026-03", "periodLabel": "3月", "value": 938, "yoy": -5.0},
        {"period": "2026-04", "periodLabel": "4月", "value": 776, "yoy": -15.1},
    ],
    "furniture": [
        {"period": "2025-09", "periodLabel": "9月", "value": 176, "yoy": 16.2},
        {"period": "2025-10", "periodLabel": "10月", "value": 179, "yoy": 9.6},
        {"period": "2025-11", "periodLabel": "11月", "value": 195, "yoy": -3.8},
        {"period": "2025-12", "periodLabel": "12月", "value": 207, "yoy": -2.2},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 276, "yoy": 8.8},
        {"period": "2026-03", "periodLabel": "3月", "value": 149, "yoy": -8.7},
        {"period": "2026-04", "periodLabel": "4月", "value": 134, "yoy": -10.4},
    ],
    "building_materials": [
        {"period": "2025-09", "periodLabel": "9月", "value": 147, "yoy": -0.1},
        {"period": "2025-10", "periodLabel": "10月", "value": 144, "yoy": -8.3},
        {"period": "2025-11", "periodLabel": "11月", "value": 149, "yoy": -17.0},
        {"period": "2025-12", "periodLabel": "12月", "value": 172, "yoy": -11.8},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 204, "yoy": -2.2},
        {"period": "2026-03", "periodLabel": "3月", "value": 112, "yoy": -9.0},
        {"period": "2026-04", "periodLabel": "4月", "value": 101, "yoy": -13.8},
    ],
    "real_estate_sales": [
        {"period": "2025-09", "periodLabel": "1-9月累计", "value": 63040, "yoy": -7.9},
        {"period": "2025-10", "periodLabel": "1-10月累计", "value": 69017, "yoy": -9.6},
        {"period": "2025-11", "periodLabel": "1-11月累计", "value": 75130, "yoy": -11.1},
        {"period": "2025-12", "periodLabel": "全年", "value": 83937, "yoy": -12.6},
        {"period": "2026-02", "periodLabel": "1-2月累计", "value": 8186, "yoy": -20.2},
        {"period": "2026-03", "periodLabel": "1-3月累计", "value": 17262, "yoy": -16.7},
        {"period": "2026-04", "periodLabel": "1-4月累计", "value": 23000, "yoy": -14.6},
    ],
    "pork_cpi": [
        {"period": "2025-09", "periodLabel": "9月", "yoy": -17.0, "mom": -0.7},
        {"period": "2025-10", "periodLabel": "10月", "yoy": -16.0, "mom": -2.5},
        {"period": "2025-11", "periodLabel": "11月", "yoy": -15.0, "mom": -2.2},
        {"period": "2025-12", "periodLabel": "12月", "yoy": -14.6, "mom": -1.7},
        {"period": "2026-01", "periodLabel": "1月", "yoy": -13.7, "mom": 1.2},
        {"period": "2026-02", "periodLabel": "2月", "yoy": -8.6, "mom": 4.0},
        {"period": "2026-03", "periodLabel": "3月", "yoy": -11.5, "mom": -7.3},
        {"period": "2026-04", "periodLabel": "4月", "yoy": -15.2, "mom": -5.7},
        {"period": "2026-05", "periodLabel": "5月", "yoy": -16.1, "mom": -1.6},
    ],
    "egg_cpi": [
        {"period": "2025-09", "periodLabel": "9月", "yoy": -11.9, "mom": 2.7},
        {"period": "2025-10", "periodLabel": "10月", "yoy": -11.6, "mom": -1.7},
        {"period": "2025-11", "periodLabel": "11月", "yoy": -12.5, "mom": -1.8},
        {"period": "2025-12", "periodLabel": "12月", "yoy": -12.7, "mom": 0.0},
        {"period": "2026-01", "periodLabel": "1月", "yoy": -9.2, "mom": 2.7},
        {"period": "2026-02", "periodLabel": "2月", "yoy": -2.9, "mom": 1.3},
        {"period": "2026-03", "periodLabel": "3月", "yoy": -3.1, "mom": -2.7},
        {"period": "2026-04", "periodLabel": "4月", "yoy": 0.5, "mom": 2.7},
        {"period": "2026-05", "periodLabel": "5月", "yoy": 6.6, "mom": 5.0},
    ],
    "medical_cpi": [
        {"period": "2025-09", "periodLabel": "9月", "yoy": 1.1, "mom": 0.2},
        {"period": "2025-10", "periodLabel": "10月", "yoy": 1.4, "mom": 0.3},
        {"period": "2025-11", "periodLabel": "11月", "yoy": 1.6, "mom": 0.1},
        {"period": "2025-12", "periodLabel": "12月", "yoy": 1.8, "mom": 0.1},
        {"period": "2026-01", "periodLabel": "1月", "yoy": 1.7, "mom": 0.3},
        {"period": "2026-02", "periodLabel": "2月", "yoy": 1.9, "mom": 0.1},
        {"period": "2026-03", "periodLabel": "3月", "yoy": 1.9, "mom": 0.1},
        {"period": "2026-04", "periodLabel": "4月", "yoy": 2.2, "mom": 0.3},
        {"period": "2026-05", "periodLabel": "5月", "yoy": 2.1, "mom": 0.0},
    ],
}


def row(
    id: str,
    category: str,
    metric: str,
    segment: str,
    geography: str,
    period: str,
    value: float | None,
    unit: str,
    yoy: float | None,
    mom: float | None,
    source: str,
    source_url: str,
    note: str,
    history: list[dict[str, Any]],
    period_label: str | None = None,
) -> dict[str, Any]:
    channel, channel_label = CONSUMPTION_CHANNELS.get(id, ("", ""))
    return {
        "id": id,
        "category": category,
        "metric": metric,
        "segment": segment,
        "segmentLabel": "必选" if segment == "required" else "可选",
        "geography": geography,
        "geographyLabel": "境内" if geography == "domestic" else "海外/进口",
        "channel": channel,
        "channelLabel": channel_label,
        "period": period,
        "periodLabel": period_label or period,
        "value": value,
        "unit": unit,
        "yoy": yoy,
        "mom": mom,
        "source": source,
        "sourceUrl": source_url,
        "note": note,
        "history": history,
    }


FALLBACK_ROWS: list[dict[str, Any]] = [
    row(
        "total_retail",
        SOCIAL_RETAIL_CATEGORY,
        "社会消费品零售总额",
        "optional",
        "domestic",
        "2026-05",
        41090,
        "亿元",
        -0.6,
        -0.38,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "社零当月口径；5月环比来自国家统计局社零发布稿。",
        [
            {"period": "2026-02", "periodLabel": "1-2月累计", "value": 86079, "yoy": 2.8, "mom": None},
            {"period": "2026-03", "periodLabel": "3月", "value": 41616, "yoy": 1.7, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": 37247, "yoy": 0.2, "mom": -0.48},
            {"period": "2026-05", "periodLabel": "5月", "value": 41090, "yoy": -0.6, "mom": -0.38},
        ],
    ),
    row(
        "grain_food",
        "食品饮料",
        "限额以上粮油、食品类零售额",
        "required",
        "domestic",
        "2026-04",
        None,
        "亿元",
        8.6,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963732.html",
        "兜底使用国民经济发布稿提到的1-4月同比；抓取到社零明细表后会替换为当月值。",
        [
            {"period": "2026-02", "periodLabel": "1-2月累计", "value": None, "yoy": None, "mom": None},
            {"period": "2026-03", "periodLabel": "3月", "value": None, "yoy": None, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": None, "yoy": 8.6, "mom": None},
        ],
    ),
    row(
        "beverages",
        "食品饮料",
        "限额以上饮料类零售额",
        "required",
        "domestic",
        "2026-04",
        None,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "社零明细表口径。",
        [],
    ),
    row(
        "pork_cpi",
        "猪肉鸡蛋",
        "猪肉价格CPI",
        "required",
        "domestic",
        "2026-05",
        None,
        "%",
        -16.1,
        -1.6,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/202606/t20260610_1963923.html",
        "价格同比/环比，不是零售额；用于补足高频民生品类。",
        [
            {"period": "2026-03", "periodLabel": "3月", "value": None, "yoy": -11.5, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": None, "yoy": -15.2, "mom": None},
            {"period": "2026-05", "periodLabel": "5月", "value": None, "yoy": -16.1, "mom": -1.6},
        ],
    ),
    row(
        "egg_cpi",
        "猪肉鸡蛋",
        "蛋类价格CPI",
        "required",
        "domestic",
        "2026-05",
        None,
        "%",
        6.6,
        5.0,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/202606/t20260610_1963923.html",
        "国家统计局CPI食品分项，鸡蛋使用蛋类口径。",
        [
            {"period": "2026-03", "periodLabel": "3月", "value": None, "yoy": -3.1, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": None, "yoy": None, "mom": None},
            {"period": "2026-05", "periodLabel": "5月", "value": None, "yoy": 6.6, "mom": 5.0},
        ],
    ),
    row(
        "medicine",
        "医疗健康",
        "限额以上中西药品类零售额",
        "required",
        "domestic",
        "2026-04",
        None,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "社零明细表口径。",
        [],
    ),
    row(
        "medical_cpi",
        "医疗健康",
        "医疗保健CPI",
        "required",
        "domestic",
        "2026-05",
        None,
        "%",
        2.1,
        0.0,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/202606/t20260610_1963923.html",
        "价格口径，和药品零售额互补观察。",
        [{"period": "2026-05", "periodLabel": "5月", "value": None, "yoy": 2.1, "mom": 0.0}],
    ),
    row(
        "catering",
        SOCIAL_RETAIL_CATEGORY,
        "餐饮收入",
        "optional",
        "domestic",
        "2026-05",
        4605,
        "亿元",
        0.6,
        8.1,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "餐饮收入包含堂食和外卖；外卖单列需平台披露，页面以餐饮收入和网上服务零售额做代理观察。",
        [
            {"period": "2026-02", "periodLabel": "1-2月累计", "value": 10264, "yoy": 4.8, "mom": None},
            {"period": "2026-03", "periodLabel": "3月", "value": 4359, "yoy": 2.9, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": 4260, "yoy": 2.2, "mom": -2.27},
            {"period": "2026-05", "periodLabel": "5月", "value": 4605, "yoy": 0.6, "mom": 8.1},
        ],
    ),
    row(
        "online_services",
        SOCIAL_RETAIL_CATEGORY,
        "网上服务零售额",
        "optional",
        "domestic",
        "2026-05",
        30459,
        "亿元",
        7.6,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "1-5月累计口径，覆盖平台服务消费；不是纯外卖口径。",
        [
            {"period": "2026-03", "periodLabel": "1-3月累计", "value": 18160, "yoy": 8.8, "mom": None},
            {"period": "2026-04", "periodLabel": "1-4月累计", "value": 24123, "yoy": 8.3, "mom": None},
            {"period": "2026-05", "periodLabel": "1-5月累计", "value": 30459, "yoy": 7.6, "mom": None},
        ],
        period_label="1-5月累计",
    ),
    row(
        "total_retail_ytd",
        SOCIAL_RETAIL_CATEGORY,
        "社会消费品零售总额（累计）",
        "optional",
        "domestic",
        "2026-05",
        206031,
        "亿元",
        1.4,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "社零累计口径，用来和线上电商、线下估算口径放在同一张表里比较。",
        [
            {"period": "2026-02", "periodLabel": "1-2月累计", "value": 86079, "yoy": 2.8, "mom": None},
            {"period": "2026-03", "periodLabel": "1-3月累计", "value": None, "yoy": 2.4, "mom": None},
            {"period": "2026-04", "periodLabel": "1-4月累计", "value": None, "yoy": 1.9, "mom": None},
            {"period": "2026-05", "periodLabel": "1-5月累计", "value": 206031, "yoy": 1.4, "mom": None},
        ],
        period_label="1-5月累计",
    ),
    row(
        "retail_ex_auto",
        SOCIAL_RETAIL_CATEGORY,
        "除汽车以外的消费品零售额",
        "optional",
        "domestic",
        "2026-05",
        37781,
        "亿元",
        1.1,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "社零扣除汽车口径，辅助观察一般消费强弱。",
        [
            {"period": "2026-03", "periodLabel": "3月", "value": None, "yoy": 3.2, "mom": None},
            {"period": "2026-04", "periodLabel": "4月", "value": None, "yoy": 1.8, "mom": None},
            {"period": "2026-05", "periodLabel": "5月", "value": 37781, "yoy": 1.1, "mom": None},
        ],
    ),
    row(
        "limited_retail",
        SOCIAL_RETAIL_CATEGORY,
        "限额以上单位消费品零售额",
        "optional",
        "domestic",
        "2026-05",
        15609,
        "亿元",
        -4.9,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "限额以上单位当月口径，偏大中型零售主体。",
        [{"period": "2026-05", "periodLabel": "5月", "value": 15609, "yoy": -4.9, "mom": None}],
    ),
    row(
        "goods_retail",
        SOCIAL_RETAIL_CATEGORY,
        "商品零售额",
        "optional",
        "domestic",
        "2026-05",
        36485,
        "亿元",
        -0.7,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "社零中商品零售当月口径，和餐饮收入分开观察。",
        [{"period": "2026-05", "periodLabel": "5月", "value": 36485, "yoy": -0.7, "mom": None}],
    ),
    row(
        "online_retail",
        SOCIAL_RETAIL_CATEGORY,
        "网上商品和服务零售额",
        "optional",
        "domestic",
        "2026-05",
        83177,
        "亿元",
        5.9,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "1-5月累计口径，覆盖网上商品和服务交易。",
        [
            {"period": "2026-03", "periodLabel": "1-3月累计", "value": None, "yoy": 8.0, "mom": None},
            {"period": "2026-04", "periodLabel": "1-4月累计", "value": None, "yoy": 6.6, "mom": None},
            {"period": "2026-05", "periodLabel": "1-5月累计", "value": 83177, "yoy": 5.9, "mom": None},
        ],
        period_label="1-5月累计",
    ),
    row(
        "online_goods",
        SOCIAL_RETAIL_CATEGORY,
        "网上商品零售额",
        "optional",
        "domestic",
        "2026-05",
        52718,
        "亿元",
        5.0,
        None,
        "国家统计局",
        SOCIAL_RETAIL_SOURCE_URL,
        "1-5月累计口径，原实物商品网上零售额调整为网上商品零售额。",
        [
            {"period": "2026-03", "periodLabel": "1-3月累计", "value": None, "yoy": 7.5, "mom": None},
            {"period": "2026-04", "periodLabel": "1-4月累计", "value": None, "yoy": 5.7, "mom": None},
            {"period": "2026-05", "periodLabel": "1-5月累计", "value": 52718, "yoy": 5.0, "mom": None},
        ],
        period_label="1-5月累计",
    ),
    row(
        "offline_retail_estimated",
        SOCIAL_RETAIL_CATEGORY,
        "线下/非网上零售额估算",
        "optional",
        "domestic",
        "2026-05",
        122854,
        "亿元",
        None,
        None,
        "国家统计局 / 计算",
        SOCIAL_RETAIL_SOURCE_URL,
        "由社零累计扣网上商品和服务零售额得到；因网上服务统计范围调整，只作线下规模观察。",
        [{"period": "2026-05", "periodLabel": "1-5月累计", "value": 122854, "yoy": None, "mom": None}],
        period_label="1-5月累计",
    ),
    row(
        "auto_retail",
        "汽车",
        "限额以上汽车类零售额",
        "optional",
        "domestic",
        "2026-04",
        3029,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "当月值可由社零总额扣除除汽车外消费品零售额得到；明细表抓取成功后会替换同比。",
        [{"period": "2026-04", "periodLabel": "4月", "value": 3029, "yoy": None, "mom": None}],
    ),
    row(
        "auto_sales_caam",
        "汽车",
        "汽车销量",
        "optional",
        "domestic",
        "2026-05",
        262.9,
        "万辆",
        -2.1,
        4.1,
        "中国汽车工业协会 / 权威媒体披露",
        "https://finance.sina.com.cn/tech/digi/2026-06-13/doc-inicferc1821366.shtml",
        "中汽协产销口径，补充社零汽车金额。",
        [{"period": "2026-05", "periodLabel": "5月", "value": 262.9, "yoy": -2.1, "mom": 4.1}],
    ),
    row(
        "home_appliance",
        "家用电器",
        "限额以上家用电器和音像器材类零售额",
        "optional",
        "domestic",
        "2026-04",
        None,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "社零明细表口径。",
        [],
    ),
    row(
        "real_estate_sales",
        "房地产",
        "新建商品房销售额",
        "optional",
        "domestic",
        "2026-04",
        23000,
        "亿元",
        -14.6,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963729.html",
        "房地产销售为累计口径，和月度社零品类分开解读。",
        [
            {"period": "2026-02", "periodLabel": "1-2月累计", "value": 8186, "yoy": -20.2, "mom": None},
            {"period": "2026-03", "periodLabel": "1-3月累计", "value": 17262, "yoy": -16.7, "mom": None},
            {"period": "2026-04", "periodLabel": "1-4月累计", "value": 23000, "yoy": -14.6, "mom": None},
        ],
        period_label="1-4月累计",
    ),
    row(
        "furniture",
        "房地产",
        "限额以上家具类零售额",
        "optional",
        "domestic",
        "2026-04",
        None,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "地产后周期消费。",
        [],
    ),
    row(
        "building_materials",
        "房地产",
        "限额以上建筑及装潢材料类零售额",
        "optional",
        "domestic",
        "2026-04",
        None,
        "亿元",
        None,
        None,
        "国家统计局",
        "https://www.stats.gov.cn/sj/zxfbhjd/202605/t20260518_1963727.html",
        "地产后周期消费。",
        [],
    ),
    row(
        "total_imports",
        "海外消费",
        "货物贸易进口",
        "optional",
        "overseas",
        "2026-05",
        8.77,
        "万亿元",
        20.5,
        None,
        "海关总署",
        "https://www.customs.gov.cn/customs/2026-06/09/article_2026060908295994113.html",
        "1-5月累计进口，作为海外供给/进口消费观察总量。",
        [{"period": "2026-05", "periodLabel": "1-5月累计", "value": 8.77, "yoy": 20.5, "mom": None}],
        period_label="1-5月累计",
    ),
    row(
        "consumer_goods_import",
        "海外消费",
        "消费品进口",
        "required",
        "overseas",
        "2026-02",
        None,
        "亿元",
        8.3,
        None,
        "海关总署",
        "https://www.customs.gov.cn/customs/302249/zfxxgk/fdzdgknr/302274/index.html",
        "海关统计新闻口径；后续明细表可补金额。",
        [{"period": "2026-02", "periodLabel": "1-2月累计", "value": None, "yoy": 8.3, "mom": None}],
        period_label="1-2月累计",
    ),
    row(
        "meat_import",
        "猪肉鸡蛋",
        "肉类进口",
        "required",
        "overseas",
        "2026-05",
        None,
        "万吨",
        None,
        None,
        "海关总署",
        "https://www.customs.gov.cn/customs/302249/zfxxgk/fdzdgknr/302274/302275/index.html",
        "待接入海关月度商品量值表；先保留观察位。",
        [],
    ),
    row(
        "auto_exports",
        "汽车",
        "汽车出口",
        "optional",
        "overseas",
        "2026-05",
        None,
        "万辆",
        68.7,
        None,
        "中国汽车工业协会 / 权威媒体披露",
        "https://finance.sina.com.cn/tech/digi/2026-06-13/doc-inicferc1821366.shtml",
        "海外需求观察，不计入境内消费。",
        [{"period": "2026-05", "periodLabel": "5月", "value": None, "yoy": 68.7, "mom": None}],
    ),
]


def fallback_source_url(row_id: str) -> str:
    row_data = next((item for item in FALLBACK_ROWS if item.get("id") == row_id), None)
    return str(row_data.get("sourceUrl") or "") if row_data else ""


async def get_consumption(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    async with CONSUMPTION_CACHE_LOCK:
        if (
            not force
            and not refresh
            and CONSUMPTION_CACHE["data"]
            and CONSUMPTION_CACHE["data"].get("schemaVersion") == CONSUMPTION_SCHEMA_VERSION
            and datetime.now(UTC) < CONSUMPTION_CACHE["expires_at"]
        ):
            cached = dict(CONSUMPTION_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = await load_latest_consumption(db_path)
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == CONSUMPTION_SCHEMA_VERSION)
    stored_is_fresh = bool(stored_schema_valid and parse_dt(stored.get("expiresAt", "")) > datetime.now(UTC))
    if not force and stored and stored_schema_valid and ((allow_stale and not refresh) or stored_is_fresh):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with CONSUMPTION_CACHE_LOCK:
            CONSUMPTION_CACHE["data"] = stored
            CONSUMPTION_CACHE["expires_at"] = parse_dt(stored.get("expiresAt", ""))
        return stored

    rows = copy.deepcopy(FALLBACK_ROWS)
    errors: list[str] = []
    timeout = float(fetch_config.get("request_timeout_seconds", 8))
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout), verify=False) as client:
        coordinate_httpx_client(client)
        tasks = [
            fetch_nbs_social_retail(client, rows),
            fetch_nbs_cpi(client, rows),
            fetch_nbs_real_estate(client, rows),
            fetch_customs_imports(client, rows),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                message = str(result)
                if message:
                    errors.append(message)
            elif result:
                errors.extend([message for message in result if message])

    add_derived_consumption_rows(rows)
    backfill_official_history(rows)
    enrich_rows(rows)
    now = datetime.now(UTC)
    data = {
        "schemaVersion": CONSUMPTION_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": bool(rows),
        "source": "国家统计局 / 海关总署 / 中国汽车工业协会 / 权威媒体",
        "cadence": "半小时最多刷新一次；以官方月度发布为主，外卖等平台细分项以代理指标和权威披露补充",
        "errors": errors,
        "summary": build_summary(rows),
        "sections": build_sections(rows),
        "rows": rows,
    }
    await save_latest_consumption(db_path, data)
    async with CONSUMPTION_CACHE_LOCK:
        CONSUMPTION_CACHE["data"] = data
        CONSUMPTION_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


async def fetch_nbs_social_retail(client: httpx.AsyncClient, rows: list[dict[str, Any]]) -> list[str]:
    url = await find_nbs_release(client, "社会消费品零售总额", fallback_source_url("total_retail"))
    html = await fetch_text(client, url, "国家统计局社零发布")
    period, period_label = extract_period(html)
    updates = parse_social_retail_rows(html, period, period_label, url)

    for row_id, update in updates.items():
        merge_row(rows, row_id, update)

    if "total_retail" not in updates:
        total = first_metric(
            clean_html(html),
            [
                r"(\d{1,2})\s*月份，社会消费品零售总额\s*([\d,.]+)\s*亿元，同比(增长|下降)\s*([\d.]+)%",
            ],
        )
        if total:
            month, value, direction, yoy = total
            merge_row(
                rows,
                "total_retail",
                {
                    "period": period or f"{datetime.now(UTC).year}-{int(month):02d}",
                    "periodLabel": f"{int(month)}月",
                    "value": safe_float(value),
                    "yoy": signed_pct(direction, yoy),
                    "source": "国家统计局",
                    "sourceUrl": url,
                },
            )
    return []


async def fetch_nbs_cpi(client: httpx.AsyncClient, rows: list[dict[str, Any]]) -> list[str]:
    url = await find_nbs_release(client, "居民消费价格同比", fallback_source_url("pork_cpi"))
    html = await fetch_text(client, url, "国家统计局CPI发布")
    text = clean_html(html)
    period, period_label = extract_period(html)
    yoy_text, mom_text = split_yoy_mom_text(text)

    pork_yoy = extract_directional_pct(yoy_text, r"猪肉价格(上涨|下降)\s*([\d.]+)%")
    pork_mom = extract_directional_pct(mom_text, r"猪肉价格(上涨|下降)\s*([\d.]+)%")
    egg_yoy = extract_directional_pct(yoy_text, r"蛋类价格(上涨|下降)\s*([\d.]+)%")
    egg_mom = extract_directional_pct(mom_text, r"蛋类价格(上涨|下降)\s*([\d.]+)%")
    medical_yoy = extract_medical_yoy(yoy_text)
    medical_mom = 0.0 if "医疗保健价格均持平" in mom_text else extract_directional_pct(mom_text, r"医疗保健价格(?:分别)?(上涨|下降)\s*([\d.]+)%")

    update_common = {"period": period, "periodLabel": period_label, "source": "国家统计局", "sourceUrl": url}
    if pork_yoy is not None or pork_mom is not None:
        merge_row(rows, "pork_cpi", {**update_common, "yoy": pork_yoy, "mom": pork_mom})
    if egg_yoy is not None or egg_mom is not None:
        merge_row(rows, "egg_cpi", {**update_common, "yoy": egg_yoy, "mom": egg_mom})
    if medical_yoy is not None or medical_mom is not None:
        merge_row(rows, "medical_cpi", {**update_common, "yoy": medical_yoy, "mom": medical_mom})
    return []


async def fetch_nbs_real_estate(client: httpx.AsyncClient, rows: list[dict[str, Any]]) -> list[str]:
    url = await find_nbs_release(client, "房地产市场基本情况", fallback_source_url("real_estate_sales"))
    html = await fetch_text(client, url, "国家统计局房地产发布")
    text = clean_html(html)
    period, _ = extract_period(html)
    period_label = extract_cumulative_label(text) or "累计"
    match = re.search(r"新建商品房销售额\s*([\d,.]+)\s*亿元，(增长|下降)\s*([\d.]+)%", text)
    if match:
        value, direction, yoy = match.groups()
        merge_row(
            rows,
            "real_estate_sales",
            {
                "period": period,
                "periodLabel": period_label,
                "value": safe_float(value),
                "yoy": signed_pct(direction, yoy),
                "source": "国家统计局",
                "sourceUrl": url,
            },
        )
    return []


async def fetch_customs_imports(client: httpx.AsyncClient, rows: list[dict[str, Any]]) -> list[str]:
    url = await find_customs_release(client, "货物贸易进出口增长", fallback_source_url("total_imports"))
    html = await fetch_text(client, url, "海关总署发布")
    text = clean_html(html)
    period = extract_customs_period(text) or "2026-05"
    period_label = extract_customs_period_label(text) or "累计"
    match = re.search(r"进口\s*([\d.]+)\s*万亿元，增长\s*([\d.]+)%", text)
    if match:
        value, yoy = match.groups()
        merge_row(
            rows,
            "total_imports",
            {
                "period": period,
                "periodLabel": period_label,
                "value": safe_float(value),
                "yoy": safe_float(yoy),
                "source": "海关总署",
                "sourceUrl": url,
            },
        )
    consumer_yoy = extract_value_after(text, r"消费品进口增长\s*([\d.]+)%")
    if consumer_yoy is not None:
        merge_row(rows, "consumer_goods_import", {"period": period, "periodLabel": period_label, "yoy": consumer_yoy, "source": "海关总署", "sourceUrl": url})
    return []


def parse_social_retail_rows(html: str, period: str, period_label: str, source_url: str) -> dict[str, dict[str, Any]]:
    current_period_label = extract_social_retail_table_label(html) or period_label
    ytd_period_label = extract_cumulative_label(clean_html(html)) or period_label
    row_map = [
        ("社会消费品零售总额", [("total_retail", "month"), ("total_retail_ytd", "ytd")], True),
        ("除汽车以外的消费品零售额", [("retail_ex_auto", "month")], True),
        ("限额以上单位消费品零售额", [("limited_retail", "month")], True),
        ("网上商品零售额", [("online_goods", "ytd")], True),
        ("粮油、食品类", [("grain_food", "month")], False),
        ("饮料类", [("beverages", "month")], False),
        ("餐饮收入", [("catering", "month")], True),
        ("商品零售额", [("goods_retail", "month")], True),
        ("中西药品类", [("medicine", "month")], False),
        ("汽车类", [("auto_retail", "month")], False),
        ("家用电器和音像器材类", [("home_appliance", "month")], False),
        ("家具类", [("furniture", "month")], False),
        ("建筑及装潢材料类", [("building_materials", "month")], False),
    ]
    updates: dict[str, dict[str, Any]] = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells = [clean_html(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.I | re.S)]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3:
            continue
        name = normalize_label(cells[0])
        for label, targets, exact_only in row_map:
            expected = normalize_label(label)
            if expected == name or (not exact_only and expected in name):
                for row_id, mode in targets:
                    if mode == "ytd":
                        if len(cells) < 5:
                            continue
                        value = safe_float(cells[3])
                        yoy = safe_float(cells[4])
                        table_period_label = ytd_period_label
                    else:
                        value = safe_float(cells[1])
                        yoy = safe_float(cells[2])
                        table_period_label = current_period_label
                    updates[row_id] = {
                        "period": period,
                        "periodLabel": table_period_label,
                        "value": value,
                        "yoy": yoy,
                        "source": "国家统计局",
                        "sourceUrl": source_url,
                    }
                break

    text = clean_html(html)
    online_total = re.search(r"全国网上商品和服务零售额\s*([\d,.]+)\s*亿元，同比(增长|下降)\s*([\d.]+)%", text)
    if online_total:
        updates["online_retail"] = {
            "period": period,
            "periodLabel": ytd_period_label,
            "value": safe_float(online_total.group(1)),
            "yoy": signed_pct(online_total.group(2), online_total.group(3)),
            "source": "国家统计局",
            "sourceUrl": source_url,
        }
    online_goods = re.search(r"网上商品零售额\s*([\d,.]+)\s*亿元，(增长|下降)\s*([\d.]+)%", text)
    if online_goods:
        updates["online_goods"] = {
            "period": period,
            "periodLabel": ytd_period_label,
            "value": safe_float(online_goods.group(1)),
            "yoy": signed_pct(online_goods.group(2), online_goods.group(3)),
            "source": "国家统计局",
            "sourceUrl": source_url,
        }
    online = re.search(r"网上服务零售额\s*([\d,.]+)\s*亿元，(增长|下降)\s*([\d.]+)%", text)
    if online:
        updates["online_services"] = {
            "period": period,
            "periodLabel": ytd_period_label,
            "value": safe_float(online.group(1)),
            "yoy": signed_pct(online.group(2), online.group(3)),
            "source": "国家统计局",
            "sourceUrl": source_url,
        }
    return updates


def extract_social_retail_table_label(html: str) -> str:
    text = clean_html(html)
    match = re.search(r"\d{4}\s*年\s*(\d{1,2})\s*月份社会消费品零售总额主要数据", text)
    return f"{int(match.group(1))}月" if match else ""


def extract_medical_yoy(text: str) -> float | None:
    grouped = re.search(r"医疗保健价格分别(上涨|下降)\s*[\d.]+%、[\d.]+%和([\d.]+)%", text)
    if grouped:
        direction, value = grouped.groups()
        return signed_pct(direction, value)
    return extract_directional_pct(text, r"医疗保健价格(上涨|下降)\s*([\d.]+)%")


def add_derived_consumption_rows(rows: list[dict[str, Any]]) -> None:
    row_index = {item.get("id"): item for item in rows}
    total = row_index.get("total_retail_ytd")
    online = row_index.get("online_retail")
    if not total or not online:
        return
    total_value = safe_float(total.get("value"))
    online_value = safe_float(online.get("value"))
    if total_value is None or online_value is None:
        return
    period = str(total.get("period") or online.get("period") or "")
    period_label = str(total.get("periodLabel") or online.get("periodLabel") or period)
    merge_row(
        rows,
        "offline_retail_estimated",
        {
            "period": period,
            "periodLabel": period_label,
            "value": round(total_value - online_value, 2),
            "source": "国家统计局 / 计算",
            "sourceUrl": total.get("sourceUrl") or online.get("sourceUrl") or SOCIAL_RETAIL_SOURCE_URL,
        },
    )


async def find_nbs_release(client: httpx.AsyncClient, keyword: str, fallback_url: str) -> str:
    for index_url in NBS_RELEASE_INDEXES:
        try:
            html = await fetch_text(client, index_url, "国家统计局索引")
        except Exception:
            continue
        link = find_link(html, keyword, index_url)
        if link:
            return link
    return fallback_url


async def find_customs_release(client: httpx.AsyncClient, keyword: str, fallback_url: str) -> str:
    try:
        html = await fetch_text(client, CUSTOMS_INDEX, "海关总署索引")
    except Exception:
        return fallback_url
    return find_link(html, keyword, CUSTOMS_INDEX) or fallback_url


def find_link(html: str, keyword: str, base_url: str) -> str:
    for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
        text = clean_html(title)
        if keyword in text:
            return urljoin(base_url, href)
    return ""


async def fetch_text(client: httpx.AsyncClient, url: str, label: str) -> str:
    response = await client.get(url, headers={"User-Agent": user_agent(), "Accept": "text/html,application/xhtml+xml"})
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "utf-8"
    text = response.text
    if not text.strip():
        raise ValueError(f"{label}返回为空")
    return text


def merge_row(rows: list[dict[str, Any]], row_id: str, update: dict[str, Any]) -> None:
    target = next((row for row in rows if row.get("id") == row_id), None)
    if not target:
        return
    for key, value in update.items():
        if value is not None:
            target[key] = value
    append_history_point(target, update)


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


def backfill_official_history(rows: list[dict[str, Any]]) -> None:
    row_index = {item.get("id"): item for item in rows}
    for row_id, points in OFFICIAL_TREND_HISTORY.items():
        target = row_index.get(row_id)
        if not target:
            continue
        for point in points:
            append_history_point(target, point)


def enrich_rows(rows: list[dict[str, Any]]) -> None:
    for item in rows:
        history = sorted(item.get("history") or [], key=lambda point: str(point.get("period") or ""))
        item["history"] = history
        latest = next((point for point in reversed(history) if point.get("period") == item.get("period")), None)
        if latest:
            for key in ["value", "yoy", "mom", "periodLabel"]:
                if key == "periodLabel" and latest.get(key) is not None:
                    item[key] = latest[key]
                elif item.get(key) is None and latest.get(key) is not None:
                    item[key] = latest[key]
        if item.get("mom") is None and len(history) >= 2:
            current = safe_float(item.get("value"))
            previous = safe_float(history[-2].get("value"))
            if current is not None and previous:
                item["mom"] = round((current / previous - 1) * 100, 2)


def build_sections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = []
    social_rows = [row for row in rows if row.get("category") == SOCIAL_RETAIL_CATEGORY]
    if social_rows:
        sections.append(
            {
                "id": "social_retail",
                "name": "社零",
                "groups": [{"id": "domestic", "name": "境内", "rows": social_rows}],
                "rowCount": len(social_rows),
            }
        )
    for segment, segment_label in [("required", "必选消费"), ("optional", "可选消费")]:
        groups = []
        for geography, geography_label in [("domestic", "境内"), ("overseas", "海外/进口")]:
            group_rows = [
                row
                for row in rows
                if row.get("segment") == segment
                and row.get("geography") == geography
                and row.get("category") != SOCIAL_RETAIL_CATEGORY
            ]
            groups.append({"id": geography, "name": geography_label, "rows": group_rows})
        sections.append({"id": segment, "name": segment_label, "groups": groups, "rowCount": sum(len(group["rows"]) for group in groups)})
    return sections


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_names = {row.get("source") for row in rows if row.get("source")}
    categories = {row.get("category") for row in rows if row.get("category")}
    latest_period = max((str(row.get("period") or "") for row in rows), default="")
    return {
        "latestPeriod": latest_period,
        "rowCount": len(rows),
        "categoryCount": len(categories),
        "sourceCount": len(source_names),
        "requiredCount": sum(1 for row in rows if row.get("segment") == "required"),
        "optionalCount": sum(1 for row in rows if row.get("segment") == "optional"),
        "domesticCount": sum(1 for row in rows if row.get("geography") == "domestic"),
        "overseasCount": sum(1 for row in rows if row.get("geography") == "overseas"),
        "sources": sorted(source_names),
    }


def extract_period(html: str) -> tuple[str, str]:
    text = clean_html(html)
    match = re.search(r"(\d{4})年(\d{1,2})月份", text)
    if match:
        year, month = match.groups()
        return f"{year}-{int(month):02d}", f"{int(month)}月"
    cumulative = re.search(r"(\d{4})年1[—-](\d{1,2})月份", text)
    if cumulative:
        year, month = cumulative.groups()
        return f"{year}-{int(month):02d}", f"1-{int(month)}月累计"
    return datetime.now(UTC).strftime("%Y-%m"), "最新"


def extract_cumulative_label(text: str) -> str:
    match = re.search(r"\d{4}年1[—-](\d{1,2})月份", text)
    return f"1-{int(match.group(1))}月累计" if match else ""


def extract_customs_period(text: str) -> str:
    match = re.search(r"(\d{4})年前(\d{1,2})个月", text)
    if match:
        year, months = match.groups()
        return f"{year}-{int(months):02d}"
    return ""


def extract_customs_period_label(text: str) -> str:
    match = re.search(r"\d{4}年前(\d{1,2})个月", text)
    return f"1-{int(match.group(1))}月累计" if match else ""


def split_yoy_mom_text(text: str) -> tuple[str, str]:
    parts = re.split(r"二、各类商品及服务价格环比变动情况", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return text, text


def first_metric(text: str, patterns: list[str]) -> tuple[str, ...] | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.groups()
    return None


def extract_directional_pct(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    direction, value = match.groups()
    return signed_pct(direction, value)


def extract_value_after(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    return safe_float(match.group(1)) if match else None


def signed_pct(direction: str, value: Any) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return -number if "下降" in direction else number


def normalize_label(value: str) -> str:
    return re.sub(r"[\s：:其中、，,（）()]+", "", value)


def clean_html(value: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    cleaned = re.sub(r"<script.*?</script>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<style.*?</style>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return unescape(re.sub(r"\s+", " ", cleaned)).strip()


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "-", ""):
            return None
        if isinstance(value, str):
            normalized = value.replace(",", "").replace("%", "").replace("+", "").strip()
            if not normalized or normalized == "-":
                return None
            return float(normalized)
        return float(value)
    except (TypeError, ValueError):
        return None


async def load_latest_consumption(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_consumption_sync, db_path)


async def save_latest_consumption(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_consumption_sync, db_path, data)


def load_latest_consumption_sync(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_consumption_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_consumption WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_consumption_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_consumption_table(db_path)
    payload = json.dumps(data, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_consumption WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_consumption (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (data.get("generatedAt", ""), data.get("savedAt", ""), data.get("expiresAt", ""), payload),
        )
        conn.commit()


def ensure_consumption_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_consumption (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def user_agent() -> str:
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
