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

from .investment_catalog import build_commodity_metadata
from .investment_quality import build_metric_quality, quality_summary
from .request_coordinator import coordinate_httpx_client

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
COMMODITY_CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
COMMODITY_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
COMMODITY_SCHEMA_VERSION = 12

SINA_FUTURES_URL = "https://hq.sinajs.cn/list={symbols}"
SINA_FUTURES_KLINE_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_k=/InnerFuturesNewService.getDailyKLine"
SINA_GLOBAL_FUTURES_KLINE_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_k=/GlobalFuturesService.getGlobalFuturesDailyKLine"
SUNSIRS_FUTURES_URL = "https://futures.100ppi.com/"
EASTMONEY_DATA_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SMM_PRICE_URL = "https://www.smm.com.cn/price"
SMM_EXTRA_PRICE_URLS = [
    "https://hq.smm.cn/h5/si-polysilicon",
    "https://hq.smm.cn/h5/iron-ore",
    "https://hq.smm.cn/h5/iron-ore-price-index",
    "https://hq.smm.cn/h5/coal",
    "https://hq.smm.cn/h5/rebar",
    "https://hq.smm.cn/h5/SPHC",
]
SMM_REBAR_PAGE_URL = "https://hq.smm.cn/h5/rebar"
SMM_IRON_ORE_PAGE_URL = "https://hq.smm.cn/h5/iron-ore"
SMM_HOT_ROLL_STOCK_URL = "https://hq.smm.cn/h5/SPHC-stock"
SMM_COAL_STOCK_URL = "https://hq.smm.cn/h5/coal/stock"
SINA_PRECIOUS_SPOT_SYMBOLS = {
    "gold": {"symbol": "hf_XAU", "name": "伦敦现货黄金", "unit": "元/克", "factor": 1 / 31.1034768},
    "silver": {"symbol": "hf_XAG", "name": "伦敦现货白银", "unit": "元/千克", "factor": 1000 / 31.1034768},
}
SHFE_INVENTORY_URLS = [
    "https://www.shfe.com.cn/data/dailydata/kx/kx{date}.dat",
    "https://www.shfe.com.cn/data/dailydata/{date}dailystock.dat",
    "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx/kx{date}.dat",
    "https://www.shfe.com.cn/data/tradedata/future/dailydata/{date}dailystock.dat",
]
EASTMONEY_INVENTORY_CODES = {
    "gold": "AU",
    "silver": "AG",
    "copper": "CU",
    "aluminum": "AL",
    "nickel": "NI",
    "zinc": "ZN",
    "tin": "SN",
    "iron_ore": "I",
    "coking_coal": "JM",
    "coke": "J",
    "rebar": "RB",
    "hot_rolled_coil": "HC",
    "crude_oil": "sc",
    "fuel_oil": "FU",
    "asphalt": "BU",
    "lpg": "PG",
    "methanol": "MA",
    "pta": "TA",
    "polypropylene": "PP",
    "polyethylene": "L",
    "pvc": "V",
    "rubber": "RU",
    "glass": "FG",
    "soda_ash": "SA",
    "urea": "UR",
    "egg": "JD",
    "corn": "C",
    "soybean": "A",
    "soybean_meal": "M",
    "soybean_oil": "Y",
    "palm_oil": "P",
    "rapeseed_meal": "RM",
    "rapeseed_oil": "OI",
    "cotton": "CF",
    "sugar": "SR",
}
SUNSIRS_SPOT_UNITS = {
    "黄金": "元/克",
    "白银": "元/千克",
    "玻璃": "元/平方米",
    "鸡蛋": "元/公斤",
    "生猪": "元/公斤",
}
HISTORY_POINTS = 30
SUNSIRS_BASIS_HISTORY_PAGES = 8
SUNSIRS_BASIS_HISTORY_POINTS = 12
SUNSIRS_BASIS_DETAIL_LIMIT = 120
INVENTORY_TYPES = frozenset(
    {
        "exchange_receipt",
        "deliverable_stock",
        "port_stock",
        "social_stock",
        "mill_stock",
        "plant_stock",
        "sample_stock",
    }
)
INVENTORY_TYPE_LABELS = {
    "exchange_receipt": "交易所仓单",
    "deliverable_stock": "可交割库存",
    "port_stock": "港口库存",
    "social_stock": "社会库存",
    "mill_stock": "钢厂库存",
    "plant_stock": "生产企业库存",
    "sample_stock": "样本库存",
}
PREFERRED_INVENTORY_TYPES = {
    "iron_ore": "port_stock",
    "coking_coal": "plant_stock",
    "coke": "port_stock",
    "rebar": "social_stock",
    "hot_rolled_coil": "social_stock",
}
COMMODITY_RELATIONS = frozenset(
    {"same_product_global", "upstream_driver", "substitute", "downstream_demand"}
)

COMMODITIES = [
    {"id": "gold", "name": "黄金", "sector": "贵金属", "domesticFuture": "nf_AU0", "globalFuture": "hf_GC", "spotNames": ["黄金"], "unit": "元/克"},
    {"id": "silver", "name": "白银", "sector": "贵金属", "domesticFuture": "nf_AG0", "globalFuture": "hf_SI", "spotNames": ["白银"], "unit": "元/千克"},
    {"id": "copper", "name": "铜", "sector": "有色金属", "domesticFuture": "nf_CU0", "globalFuture": "hf_CAD", "spotNames": ["SMM 1#电解铜"], "unit": "元/吨"},
    {"id": "aluminum", "name": "铝", "sector": "有色金属", "domesticFuture": "nf_AL0", "globalFuture": "hf_AHD", "spotNames": ["SMM A00铝"], "unit": "元/吨"},
    {"id": "nickel", "name": "镍", "sector": "有色金属", "domesticFuture": "nf_NI0", "globalFuture": "hf_NID", "spotNames": ["SMM 1#电解镍"], "unit": "元/吨"},
    {"id": "zinc", "name": "锌", "sector": "有色金属", "domesticFuture": "nf_ZN0", "globalFuture": "hf_ZSD", "spotNames": ["SMM 0#锌锭"], "unit": "元/吨"},
    {"id": "tin", "name": "锡", "sector": "有色金属", "domesticFuture": "nf_SN0", "globalFuture": "hf_SND", "spotNames": ["SMM 1#锡"], "unit": "元/吨"},
    {
        "id": "iron_ore",
        "name": "铁矿石",
        "sector": "黑色链",
        "domesticFuture": "nf_I0",
        "globalFuture": "",
        "spotNames": [
            "MMi青岛港65%铁矿石现货价格指数",
            "MMi青岛港58%铁矿石现货价格指数",
            "MMi 65%铁矿石港口现货指数",
            "MMi青岛港62%铁矿石现货价格指数",
            "青岛港PB粉铁矿石价格",
        ],
        "unit": "元/吨",
    },
    {
        "id": "coking_coal",
        "name": "焦煤",
        "sector": "黑色链",
        "domesticFuture": "nf_JM0",
        "globalFuture": "",
        "spotNames": ["吕梁主焦煤价格", "太原主焦煤价格", "临汾主焦煤价格", "主焦煤价格"],
        "unit": "元/吨",
    },
    {
        "id": "coke",
        "name": "焦炭",
        "sector": "黑色链",
        "domesticFuture": "nf_J0",
        "globalFuture": "",
        "spotNames": ["干熄准一级冶金焦炭价格", "准一级冶金焦炭价格", "一级冶金焦炭价格"],
        "unit": "元/吨",
    },
    {
        "id": "rebar",
        "name": "螺纹钢",
        "sector": "黑色链",
        "domesticFuture": "nf_RB0",
        "globalFuture": "",
        "spotNames": ["SMM中国螺纹钢价格指数", "螺纹钢全国均价"],
        "unit": "元/吨",
    },
    {
        "id": "hot_rolled_coil",
        "name": "热卷",
        "sector": "黑色链",
        "domesticFuture": "nf_HC0",
        "globalFuture": "",
        "spotNames": ["SMM中国热轧板卷价格指数", "全国热卷均价", "热轧卷板", "热卷"],
        "unit": "元/吨",
    },
    {"id": "crude_oil", "name": "原油", "sector": "大宗能源", "domesticFuture": "nf_SC0", "globalFuture": "hf_OIL", "spotNames": ["原油"], "unit": "元/桶"},
    {"id": "fuel_oil", "name": "燃料油", "sector": "大宗能源", "domesticFuture": "nf_FU0", "globalFuture": "hf_HO", "globalRelation": "substitute", "spotNames": ["燃料油"], "unit": "元/吨"},
    {
        "id": "asphalt",
        "name": "沥青",
        "sector": "化工品",
        "domesticFuture": "nf_BU0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["石油沥青", "沥青"],
        "unit": "元/吨",
    },
    {
        "id": "lpg",
        "name": "液化石油气",
        "sector": "大宗能源",
        "domesticFuture": "nf_PG0",
        "globalFuture": "",
        "benchmarkFuture": "hf_NG",
        "spotNames": ["液化石油气", "液化气"],
        "unit": "元/吨",
    },
    {"id": "natural_gas", "name": "天然气", "sector": "大宗能源", "domesticFuture": "", "globalFuture": "hf_NG", "globalRelation": "upstream_driver", "spotNames": ["天然气"], "unit": ""},
    {
        "id": "methanol",
        "name": "甲醇",
        "sector": "化工品",
        "domesticFuture": "nf_MA0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["华东甲醇价格", "甲醇MA", "甲醇"],
        "unit": "元/吨",
    },
    {
        "id": "pta",
        "name": "PTA",
        "sector": "化工品",
        "domesticFuture": "nf_TA0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["PTA"],
        "unit": "元/吨",
    },
    {
        "id": "polypropylene",
        "name": "聚丙烯",
        "sector": "化工品",
        "domesticFuture": "nf_PP0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["聚丙烯", "PP"],
        "unit": "元/吨",
    },
    {
        "id": "polyethylene",
        "name": "塑料",
        "sector": "化工品",
        "domesticFuture": "nf_L0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["聚乙烯", "LLDPE", "塑料"],
        "unit": "元/吨",
    },
    {
        "id": "pvc",
        "name": "PVC",
        "sector": "化工品",
        "domesticFuture": "nf_V0",
        "globalFuture": "",
        "benchmarkFuture": "hf_OIL",
        "spotNames": ["聚氯乙烯", "PVC"],
        "unit": "元/吨",
    },
    {"id": "rubber", "name": "天然橡胶", "sector": "化工品", "domesticFuture": "nf_RU0", "globalFuture": "", "spotNames": ["天然橡胶"], "unit": "元/吨"},
    {"id": "glass", "name": "玻璃", "sector": "建材", "domesticFuture": "nf_FG0", "globalFuture": "", "spotNames": ["玻璃"], "unit": "元/吨"},
    {"id": "soda_ash", "name": "纯碱", "sector": "建材", "domesticFuture": "nf_SA0", "globalFuture": "", "spotNames": ["纯碱"], "unit": "元/吨"},
    {"id": "urea", "name": "尿素", "sector": "化肥", "domesticFuture": "nf_UR0", "globalFuture": "", "spotNames": ["尿素"], "unit": "元/吨"},
    {"id": "industrial_silicon", "name": "工业硅", "sector": "新能源材料", "domesticFuture": "nf_SI0", "globalFuture": "", "spotNames": ["工业硅"], "unit": "元/吨"},
    {"id": "polysilicon", "name": "多晶硅", "sector": "新能源材料", "domesticFuture": "nf_PS0", "domesticFutureUnit": "元/吨", "globalFuture": "", "spotNames": ["多晶硅价格指数", "N型多晶硅料价格", "多晶硅"], "unit": "元/千克"},
    {"id": "lithium_carbonate", "name": "碳酸锂", "sector": "新能源材料", "domesticFuture": "nf_LC0", "globalFuture": "", "spotNames": ["电池级碳酸锂"], "unit": "元/吨"},
    {"id": "egg", "name": "鸡蛋", "sector": "农产品", "domesticFuture": "nf_JD0", "globalFuture": "", "spotNames": ["鸡蛋"], "unit": "元/500千克"},
    {"id": "corn", "name": "玉米", "sector": "农产品", "domesticFuture": "nf_C0", "globalFuture": "hf_C", "spotNames": ["玉米"], "unit": "元/吨"},
    {"id": "soybean", "name": "大豆", "sector": "农产品", "domesticFuture": "nf_A0", "globalFuture": "hf_S", "spotNames": ["大豆", "豆一"], "unit": "元/吨"},
    {"id": "soybean_meal", "name": "豆粕", "sector": "农产品", "domesticFuture": "nf_M0", "globalFuture": "hf_SM", "spotNames": ["豆粕"], "unit": "元/吨"},
    {"id": "soybean_oil", "name": "豆油", "sector": "农产品", "domesticFuture": "nf_Y0", "globalFuture": "hf_BO", "spotNames": ["豆油"], "unit": "元/吨"},
    {"id": "palm_oil", "name": "棕榈油", "sector": "农产品", "domesticFuture": "nf_P0", "globalFuture": "", "spotNames": ["棕榈油"], "unit": "元/吨"},
    {"id": "rapeseed_meal", "name": "菜粕", "sector": "农产品", "domesticFuture": "nf_RM0", "globalFuture": "", "spotNames": ["菜粕", "菜籽粕"], "unit": "元/吨"},
    {"id": "rapeseed_oil", "name": "菜油", "sector": "农产品", "domesticFuture": "nf_OI0", "globalFuture": "", "spotNames": ["菜油", "菜籽油", "菜籽油OI"], "unit": "元/吨"},
    {"id": "cotton", "name": "棉花", "sector": "农产品", "domesticFuture": "nf_CF0", "globalFuture": "hf_CT", "spotNames": ["棉花"], "unit": "元/吨"},
    {"id": "sugar", "name": "白糖", "sector": "农产品", "domesticFuture": "nf_SR0", "globalFuture": "", "spotNames": ["白糖"], "unit": "元/吨"},
]


def classify_shfe_inventory_diagnostic(
    error: str,
    fallback_inventories: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Downgrade an SHFE fetch failure only when both precious-metal rows have a usable fallback."""

    message = str(error or "").strip()
    if not message:
        return [], []

    for commodity_id in ("gold", "silver"):
        value = fallback_inventories.get(commodity_id)
        rows = value if isinstance(value, list) else [value]
        if not any(
            isinstance(row, dict)
            and row.get("inventory") is not None
            and str(row.get("inventoryDate") or "").strip()
            for row in rows
        ):
            return [message], []
    return [], [f"{message}；黄金/白银仓单备用源已补位"]


async def fetch_commodity_sources(client: httpx.AsyncClient) -> list[tuple[Any, str]]:
    """Fetch independent providers concurrently; per-domain coordinator still bounds requests."""

    return await asyncio.gather(
        fetch_sina_futures(client),
        fetch_sina_future_histories(client),
        fetch_smm_spots(client),
        fetch_sina_precious_spots(client),
        fetch_sunsirs_basis_spots(client),
        fetch_shfe_precious_inventories(client),
        fetch_smm_inventories(client),
        fetch_eastmoney_inventories(client),
    )


async def get_commodities(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    async with COMMODITY_CACHE_LOCK:
        if (
            not force
            and not refresh
            and COMMODITY_CACHE["data"]
            and COMMODITY_CACHE["data"].get("schemaVersion") == COMMODITY_SCHEMA_VERSION
            and datetime.now(UTC) < COMMODITY_CACHE["expires_at"]
        ):
            cached = dict(COMMODITY_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = upgrade_commodity_snapshot(await load_latest_commodities(db_path))
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == COMMODITY_SCHEMA_VERSION)
    stored_is_fresh = bool(stored_schema_valid and effective_expires_at(stored, ttl_seconds) > datetime.now(UTC))
    if (
        not force
        and stored
        and stored_schema_valid
        and ((allow_stale and not refresh) or stored_is_fresh)
        and has_commodity_payload(stored)
    ):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with COMMODITY_CACHE_LOCK:
            COMMODITY_CACHE["data"] = stored
            COMMODITY_CACHE["expires_at"] = effective_expires_at(stored, ttl_seconds)
        return stored

    errors: list[str] = []
    warnings: list[str] = []
    timeout = float(fetch_config.get("request_timeout_seconds", 8))
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout)) as client:
        coordinate_httpx_client(client)
        (
            (futures, futures_error),
            (future_histories, future_history_error),
            (spots, spot_error),
            (precious_spots, precious_spot_error),
            (sunsirs_spots, sunsirs_spot_error),
            (shfe_inventories, inventory_error),
            (smm_inventories, smm_inventory_error),
            (eastmoney_inventories, eastmoney_inventory_error),
        ) = await fetch_commodity_sources(client)
        inventories = merge_inventory_series(smm_inventories, shfe_inventories, eastmoney_inventories)
        spots.update({name: spot for name, spot in precious_spots.items() if name not in spots})
        spots.update({name: spot for name, spot in sunsirs_spots.items() if name not in spots})

    if futures_error:
        errors.append(futures_error)
    if future_history_error:
        errors.append(future_history_error)
    if spot_error:
        errors.append(spot_error)
    if precious_spot_error:
        errors.append(precious_spot_error)
    if sunsirs_spot_error:
        errors.append(sunsirs_spot_error)
    inventory_errors, inventory_warnings = classify_shfe_inventory_diagnostic(
        inventory_error,
        eastmoney_inventories,
    )
    errors.extend(inventory_errors)
    warnings.extend(inventory_warnings)
    if smm_inventory_error:
        errors.append(smm_inventory_error)
    if eastmoney_inventory_error:
        errors.append(eastmoney_inventory_error)

    items = [
        item
        for item in (build_commodity_item(item, futures, future_histories, spots, inventories) for item in COMMODITIES)
        if has_publishable_commodity_data(item)
    ]
    quality_rows = [
        {"quality": quality}
        for item in items
        for quality in [
            item.get("basisQuality"),
            *(series.get("quality") for series in item.get("inventorySeries", [])),
        ]
        if isinstance(quality, dict)
    ]
    now = datetime.now(UTC)
    data = {
        "schemaVersion": COMMODITY_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": any(has_publishable_commodity_data(row) for row in items),
        "source": "Sina Futures / Sina Spot / SMM / SHFE / Sunsirs / Eastmoney",
        "qualitySummary": quality_summary(quality_rows),
        "cadence": "半小时最多真实抓取一次",
        "errors": errors,
        "warnings": warnings,
        "items": items,
    }

    if not data["hasData"] and stored and has_commodity_payload(stored):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["stale"] = True
        return stored

    await save_latest_commodities(db_path, data)
    async with COMMODITY_CACHE_LOCK:
        COMMODITY_CACHE["data"] = data
        COMMODITY_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


async def read_commodity_snapshot() -> dict[str, Any] | None:
    """Return the latest usable commodity snapshot without starting external I/O."""

    config = load_config()
    ttl_seconds = int(config.get("fetch", {}).get("min_refresh_interval_seconds", 1800))
    cached = upgrade_commodity_snapshot(COMMODITY_CACHE.get("data"))
    from_storage = False
    if not isinstance(cached, dict) or not has_commodity_payload(cached):
        cached = upgrade_commodity_snapshot(await load_latest_commodities(resolve_sqlite_path(config)))
        from_storage = True
    if not isinstance(cached, dict) or not has_commodity_payload(cached):
        return None

    snapshot = dict(cached)
    schema_current = snapshot.get("schemaVersion") == COMMODITY_SCHEMA_VERSION
    snapshot.update(
        {
            "cached": True,
            "fromStorage": from_storage,
            "throttled": False,
            "stale": not schema_current or effective_expires_at(snapshot, ttl_seconds) <= datetime.now(UTC),
        }
    )
    return snapshot


def upgrade_commodity_snapshot(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    snapshot = copy.deepcopy(data)
    previous_schema = snapshot.get("schemaVersion")
    definitions = {definition["id"]: definition for definition in COMMODITIES}
    quality_rows: list[dict[str, Any]] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        definition = definitions.get(item_id) or {
            "id": item_id,
            "name": item.get("name") or item_id,
            "sector": item.get("sector") or "其他",
            "domesticFuture": "",
            "globalFuture": "",
        }
        inventory_rows = [row for row in item.get("inventorySeries") or [] if isinstance(row, dict)]
        item.update(build_commodity_metadata(definition, inventory_rows))
        domestic_symbol = str(definition.get("domesticFuture") or "")
        global_symbol = str(definition.get("globalFuture") or "")
        item.setdefault("domesticFutureSourceUrl", SINA_FUTURES_URL.format(symbols=domestic_symbol) if domestic_symbol else "")
        item.setdefault("globalFutureSourceUrl", SINA_FUTURES_URL.format(symbols=global_symbol) if global_symbol else "")
        for quality in [item.get("basisQuality"), *(row.get("quality") for row in inventory_rows)]:
            if isinstance(quality, dict):
                quality_rows.append({"quality": quality})
    if quality_rows:
        snapshot["qualitySummary"] = quality_summary(quality_rows)
    if previous_schema != COMMODITY_SCHEMA_VERSION:
        snapshot["legacySchemaVersion"] = previous_schema
    snapshot["schemaVersion"] = COMMODITY_SCHEMA_VERSION
    return snapshot


async def fetch_sina_futures(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    domestic_symbols = [item["domesticFuture"] for item in COMMODITIES if item.get("domesticFuture")]
    global_symbols = sorted(
        {
            symbol
            for item in COMMODITIES
            for symbol in [item.get("globalFuture"), item.get("benchmarkFuture")]
            if symbol
        }
    )
    results: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    domestic, domestic_error = await fetch_sina_symbol_group(client, domestic_symbols, "新浪国内期货接口")
    global_, global_error = await fetch_sina_symbol_group(client, global_symbols, "新浪国际期货接口")
    results.update(domestic)
    results.update(global_)
    if domestic_error:
        errors.append(domestic_error)
    if global_error:
        errors.append(global_error)

    return results, "；".join(errors)


async def fetch_sina_future_histories(client: httpx.AsyncClient) -> tuple[dict[str, list[dict[str, Any]]], str]:
    symbols = sorted(
        {
            symbol
            for item in COMMODITIES
            for symbol in [item.get("domesticFuture"), item.get("globalFuture"), item.get("benchmarkFuture")]
            if symbol
        }
    )
    tasks = [fetch_sina_future_history(client, symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rows: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for symbol, result in zip(symbols, results, strict=False):
        if isinstance(result, Exception):
            errors.append(f"{symbol} {type(result).__name__}: {result}")
            continue
        if result:
            rows[symbol] = result[-HISTORY_POINTS:]
    if rows:
        return rows, ""
    detail = f"（{'；'.join(errors[:3])}）" if errors else ""
    return {}, f"新浪期货日K暂未取到{detail}"


async def fetch_sina_future_history(client: httpx.AsyncClient, symbol: str) -> list[dict[str, Any]]:
    is_global = symbol.startswith("hf_")
    response = await client.get(
        SINA_GLOBAL_FUTURES_KLINE_URL if is_global else SINA_FUTURES_KLINE_URL,
        params={"symbol": symbol.replace("hf_", "").replace("nf_", "")},
        headers={
            "User-Agent": user_agent(),
            "Referer": "https://finance.sina.com.cn/futures/",
            "Accept": "*/*",
        },
    )
    response.raise_for_status()
    return parse_sina_future_history(response.text)


def parse_sina_future_history(text: str) -> list[dict[str, Any]]:
    match = re.search(r"=\s*\(?\s*(\[[\s\S]*\])\s*\)?\s*;?\s*$", text)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        close = safe_float(row.get("c") or row.get("close"))
        date_text = str(row.get("d") or row.get("date") or "").strip()
        if close is None or not date_text:
            continue
        rows.append(
            {
                "date": date_text,
                "open": safe_float(row.get("o") or row.get("open")),
                "high": safe_float(row.get("h") or row.get("high")),
                "low": safe_float(row.get("l") or row.get("low")),
                "close": close,
                "volume": safe_float(row.get("v") or row.get("volume")),
                "openInterest": safe_float(row.get("p") or row.get("position")),
                "settle": safe_float(row.get("s") or row.get("settlement")),
            }
        )
    return rows


async def fetch_sina_symbol_group(
    client: httpx.AsyncClient,
    symbols: list[str],
    label: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    if not symbols:
        return {}, ""
    try:
        response = await client.get(
            SINA_FUTURES_URL.format(symbols=",".join(symbols)),
            headers={
                "User-Agent": user_agent(),
                "Referer": "https://finance.sina.com.cn/futures/",
                "Accept": "*/*",
            },
        )
        response.raise_for_status()
        parsed = parse_sina_futures(decode_sina_response(response))
        missing = [symbol for symbol in symbols if symbol not in parsed]
        error = f"{label}部分代码无返回：{','.join(missing)}" if missing else ""
        return parsed, error
    except Exception as error:
        return {}, f"{label}暂未取到：{error}"


def parse_sina_futures(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    pattern = re.compile(r'var\s+hq_str_((?:nf|hf)_[A-Z0-9]+)="([^"]*)";')
    for symbol, payload in pattern.findall(text):
        if not payload:
            continue
        fields = payload.split(",")
        if symbol.startswith("hf_"):
            parsed = parse_sina_global_future(symbol, fields)
        else:
            parsed = parse_sina_domestic_future(symbol, fields)
        if parsed:
            result[symbol] = parsed
    return result


def decode_sina_response(response: httpx.Response) -> str:
    return response.content.decode("gbk", errors="replace")


def parse_sina_domestic_future(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 18:
        return None
    latest = safe_float(fields[8]) or safe_float(fields[6]) or safe_float(fields[2])
    previous_settle = safe_float(fields[10])
    return {
        "symbol": symbol.replace("nf_", ""),
        "market": "国内",
        "name": fields[0] or fields[15],
        "price": latest,
        "open": safe_float(fields[2]),
        "high": safe_float(fields[3]),
        "low": safe_float(fields[4]),
        "previousSettle": previous_settle,
        "changePct": pct_change(latest, previous_settle),
        "volume": safe_float(fields[13]),
        "openInterest": safe_float(fields[14]),
        "exchange": fields[15],
        "date": fields[17] if len(fields) > 17 else "",
        "source": "新浪期货",
    }


def parse_sina_global_future(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 14:
        return None
    latest = safe_float(fields[0])
    previous = safe_float(fields[7])
    return {
        "symbol": symbol.replace("hf_", ""),
        "market": "国际",
        "name": fields[13] if len(fields) > 13 else symbol.replace("hf_", ""),
        "price": latest,
        "open": safe_float(fields[8]),
        "high": safe_float(fields[4]),
        "low": safe_float(fields[5]),
        "previousSettle": previous,
        "changePct": pct_change(latest, previous),
        "volume": safe_float(fields[14]) if len(fields) > 14 else None,
        "openInterest": None,
        "exchange": "",
        "date": fields[12] if len(fields) > 12 else "",
        "time": fields[6] if len(fields) > 6 else "",
        "source": "新浪外盘",
    }


async def fetch_smm_spots(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    urls = [SMM_PRICE_URL, *SMM_EXTRA_PRICE_URLS]
    results = await asyncio.gather(*(fetch_smm_spot_page(client, url) for url in urls))
    for page_rows, error in results:
        rows.update(page_rows)
        if error:
            errors.append(error)
    return rows, "；".join(errors)


async def fetch_sina_precious_spots(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    symbols = [value["symbol"] for value in SINA_PRECIOUS_SPOT_SYMBOLS.values()]
    try:
        response = await client.get(
            SINA_FUTURES_URL.format(symbols=",".join([*symbols, "fx_susdcny"])),
            headers={
                "User-Agent": user_agent(),
                "Referer": "https://finance.sina.com.cn/futures/",
                "Accept": "*/*",
            },
        )
        response.raise_for_status()
    except Exception as error:
        return {}, f"新浪贵金属现货暂未取到：{error}"

    decoded = decode_sina_response(response)
    usd_cny = parse_sina_usd_cny(decoded)
    if not usd_cny:
        return {}, "新浪贵金属现货暂未取到：美元人民币汇率缺失"

    quotes = parse_sina_futures(decoded)
    rows: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for commodity_id, config in SINA_PRECIOUS_SPOT_SYMBOLS.items():
        quote = quotes.get(config["symbol"])
        price_usd_oz = quote.get("price") if quote else None
        if price_usd_oz is None:
            missing.append(config["symbol"])
            continue
        price = round(price_usd_oz * usd_cny * config["factor"], 2)
        rows[config["name"]] = {
            "name": config["name"],
            "range": f"{price_usd_oz:g} 美元/盎司，USD/CNY {usd_cny:g}",
            "price": price,
            "change": quote.get("changePct"),
            "unit": config["unit"],
            "date": quote.get("date", ""),
            "source": "新浪现货",
            "commodityId": commodity_id,
        }
    error = f"新浪贵金属现货部分代码无返回：{','.join(missing)}" if missing else ""
    return rows, error


async def fetch_sunsirs_basis_spots(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        html = await fetch_html_with_hw_check(
            client,
            SUNSIRS_FUTURES_URL,
            headers={
                "User-Agent": user_agent(),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        rows = parse_sunsirs_basis_prices(html)
        history_rows, history_error = await fetch_sunsirs_basis_history(client, rows)
        attach_sunsirs_spot_history(rows, history_rows)
        if rows:
            return rows, history_error
        return rows, history_error or "生意社现期表暂未解析到可用数据"
    except Exception as error:
        return {}, f"生意社现期表暂未取到：{error}"


async def fetch_html_with_hw_check(client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> str:
    response = await client.get(url, headers=headers or {})
    response.raise_for_status()
    challenge = re.search(r'var\s+_0x2\s*=\s*"([^"]+)"', response.text)
    if challenge and "HW_CHECK" in response.text:
        host = httpx.URL(url).host
        if host:
            client.cookies.set("HW_CHECK", challenge.group(1), domain=host, path="/")
        response = await client.get(url, headers=headers or {})
        response.raise_for_status()
    return response.text


def parse_sunsirs_basis_prices(html: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    date_text = extract_chinese_date(clean_html(html))
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        row_html = match.group(1)
        cells = [clean_html(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S | re.I)]
        if len(cells) != 5:
            continue
        name, spot_text, contract, future_text, basis_text = cells
        spot_price = safe_float(spot_text)
        future_price = safe_float(future_text)
        basis = safe_float(basis_text)
        if spot_price is None or future_price is None or basis is None:
            continue
        detail_match = re.search(r'<a[^>]+href="([^"]+)"', row_html, flags=re.S | re.I)
        detail_url = make_absolute_url(detail_match.group(1), "https://www.100ppi.com") if detail_match else ""
        range_text = f"{contract}合约 {future_price:g}，基差 {basis:+g}"
        history_point = {
            "date": date_text,
            "value": spot_price,
            "futurePrice": future_price,
            "basis": basis,
            "contract": contract,
            "unit": SUNSIRS_SPOT_UNITS.get(name, "元/吨"),
        }
        row = {
            "name": name,
            "range": range_text,
            "price": spot_price,
            "change": None,
            "unit": SUNSIRS_SPOT_UNITS.get(name, "元/吨"),
            "date": date_text,
            "source": "生意社现期表",
            "detailUrl": detail_url,
            "basis": basis,
            "basisFutureContract": contract,
            "basisFuturePrice": future_price,
            "basisSource": "生意社现货-期货合约",
            "history": [history_point] if date_text else [],
        }
        rows[name] = row
    return rows


async def fetch_sunsirs_basis_history(
    client: httpx.AsyncClient,
    current_rows: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    wanted = {normalize_commodity_name(name): name for name in current_rows}
    if not wanted:
        return {}, ""

    page_tasks = [
        fetch_sunsirs_basis_history_page(client, page)
        for page in range(1, SUNSIRS_BASIS_HISTORY_PAGES + 1)
    ]
    page_results = await asyncio.gather(*page_tasks, return_exceptions=True)
    links_by_name: dict[str, list[str]] = {name: [] for name in current_rows}
    errors: list[str] = []

    for page_result in page_results:
        if isinstance(page_result, Exception):
            errors.append(f"{type(page_result).__name__}: {page_result}")
            continue
        for name, url in page_result:
            normalized = normalize_commodity_name(name)
            expected = wanted.get(normalized)
            if not expected:
                continue
            urls = links_by_name.setdefault(expected, [])
            if url not in urls and len(urls) < SUNSIRS_BASIS_HISTORY_POINTS:
                urls.append(url)

    detail_urls: list[tuple[str, str]] = []
    for name, urls in links_by_name.items():
        detail_urls.extend((name, url) for url in urls)
    detail_urls = detail_urls[:SUNSIRS_BASIS_DETAIL_LIMIT]
    if not detail_urls:
        return {}, "生意社现货历史暂未匹配到详情页"

    detail_tasks = [fetch_sunsirs_basis_detail(client, name, url) for name, url in detail_urls]
    detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
    history: dict[str, list[dict[str, Any]]] = {}
    for result in detail_results:
        if isinstance(result, Exception):
            errors.append(f"{type(result).__name__}: {result}")
            continue
        if not result:
            continue
        history.setdefault(result["name"], []).append(result)

    for name, points in history.items():
        deduped = {point["date"]: point for point in points if point.get("date")}
        history[name] = sorted(deduped.values(), key=lambda point: point["date"])[-SUNSIRS_BASIS_HISTORY_POINTS:]

    error = f"生意社现货历史部分详情暂未取到：{'；'.join(errors[:3])}" if errors and not history else ""
    return history, error


async def fetch_sunsirs_basis_history_page(client: httpx.AsyncClient, page: int) -> list[tuple[str, str]]:
    url = f"https://www.100ppi.com/data/dlist--15--{page}.html"
    html = await fetch_html_with_hw_check(
        client,
        url,
        headers={
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    rows: list[tuple[str, str]] = []
    pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*class="blueq"[^>]*>(.*?)</a>', flags=re.S | re.I)
    for href, title_html in pattern.findall(html):
        title = clean_html(title_html)
        match = re.search(r"生意社(.+?)市场基差", title)
        if not match:
            continue
        rows.append((match.group(1), make_absolute_url(href, "https://www.100ppi.com/data/")))
    return rows


async def fetch_sunsirs_basis_detail(client: httpx.AsyncClient, expected_name: str, url: str) -> dict[str, Any] | None:
    html = await fetch_html_with_hw_check(
        client,
        url,
        headers={
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    return parse_sunsirs_basis_detail(html, expected_name)


def parse_sunsirs_basis_detail(html: str, expected_name: str) -> dict[str, Any] | None:
    text = clean_html(html)
    title_match = re.search(r"(\d{1,2})月(\d{1,2})日生意社(.+?)市场基差为([+-]?[0-9.]+)元/吨", text)
    name = title_match.group(3) if title_match else expected_name
    date_text = extract_chinese_date(text)
    spot_match = re.search(r"现货基准价为([0-9.]+)元/([^\s。]+)", text)
    future_match = re.search(r"期货主力合约([0-9A-Za-z]+)收盘价为([0-9.]+)元/吨", text)
    basis = safe_float(title_match.group(4)) if title_match else None
    spot_price = safe_float(spot_match.group(1)) if spot_match else None
    future_price = safe_float(future_match.group(2)) if future_match else None
    if not date_text or spot_price is None:
        return None
    return {
        "name": expected_name or name,
        "date": date_text,
        "value": spot_price,
        "unit": f"元/{spot_match.group(2)}" if spot_match else SUNSIRS_SPOT_UNITS.get(name, "元/吨"),
        "futurePrice": future_price,
        "basis": basis,
        "contract": future_match.group(1) if future_match else "",
    }


def attach_sunsirs_spot_history(
    rows: dict[str, dict[str, Any]],
    history_rows: dict[str, list[dict[str, Any]]],
) -> None:
    for name, row in rows.items():
        history = list(history_rows.get(name, []))
        for point in row.get("history", []):
            if not any(existing.get("date") == point.get("date") for existing in history):
                history.append(point)
        row["history"] = sorted(
            [point for point in history if point.get("date") and safe_float(point.get("value")) is not None],
            key=lambda point: point["date"],
        )[-SUNSIRS_BASIS_HISTORY_POINTS:]


async def fetch_shfe_precious_inventories(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    today = datetime.now(UTC).date()
    errors: list[str] = []
    for days_back in range(0, 10):
        date_text = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        for template in SHFE_INVENTORY_URLS:
            url = template.format(date=date_text)
            try:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": user_agent(),
                        "Referer": "https://www.shfe.com.cn/",
                        "Accept": "application/json,text/plain,*/*",
                    },
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                rows = parse_shfe_precious_inventories(response.json(), date_text)
                if rows:
                    return rows, ""
            except Exception as error:
                errors.append(f"{date_text} {type(error).__name__}: {error}")
    detail = f"（{'；'.join(errors[:2])}）" if errors else ""
    return {}, f"SHFE贵金属库存接口暂不可用{detail}"


async def fetch_smm_inventories(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    tasks = [
        ("SMM铁矿石库存", fetch_smm_iron_ore_inventory(client)),
        ("SMM热卷库存", fetch_smm_hot_roll_inventory(client)),
        ("SMM煤焦库存", fetch_smm_coal_inventories(client)),
        ("SMM螺纹库存", fetch_smm_rebar_inventory(client)),
    ]
    results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
    for (label, _), result in zip(tasks, results, strict=False):
        if isinstance(result, Exception):
            errors.append(f"{label}暂未取到：{result}")
            continue
        rows.update(result)
    return rows, "；".join(errors)


async def fetch_eastmoney_inventories(client: httpx.AsyncClient) -> tuple[dict[str, dict[str, Any]], str]:
    since = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    tasks = [
        fetch_eastmoney_inventory(client, commodity_id, code, since)
        for commodity_id, code in EASTMONEY_INVENTORY_CODES.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for (commodity_id, code), result in zip(EASTMONEY_INVENTORY_CODES.items(), results, strict=False):
        if isinstance(result, Exception):
            errors.append(f"{code} {type(result).__name__}: {result}")
            continue
        if result:
            rows[commodity_id] = result
    if rows:
        return rows, ""
    detail = f"（{'；'.join(errors[:3])}）" if errors else ""
    return {}, f"东方财富期货库存暂未取到{detail}"


async def fetch_eastmoney_inventory(
    client: httpx.AsyncClient,
    commodity_id: str,
    code: str,
    since: str,
) -> dict[str, Any] | None:
    response = await client.get(
        EASTMONEY_DATA_URL,
        params={
            "reportName": "RPT_FUTU_STOCKDATA",
            "columns": "SECURITY_CODE,TRADE_DATE,ON_WARRANT_NUM,ADDCHANGE,UNIT",
            "filter": f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{since}\')',
            "pageNumber": 1,
            "pageSize": HISTORY_POINTS,
            "sortTypes": 1,
            "sortColumns": "TRADE_DATE",
            "source": "WEB",
            "client": "WEB",
        },
        headers={
            "User-Agent": user_agent(),
            "Referer": "https://data.eastmoney.com/ifdata/kcsj.html",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    response.raise_for_status()
    payload = response.json()
    data = (payload.get("result") or {}).get("data") or []
    history: list[dict[str, Any]] = []
    unit = ""
    for row in data:
        inventory = safe_float(row.get("ON_WARRANT_NUM"))
        if inventory is None:
            continue
        date_text = str(row.get("TRADE_DATE") or "").split(" ")[0]
        change = safe_float(row.get("ADDCHANGE"))
        unit = str(row.get("UNIT") or "").strip() or unit
        history.append({"date": date_text, "value": inventory, "change": change})
    history = [row for row in history if row.get("date")]
    if not history:
        return None
    history.sort(key=lambda row: row["date"])
    latest = history[-1]
    previous_value = history[-2]["value"] if len(history) > 1 else None
    inventory = safe_float(latest.get("value"))
    change = safe_float(latest.get("change"))
    if change is None and inventory is not None and previous_value is not None:
        change = round(inventory - previous_value, 4)
    change_pct = round(change / previous_value * 100, 2) if change is not None and previous_value else None
    source = f"东方财富期货库存（{code}仓单）"
    if change is not None:
        source = f"{source}，日变动{change:+g}"
    return {
        "inventory": inventory,
        "inventoryUnit": unit,
        "inventoryDate": latest["date"],
        "inventorySource": source,
        "inventoryChange": change,
        "inventoryChangePct": change_pct,
        "inventoryHistory": history[-HISTORY_POINTS:],
    }


async def fetch_smm_iron_ore_inventory(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    html = await fetch_smm_html(client, SMM_IRON_ORE_PAGE_URL)
    article_url = first_smm_link(html, r"铁矿石港口库存及疏港量")
    if not article_url:
        return {}
    article_html = await fetch_smm_html(client, article_url)
    title = extract_smm_title(article_html)
    profile = extract_smm_profile(article_html)
    inventory = first_text_number(profile, [r"库存总量为\s*([0-9.]+)\s*万吨", r"港口的铁矿石库存.*?([0-9.]+)\s*万吨"])
    if inventory is None:
        return {}
    return {
        "iron_ore": {
            "inventory": inventory,
            "inventoryUnit": "万吨",
            "inventoryDate": extract_chinese_date(title or profile) or title,
            "inventorySource": "SMM 35港铁矿石库存",
        }
    }


async def fetch_smm_hot_roll_inventory(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    html = await fetch_smm_html(client, SMM_HOT_ROLL_STOCK_URL)
    news = first_smm_news(html, lambda row: "热卷库存" in news_text(row) and "总库存" in news_text(row))
    if not news:
        return {}
    text = news_text(news)
    date_text = smm_news_date(news) or str(news.get("news_title") or "")
    inventory = first_text_number(text, [r"总库存\s*([0-9.]+)\s*万吨", r"热轧板卷总库存\s*([0-9.]+)\s*万吨"])
    if inventory is None:
        return {}
    return {
        "hot_rolled_coil": {
            "inventory": inventory,
            "inventoryUnit": "万吨",
            "inventoryDate": date_text,
            "inventorySource": "SMM热轧板卷总库存",
        }
    }


async def fetch_smm_coal_inventories(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    html = await fetch_smm_html(client, SMM_COAL_STOCK_URL)
    news = first_smm_news(html, lambda row: "焦煤焦炭库存" in news_text(row) and "库存" in news_text(row))
    if not news:
        return {}
    text = news_text(news)
    date_text = smm_news_date(news) or str(news.get("news_title") or "")
    rows: dict[str, dict[str, Any]] = {}

    coke_inventory = last_text_number(text, [r"港口焦炭库存\s*([0-9.]+)\s*万?吨", r"焦企焦炭库存\s*([0-9.]+)\s*万?吨"])
    if coke_inventory is not None:
        rows["coke"] = {
            "inventory": coke_inventory,
            "inventoryUnit": "万吨",
            "inventoryDate": date_text,
            "inventorySource": "SMM焦炭港口库存",
        }

    coking_coal_inventory = last_text_number(text, [r"焦企焦煤库存\s*([0-9.]+)\s*(?:万?吨)"])
    if coking_coal_inventory is not None:
        rows["coking_coal"] = {
            "inventory": coking_coal_inventory,
            "inventoryUnit": "万吨",
            "inventoryDate": date_text,
            "inventorySource": "SMM焦企焦煤库存",
        }
    return rows


async def fetch_smm_rebar_inventory(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    html = await fetch_smm_html(client, SMM_REBAR_PAGE_URL)
    links = [
        (title, make_smm_url(href))
        for title, href in re.findall(r'<a[^>]+title="([^"]*建材库存[^"]*)"[^>]+href="([^"]+)"', html, flags=re.S | re.I)
        if "日评" not in title
    ]
    city_values: dict[str, float] = {}
    dates: list[str] = []
    for title, url in links[:8]:
        city_match = re.search(r"SMM([^】]+)建材库存", title)
        city = city_match.group(1) if city_match else title[:8]
        if city in city_values:
            continue
        article_html = await fetch_smm_html(client, url)
        profile = extract_smm_profile(article_html)
        value = first_text_number(profile, [r"(?:社会库存为|总库存|库存在)\s*([0-9.]+)\s*万吨"])
        if value is None:
            continue
        city_values[city] = value
        date_text = extract_chinese_date(profile)
        if date_text:
            dates.append(date_text)
        if len(city_values) >= 3:
            break

    if not city_values:
        return {}
    return {
        "rebar": {
            "inventory": round(sum(city_values.values()), 2),
            "inventoryUnit": "万吨",
            "inventoryDate": max(dates) if dates else "SMM最新建材库存",
            "inventorySource": f"SMM重点城市建材库存合计（{'、'.join(city_values.keys())}）",
        }
    }


async def fetch_smm_html(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(
        url,
        headers={
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    response.raise_for_status()
    return response.text


async def fetch_smm_spot_page(client: httpx.AsyncClient, url: str) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        html = await fetch_smm_html(client, url)
        return parse_smm_prices(html), ""
    except Exception as error:
        return {}, f"SMM现货页面暂未取到（{url}）：{error}"


def parse_smm_prices(html: str) -> dict[str, dict[str, Any]]:
    rows = parse_smm_next_prices(html)
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", match.group(1), flags=re.S | re.I)
        if len(cells) < 6:
            continue
        values = [clean_html(cell) for cell in cells[:6]]
        name, price_range, avg, change, unit, date = values
        if not name:
            continue
        rows[name] = {
            "name": name,
            "range": price_range,
            "price": safe_float(avg),
            "change": safe_float(change),
            "unit": unit,
            "date": date,
            "source": "SMM",
        }
    return rows


def parse_smm_next_prices(html: str) -> dict[str, dict[str, Any]]:
    payload = extract_smm_next_data(html)
    if not payload:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in flatten_json_rows(payload):
        name = str(row.get("product_name") or row.get("ProductName") or "").strip()
        if not name:
            continue
        price = first_number(row, ["average", "avg", "AveragePrice", "price", "Price"])
        if price is None:
            continue
        low = first_number(row, ["low", "LowPrice", "min_price"])
        high = first_number(row, ["high", "HighPrice", "max_price"])
        rows[name] = {
            "name": name,
            "range": format_smm_range(low, high, price),
            "price": price,
            "change": first_number(row, ["vchange", "change_value", "change", "Change"]),
            "unit": str(row.get("unit") or row.get("price_unit") or "").strip(),
            "date": str(row.get("renew_date") or row.get("date") or row.get("UpdateDate") or "").strip(),
            "source": "SMM",
        }
    return rows


def extract_smm_next_data(html: str) -> dict[str, Any] | None:
    match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def format_smm_range(low: float | None, high: float | None, price: float) -> str:
    if low is not None and high is not None:
        return f"{low:g} - {high:g}"
    return f"{price:g}"


def first_smm_news(html: str, predicate: Any) -> dict[str, Any] | None:
    payload = extract_smm_next_data(html)
    if not payload:
        return None
    for row in flatten_json_rows(payload):
        if row.get("news_title") and predicate(row):
            return row
    return None


def news_text(row: dict[str, Any]) -> str:
    return clean_html(
        " ".join(
            str(row.get(key) or "")
            for key in ["news_title", "news_profile", "news_content", "block_name"]
        )
    )


def smm_news_date(row: dict[str, Any]) -> str:
    timestamp = safe_float(row.get("renew_date"))
    if timestamp:
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    return extract_chinese_date(news_text(row))


def first_smm_link(html: str, title_pattern: str) -> str:
    pattern = re.compile(r'<a[^>]+title="([^"]+)"[^>]+href="([^"]+)"', flags=re.S | re.I)
    for title, href in pattern.findall(html):
        if re.search(title_pattern, title):
            return make_smm_url(href)
    return ""


def make_smm_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        return f"https://hq.smm.cn{href}"
    return f"https://hq.smm.cn/{href}"


def make_absolute_url(href: str, base: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    return urljoin(base, href)


def extract_smm_title(html: str) -> str:
    for pattern in [r"<h1[^>]*>(.*?)</h1>", r"<title>(.*?)</title>"]:
        match = re.search(pattern, html, flags=re.S | re.I)
        if match:
            return clean_html(match.group(1))
    return ""


def extract_smm_profile(html: str) -> str:
    for pattern in [
        r'<p[^>]+class="[^"]*content-news-profile[^"]*"[^>]*>(.*?)</p>',
        r'<div[^>]+class="[^"]*newsProfile[^"]*"[^>]*>(.*?)</div>',
    ]:
        match = re.search(pattern, html, flags=re.S | re.I)
        if match:
            return clean_html(match.group(1))
    return ""


def first_text_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return safe_float(match.group(1))
    return None


def last_text_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            value = matches[-1]
            if isinstance(value, tuple):
                value = value[0]
            return safe_float(value)
    return None


def extract_chinese_date(text: str) -> str:
    full = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if full:
        year, month, day = (int(value) for value in full.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    partial = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if partial:
        month, day = (int(value) for value in partial.groups())
        return f"{datetime.now(UTC).year:04d}-{month:02d}-{day:02d}"
    return ""


def parse_sina_usd_cny(text: str) -> float | None:
    match = re.search(r'var\s+hq_str_(?:fx_susdcny|USDCNY)="([^"]*)";', text)
    if not match:
        return None
    fields = match.group(1).split(",")
    for index in (8, 2, 1):
        if len(fields) > index:
            value = safe_float(fields[index])
            if value:
                return value
    return None


def parse_shfe_precious_inventories(payload: Any, date_text: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in flatten_json_rows(payload):
        normalized = {str(key).lower(): value for key, value in row.items()}
        name = str(
            normalized.get("varname")
            or normalized.get("productname")
            or normalized.get("product")
            or normalized.get("commodity")
            or normalized.get("instrument")
            or ""
        )
        commodity_id = ""
        if "黄金" in name or name.upper() == "AU":
            commodity_id = "gold"
        elif "白银" in name or name.upper() == "AG":
            commodity_id = "silver"
        if not commodity_id:
            continue

        inventory = first_number(
            normalized,
            [
                "wrtwghts",
                "wrtwght",
                "whstock",
                "whstocks",
                "stock",
                "stocks",
                "qty",
                "quantity",
                "total",
            ],
        )
        if inventory is None:
            continue
        rows[commodity_id] = {
            "inventory": inventory,
            "inventoryUnit": "千克",
            "inventoryDate": date_text,
            "inventorySource": "SHFE仓单库存",
        }
    return rows


def flatten_json_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        rows = [value] if any(not isinstance(item, (dict, list)) for item in value.values()) else []
        for item in value.values():
            rows.extend(flatten_json_rows(item))
        return rows
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(flatten_json_rows(item))
        return rows
    return []


def first_number(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = safe_float(row.get(key))
        if value is not None:
            return value
    return None


def clean_html(value: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    cleaned = re.sub(r"<script.*?</script>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<style.*?</style>", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return unescape(re.sub(r"\s+", " ", cleaned)).strip()


def infer_inventory_type(commodity_id: str, row: dict[str, Any]) -> str:
    declared = str(row.get("inventoryType") or "").strip()
    if declared in INVENTORY_TYPES:
        return declared

    source = str(row.get("inventorySource") or "")
    if "港" in source:
        return "port_stock"
    if "社会" in source or "总库存" in source or commodity_id in {"rebar", "hot_rolled_coil"} and "SMM" in source:
        return "social_stock"
    if "钢厂" in source:
        return "mill_stock"
    if "焦企" in source or "生产" in source:
        return "plant_stock"
    if "仓单" in source or "期货库存" in source:
        return "exchange_receipt"
    return "sample_stock"


def inventory_source_url(row: dict[str, Any]) -> str:
    explicit = str(row.get("inventorySourceUrl") or "").strip()
    if explicit:
        return explicit
    source = str(row.get("inventorySource") or "")
    if "SMM" in source:
        return SMM_PRICE_URL
    if "SHFE" in source or "上期所" in source:
        return "https://www.shfe.com.cn/"
    if "东方财富" in source:
        return EASTMONEY_DATA_URL
    return SUNSIRS_FUTURES_URL


def inventory_source_priority(row: dict[str, Any]) -> tuple[int, str]:
    source = str(row.get("inventorySource") or "")
    authority = 3 if "SHFE" in source or "上期所" in source else 2 if "SMM" in source else 1
    return authority, str(row.get("inventoryDate") or "")


def merge_inventory_series(*sources: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str, str, str]] = set()
    for source_rows in sources:
        for commodity_id, raw_row in source_rows.items():
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            inventory_type = infer_inventory_type(commodity_id, row)
            row["inventoryType"] = inventory_type
            row["inventoryTypeLabel"] = INVENTORY_TYPE_LABELS[inventory_type]
            signature = (
                commodity_id,
                inventory_type,
                str(row.get("inventorySource") or ""),
                str(row.get("inventoryDate") or ""),
                str(row.get("inventory") or ""),
            )
            if signature in seen:
                continue
            seen.add(signature)
            inventory_date = str(row.get("inventoryDate") or "").strip()
            row["quality"] = build_metric_quality(
                value=row.get("inventory"),
                unit=str(row.get("inventoryUnit") or "未披露"),
                as_of=inventory_date or "未知",
                source_url=inventory_source_url(row),
                definition=f"{INVENTORY_TYPE_LABELS[inventory_type]}；不同库存类型不可互相覆盖或直接求和",
                method="observed",
                status="ok" if row.get("inventory") is not None and inventory_date else "partial",
                coverage={"inventoryType": inventory_type},
                quality_flags=[] if inventory_date else ["统计日未披露"],
            )
            merged.setdefault(commodity_id, []).append(row)

    for rows in merged.values():
        rows.sort(key=inventory_source_priority, reverse=True)
    return merged


def select_primary_inventory(commodity_id: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    preferred_type = PREFERRED_INVENTORY_TYPES.get(commodity_id, "exchange_receipt")
    preferred = [row for row in rows if row.get("inventoryType") == preferred_type]
    candidates = preferred or rows
    return max(candidates, key=inventory_source_priority)


PRICE_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "元/吨": ("mass", 1.0),
    "元/千克": ("mass", 1000.0),
    "元/公斤": ("mass", 1000.0),
    "元/500千克": ("mass", 2.0),
    "元/克": ("mass", 1_000_000.0),
    "元/桶": ("barrel", 1.0),
    "元/平方米": ("area", 1.0),
}


def normalize_price_unit(value: Any, unit: str) -> tuple[float | None, str, str]:
    number = safe_float(value)
    normalized_unit = str(unit or "").strip()
    if number is None or not normalized_unit:
        return None, "", ""
    dimension, factor = PRICE_UNIT_FACTORS.get(normalized_unit, (f"exact:{normalized_unit}", 1.0))
    display_unit = "元/吨" if dimension == "mass" else normalized_unit
    return number * factor, dimension, display_unit


def is_explicit_future_contract(value: str) -> bool:
    normalized = str(value or "").strip().upper()
    return bool(re.search(r"\d{3,4}$", normalized))


def assess_basis_comparability(
    definition: dict[str, Any],
    spot: dict[str, Any] | None,
    domestic_future: dict[str, Any] | None,
    spot_price: Any,
    domestic_price: Any,
) -> dict[str, Any]:
    spot_unit = str((spot or {}).get("unit") or definition.get("unit") or "")
    future_unit = str(definition.get("domesticFutureUnit") or definition.get("unit") or "")
    normalized_spot, spot_dimension, normalized_unit = normalize_price_unit(spot_price, spot_unit)
    normalized_future, future_dimension, future_normalized_unit = normalize_price_unit(domestic_price, future_unit)
    rules = definition.get("basisRules") if isinstance(definition.get("basisRules"), dict) else {}
    source_comparable = bool((spot or {}).get("basisComparable"))
    reasons: list[str] = []

    if normalized_spot is None or normalized_future is None:
        reasons.append("现货或期货价格/单位缺失")
    elif spot_dimension != future_dimension:
        reasons.append("现货与期货计价维度不可换算")
    if not (source_comparable or rules.get("gradeVerified")):
        reasons.append("交割品级未核验")
    if not (source_comparable or rules.get("locationVerified")):
        reasons.append("交割地点未核验")
    if not (source_comparable or rules.get("taxAdjusted")):
        reasons.append("税费口径未核验")
    if not (source_comparable or rules.get("freightAdjusted")):
        reasons.append("运费/升贴水未核验")

    contract = str((spot or {}).get("basisFutureContract") or (domestic_future or {}).get("instrumentId") or "")
    if not is_explicit_future_contract(contract):
        reasons.append("未对应具体交割合约")

    comparable = not reasons
    return {
        "comparable": comparable,
        "reasons": reasons,
        "spotUnit": spot_unit,
        "futureUnit": future_unit,
        "normalizedUnit": normalized_unit if normalized_unit == future_normalized_unit else "",
        "normalizedInputs": {
            "spot": normalized_spot,
            "future": normalized_future,
        },
        "contract": contract,
    }


def build_commodity_item(
    definition: dict[str, Any],
    futures: dict[str, dict[str, Any]],
    future_histories: dict[str, list[dict[str, Any]]],
    spots: dict[str, dict[str, Any]],
    inventories: dict[str, list[dict[str, Any]] | dict[str, Any]],
) -> dict[str, Any]:
    spot = first_matching_spot(definition["spotNames"], spots)
    domestic_future = futures.get(definition.get("domesticFuture", ""))
    domestic_future_history = future_histories.get(definition.get("domesticFuture", ""), [])
    global_future = futures.get(definition.get("globalFuture", ""))
    global_future_history = future_histories.get(definition.get("globalFuture", ""), [])
    benchmark_future = futures.get(definition.get("benchmarkFuture", ""))
    benchmark_future_history = future_histories.get(definition.get("benchmarkFuture", ""), [])
    raw_inventory_rows = inventories.get(definition["id"], [])
    if isinstance(raw_inventory_rows, dict):
        inventory_rows = merge_inventory_series({definition["id"]: raw_inventory_rows}).get(definition["id"], [])
    else:
        inventory_rows = [dict(row) for row in raw_inventory_rows if isinstance(row, dict)]
    inventory = select_primary_inventory(definition["id"], inventory_rows)
    catalog_metadata = build_commodity_metadata(definition, inventory_rows)
    spot_price = spot.get("price") if spot else None
    domestic_price = domestic_future.get("price") if domestic_future else None
    if domestic_price is None and domestic_future_history:
        domestic_price = domestic_future_history[-1].get("close")
    global_price = global_future.get("price") if global_future else None
    if global_price is None and global_future_history:
        global_price = global_future_history[-1].get("close")
    benchmark_price = benchmark_future.get("price") if benchmark_future else None
    if benchmark_price is None and benchmark_future_history:
        benchmark_price = benchmark_future_history[-1].get("close")
    basis_comparison = assess_basis_comparability(
        definition,
        spot,
        domestic_future,
        spot_price,
        domestic_price,
    )
    basis = None
    basis_pct = None
    basis_future_contract = ""
    basis_future_price = None
    basis_source = ""
    spot_basis = safe_float(spot.get("basis")) if spot else None
    reported_basis = round(spot_basis, 2) if spot_basis is not None else None
    reported_basis_source = str(spot.get("basisSource") or spot.get("source") or "") if spot else ""
    basis_future_contract = str(spot.get("basisFutureContract") or "") if spot else ""
    basis_future_price = safe_float(spot.get("basisFuturePrice")) if spot else None
    if basis_comparison["comparable"]:
        normalized_spot = safe_float(basis_comparison["normalizedInputs"].get("spot"))
        normalized_future = safe_float(basis_comparison["normalizedInputs"].get("future"))
        if normalized_spot is not None and normalized_future is not None:
            basis = round(normalized_spot - normalized_future, 2)
            basis_pct = round(basis / normalized_future * 100, 2) if normalized_future else None
            basis_future_price = normalized_future
            basis_source = reported_basis_source or "标准化现货-具体交割合约"
    if domestic_price is None and basis_future_price is not None:
        domestic_price = basis_future_price

    basis_status = "ok" if basis_comparison["comparable"] else "invalid" if spot_price is not None and domestic_price is not None else "unavailable"
    basis_as_of = str((spot or {}).get("date") or (domestic_future or {}).get("date") or "未知")
    basis_quality = build_metric_quality(
        value=basis,
        unit=str(basis_comparison.get("normalizedUnit") or definition.get("unit") or "未披露"),
        as_of=basis_as_of,
        source_url=str((spot or {}).get("url") or SUNSIRS_FUTURES_URL),
        definition="现货与对应具体交割合约在单位、币种、品级、地点、税费和运费统一后的价差",
        method="derived",
        status=basis_status,
        formula="normalized spot - normalized future",
        quality_flags=basis_comparison["reasons"],
    )

    cross_market_spread = None
    cross_market_spread_pct = None

    note_parts = []
    if spot and spot.get("source") == "新浪现货":
        note_parts.append("现货采用伦敦金银并按美元人民币汇率折算")
    if benchmark_future and not global_future:
        note_parts.append("外盘列仅展示上游驱动，不代表同品种国际价格")
    if reported_basis is not None and not basis_comparison["comparable"]:
        note_parts.append("来源报告基差因口径元数据不足，仅保留参考值，不参与信号")
    if basis_comparison["reasons"]:
        note_parts.append("基差不可比：" + "、".join(basis_comparison["reasons"]))

    return {
        "id": definition["id"],
        "name": definition["name"],
        "sector": definition["sector"],
        **catalog_metadata,
        "unit": definition["unit"],
        "spotName": spot.get("name") if spot else "",
        "spotUnit": spot.get("unit") if spot else definition["unit"],
        "spotPrice": spot_price,
        "spotRange": spot.get("range") if spot else "",
        "spotChange": spot.get("change") if spot else None,
        "spotDate": spot.get("date") if spot else "",
        "spotHistory": spot.get("history", []) if spot else [],
        "spotSourceUrl": str(spot.get("url") or "") if spot else "",
        "domesticFutureSymbol": domestic_future.get("symbol") if domestic_future else basis_future_contract or definition.get("domesticFuture", "").replace("nf_", ""),
        "domesticFutureName": domestic_future.get("name") if domestic_future else (f"{basis_future_contract}合约" if basis_future_contract else ""),
        "domesticFuturePrice": domestic_price,
        "domesticFutureChangePct": domestic_future.get("changePct") if domestic_future else None,
        "domesticFutureVolume": domestic_future.get("volume") if domestic_future else None,
        "domesticFutureOpenInterest": domestic_future.get("openInterest") if domestic_future else None,
        "domesticFutureDate": domestic_future.get("date") if domestic_future else (spot.get("date") if basis_future_price is not None else (domestic_future_history[-1].get("date") if domestic_future_history else "")),
        "domesticFutureHistory": domestic_future_history,
        "domesticFutureSourceUrl": str((domestic_future or {}).get("sourceUrl") or (domestic_future or {}).get("url") or SINA_FUTURES_URL.format(symbols=definition.get("domesticFuture", ""))),
        "globalFutureSymbol": global_future.get("symbol") if global_future else definition.get("globalFuture", "").replace("hf_", ""),
        "globalFutureName": global_future.get("name") if global_future else "",
        "globalFuturePrice": global_price,
        "globalFutureChangePct": global_future.get("changePct") if global_future else None,
        "globalFutureVolume": global_future.get("volume") if global_future else None,
        "globalFutureDate": global_future.get("date") if global_future else (global_future_history[-1].get("date") if global_future_history else ""),
        "globalFutureHistory": global_future_history,
        "globalFutureSourceUrl": str((global_future or {}).get("sourceUrl") or (global_future or {}).get("url") or SINA_FUTURES_URL.format(symbols=definition.get("globalFuture", ""))),
        "globalFutureRelation": str(definition.get("globalRelation") or ("same_product_global" if definition.get("globalFuture") else "")),
        "benchmarkFutureSymbol": benchmark_future.get("symbol") if benchmark_future else definition.get("benchmarkFuture", "").replace("hf_", ""),
        "benchmarkFutureName": benchmark_future.get("name") if benchmark_future else "",
        "benchmarkFuturePrice": benchmark_price,
        "benchmarkFutureChangePct": benchmark_future.get("changePct") if benchmark_future else None,
        "benchmarkFutureDate": benchmark_future.get("date") if benchmark_future else (benchmark_future_history[-1].get("date") if benchmark_future_history else ""),
        "benchmarkFutureHistory": benchmark_future_history,
        "benchmarkFutureRelation": str(definition.get("benchmarkRelation") or ("upstream_driver" if definition.get("benchmarkFuture") else "")),
        "crossMarketSpread": cross_market_spread,
        "crossMarketSpreadPct": cross_market_spread_pct,
        "basis": basis,
        "basisPct": basis_pct,
        "basisSource": basis_source,
        "basisComparison": basis_comparison,
        "basisQuality": basis_quality,
        "reportedBasis": reported_basis,
        "reportedBasisSource": reported_basis_source,
        "basisFutureContract": basis_future_contract,
        "basisFuturePrice": basis_future_price,
        "inventory": inventory.get("inventory") if inventory else None,
        "inventoryUnit": inventory.get("inventoryUnit") if inventory else "",
        "inventoryDate": inventory.get("inventoryDate") if inventory else "",
        "inventorySource": inventory.get("inventorySource") if inventory else "",
        "inventorySourceUrl": inventory_source_url(inventory) if inventory else "",
        "inventoryChange": inventory.get("inventoryChange") if inventory else None,
        "inventoryChangePct": inventory.get("inventoryChangePct") if inventory else None,
        "inventoryHistory": inventory.get("inventoryHistory", []) if inventory else [],
        "inventoryType": inventory.get("inventoryType") if inventory else "",
        "inventoryTypeLabel": inventory.get("inventoryTypeLabel") if inventory else "",
        "inventorySeries": inventory_rows,
        "source": " / ".join(
            sorted(
                {
                    value
                    for value in [
                        spot.get("source") if spot else "",
                        domestic_future.get("source") if domestic_future else "",
                        global_future.get("source") if global_future else "",
                        benchmark_future.get("source") if benchmark_future else "",
                        inventory.get("inventorySource") if inventory else "",
                    ]
                    if value
                }
            )
        ),
        "note": "；".join(note_parts),
    }


def first_matching_spot(names: list[str], spots: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for expected in names:
        if expected in spots:
            return spots[expected]
    for expected in names:
        expected_key = normalize_commodity_name(expected)
        for name, spot in spots.items():
            name_key = normalize_commodity_name(name)
            if expected in name or name in expected:
                return spot
            if expected_key and name_key and (expected_key in name_key or name_key in expected_key):
                return spot
    return None


def normalize_commodity_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", value)
    normalized = re.sub(r"[（）()#0-9A-Za-z]+", "", normalized)
    for token in ["SMM", "中国", "全国", "现货", "价格", "指数", "均价", "电解", "锭"]:
        normalized = normalized.replace(token, "")
    return normalized


def has_publishable_commodity_data(item: dict[str, Any]) -> bool:
    return any(
        has_commodity_value(item.get(key))
        for key in [
            "spotPrice",
            "domesticFuturePrice",
            "globalFuturePrice",
            "benchmarkFuturePrice",
            "basis",
            "inventory",
        ]
    )


def has_commodity_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and value != value)


def has_commodity_payload(data: dict[str, Any]) -> bool:
    return any(has_publishable_commodity_data(item) for item in data.get("items", []))


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_sqlite_path(config: dict[str, Any]) -> Path:
    configured = config.get("storage", {}).get("sqlite_path", "data/news.sqlite")
    path = Path(configured)
    return path if path.is_absolute() else ROOT_DIR / path


async def load_latest_commodities(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_commodities_sync, db_path)


async def save_latest_commodities(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_commodities_sync, db_path, data)


def load_latest_commodities_sync(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_commodities_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_commodities WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_commodities_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_commodities_table(db_path)
    payload = json.dumps(data, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_commodities WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_commodities (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (data.get("generatedAt", ""), data.get("savedAt", ""), data.get("expiresAt", ""), payload),
        )


def ensure_commodities_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_commodities (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
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


def pct_change(latest: float | None, previous: float | None) -> float | None:
    if latest is None or not previous:
        return None
    return round((latest / previous - 1) * 100, 2)


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


def user_agent() -> str:
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
