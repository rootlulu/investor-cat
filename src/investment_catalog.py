from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo


CANONICAL_ID_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
NBS_2026_CALENDAR_URL = "https://www.stats.gov.cn/xw/tjxw/tzgg/202512/t20251224_1962137.html"

NBS_2026_RELEASES: dict[str, tuple[str, ...]] = {
    "nbs.activity.monthly": (
        "2026-01-19T10:00:00+08:00",
        "2026-03-16T10:00:00+08:00",
        "2026-04-16T10:00:00+08:00",
        "2026-05-18T10:00:00+08:00",
        "2026-06-16T10:00:00+08:00",
        "2026-07-15T10:00:00+08:00",
        "2026-08-17T10:00:00+08:00",
        "2026-09-15T10:00:00+08:00",
        "2026-10-19T10:00:00+08:00",
        "2026-11-16T10:00:00+08:00",
        "2026-12-15T10:00:00+08:00",
    ),
    "nbs.energy.monthly": (
        "2026-01-19T10:00:00+08:00",
        "2026-03-16T10:00:00+08:00",
        "2026-04-16T10:00:00+08:00",
        "2026-05-18T10:00:00+08:00",
        "2026-06-16T10:00:00+08:00",
        "2026-07-15T10:00:00+08:00",
        "2026-08-17T10:00:00+08:00",
        "2026-09-15T10:00:00+08:00",
        "2026-10-19T10:00:00+08:00",
        "2026-11-16T10:00:00+08:00",
        "2026-12-15T10:00:00+08:00",
    ),
    "nbs.price.monthly": (
        "2026-01-09T09:30:00+08:00",
        "2026-02-11T09:30:00+08:00",
        "2026-03-09T09:30:00+08:00",
        "2026-04-10T09:30:00+08:00",
        "2026-05-11T09:30:00+08:00",
        "2026-06-10T09:30:00+08:00",
        "2026-07-09T09:30:00+08:00",
        "2026-08-09T09:30:00+08:00",
        "2026-09-09T09:30:00+08:00",
        "2026-10-14T09:30:00+08:00",
        "2026-11-09T09:30:00+08:00",
        "2026-12-09T09:30:00+08:00",
    ),
    "nbs.pmi.monthly": (
        "2026-01-31T09:30:00+08:00",
        "2026-03-04T09:30:00+08:00",
        "2026-03-31T09:30:00+08:00",
        "2026-04-30T09:30:00+08:00",
        "2026-05-31T09:30:00+08:00",
        "2026-06-30T09:30:00+08:00",
        "2026-07-31T09:30:00+08:00",
        "2026-08-31T09:30:00+08:00",
        "2026-09-30T09:30:00+08:00",
        "2026-10-31T09:30:00+08:00",
        "2026-11-30T09:30:00+08:00",
        "2026-12-31T09:30:00+08:00",
    ),
    "nbs.materials.tenday": tuple(
        f"2026-{month:02d}-{day:02d}T09:30:00+08:00"
        for month, days in {
            1: (4, 14, 24),
            2: (4, 24),
            3: (4, 14, 24),
            4: (4, 14, 24),
            5: (7, 14, 24),
            6: (4, 14, 24),
            7: (4, 14, 24),
            8: (4, 14, 24),
            9: (4, 14, 24),
            10: (9, 14, 24),
            11: (4, 14, 24),
            12: (4, 14, 24),
        }.items()
        for day in days
    ),
}

SECTOR_TAGS = {
    "贵金属": "precious_metals",
    "有色金属": "nonferrous_metals",
    "黑色链": "ferrous",
    "大宗能源": "energy_commodities",
    "化工品": "chemicals",
    "建材": "construction_materials",
    "化肥": "fertilizers",
    "新能源材料": "energy_transition_materials",
    "农产品": "agriculture",
}

COMMODITY_CHAIN_TAGS: dict[str, tuple[str, ...]] = {
    "gold": ("precious_metals", "monetary", "jewelry"),
    "silver": ("precious_metals", "solar", "electronics"),
    "copper": ("base_metals", "power_grid", "construction", "new_energy"),
    "aluminum": ("base_metals", "transport", "construction", "new_energy"),
    "nickel": ("base_metals", "stainless_steel", "battery"),
    "zinc": ("base_metals", "galvanized_steel", "construction"),
    "tin": ("base_metals", "electronics", "solder"),
    "iron_ore": ("ferrous", "steel", "construction"),
    "coking_coal": ("coal", "steel", "ferrous"),
    "coke": ("coal", "steel", "ferrous"),
    "rebar": ("steel", "construction", "property"),
    "hot_rolled_coil": ("steel", "manufacturing", "automotive"),
    "crude_oil": ("oil", "refining", "transport", "chemicals"),
    "fuel_oil": ("oil", "refining", "shipping"),
    "asphalt": ("oil", "refining", "infrastructure"),
    "lpg": ("gas", "chemicals", "residential_energy"),
    "natural_gas": ("gas", "power", "chemicals", "residential_energy"),
    "methanol": ("coal_chemicals", "gas_chemicals", "olefins"),
    "pta": ("oil", "polyester", "textiles"),
    "polypropylene": ("oil", "plastics", "consumer_goods"),
    "polyethylene": ("oil", "plastics", "packaging"),
    "pvc": ("chlor_alkali", "plastics", "construction"),
    "rubber": ("agriculture", "tires", "automotive"),
    "glass": ("construction", "property", "solar"),
    "soda_ash": ("chemicals", "glass", "solar"),
    "urea": ("gas", "fertilizers", "agriculture"),
    "industrial_silicon": ("silicon", "solar", "aluminum"),
    "polysilicon": ("silicon", "solar", "new_energy"),
    "lithium_carbonate": ("lithium", "battery", "new_energy"),
    "egg": ("livestock", "food", "feed"),
    "corn": ("grain", "feed", "starch", "biofuel"),
    "soybean": ("oilseeds", "feed", "edible_oil"),
    "soybean_meal": ("oilseeds", "feed", "livestock"),
    "soybean_oil": ("oilseeds", "edible_oil", "biofuel"),
    "palm_oil": ("edible_oil", "biofuel", "consumer_goods"),
    "rapeseed_meal": ("oilseeds", "feed", "livestock"),
    "rapeseed_oil": ("oilseeds", "edible_oil", "biofuel"),
    "cotton": ("agriculture", "textiles", "apparel"),
    "sugar": ("agriculture", "food", "biofuel"),
}

ENERGY_SERIES = {
    "raw_coal": ("energy.cn.output.raw_coal.monthly", ("coal", "power", "steel"), ("primary_supply",)),
    "coke": ("energy.cn.output.coke.monthly", ("coal", "steel"), ("processed_supply",)),
    "crude_oil": ("energy.cn.output.crude_oil.monthly", ("oil", "refining", "transport"), ("primary_supply",)),
    "crude_oil_processing": ("energy.cn.processing.crude_oil.monthly", ("oil", "refining", "chemicals"), ("throughput",)),
    "natural_gas": ("energy.cn.output.natural_gas.monthly", ("gas", "power", "chemicals"), ("primary_supply",)),
    "power_generation": ("energy.cn.generation.total.monthly", ("power",), ("generation",)),
    "thermal_power": ("energy.cn.generation.thermal.monthly", ("power", "coal", "gas"), ("generation",)),
    "hydro_power": ("energy.cn.generation.hydro.monthly", ("power", "renewables"), ("generation",)),
    "nuclear_power": ("energy.cn.generation.nuclear.monthly", ("power", "nuclear"), ("generation",)),
    "wind_power": ("energy.cn.generation.wind.monthly", ("power", "renewables", "wind"), ("generation",)),
    "solar_power": ("energy.cn.generation.solar.monthly", ("power", "renewables", "solar"), ("generation",)),
}

COUNTRY_CODES = {"china": "cn", "us": "us", "japan": "jp", "europe": "eu"}


def is_canonical_series_id(value: str) -> bool:
    return bool(CANONICAL_ID_PATTERN.fullmatch(str(value or "")))


def build_commodity_metadata(
    definition: Mapping[str, Any],
    inventory_rows: Sequence[Mapping[str, Any]] = (),
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    commodity_id = _slug(definition.get("id"))
    if not commodity_id:
        raise ValueError("commodity id is required")
    sector = SECTOR_TAGS.get(str(definition.get("sector") or ""), "other")
    chains = list(COMMODITY_CHAIN_TAGS.get(commodity_id, (sector,)))
    inventory_types = sorted({_slug(row.get("inventoryType")) for row in inventory_rows if _slug(row.get("inventoryType"))})
    series_ids: dict[str, Any] = {
        "spot": f"commodity.{commodity_id}.price.spot",
        "domesticFuture": f"commodity.{commodity_id}.price.future.domestic",
        "globalFuture": f"commodity.{commodity_id}.price.future.global",
        "basis": f"commodity.{commodity_id}.spread.basis",
        "inventories": {inventory_type: f"commodity.{commodity_id}.inventory.{inventory_type}" for inventory_type in inventory_types},
    }
    return {
        "canonicalId": f"commodity.{commodity_id}",
        "seriesIds": series_ids,
        "tags": {
            "assetClasses": ["commodity"],
            "sectors": [sector],
            "chains": chains,
            "roles": ["raw_material"],
        },
        "releaseCalendars": {
            "spot": release_calendar("market.price.daily", as_of=as_of),
            "futures": release_calendar("market.futures.daily", as_of=as_of),
            "inventory": release_calendar("market.inventory.mixed", as_of=as_of),
        },
        "historyLimits": {"spot": 90, "futures": 90, "inventory": 104},
    }


def build_energy_metadata(metric_id: str, category: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    canonical_id, chains, roles = ENERGY_SERIES.get(
        str(metric_id),
        (f"energy.cn.metric.{_slug(metric_id) or 'unknown'}.monthly", (_slug(category) or "energy",), ("observed_metric",)),
    )
    return {
        "canonicalSeriesId": canonical_id,
        "tags": {
            "assetClasses": ["physical_energy"],
            "sectors": [_energy_sector(category)],
            "chains": list(chains),
            "roles": list(roles),
        },
        "releaseCalendar": release_calendar("nbs.energy.monthly", as_of=as_of),
        "historyLimit": 18,
    }


def build_macro_metadata(country_id: str, row: Mapping[str, Any], *, as_of: datetime | None = None) -> dict[str, Any]:
    country_code = COUNTRY_CODES.get(str(country_id), _slug(country_id) or "global")
    row_id = str(row.get("id") or "")
    if row_id.startswith("nbs_material_"):
        stable_key = _stable_hash(f"{row.get('category') or ''}|{row.get('name') or ''}")
        series_id = f"macro.{country_code}.nbs_material.{stable_key}"
        calendar_id = "nbs.materials.tenday"
        frequency = "tenday"
    else:
        series_id = f"macro.{country_code}.{_slug(row_id) or _stable_hash(str(row.get('name') or 'metric'))}"
        frequency = _macro_frequency(row)
        calendar_id = _macro_calendar_id(country_code, row_id, frequency)
    return {
        "canonicalSeriesId": series_id,
        "tags": {
            "assetClasses": ["macro"],
            "regions": [country_code],
            "topics": [_slug(row.get("category")) or "macro"],
        },
        "releaseCalendar": release_calendar(calendar_id, frequency=frequency, as_of=as_of),
        "historyLimit": {"daily": 252, "tenday": 72, "monthly": 36, "quarterly": 20, "event": 20}.get(frequency, 36),
    }


def release_calendar(
    calendar_id: str,
    *,
    frequency: str | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    now = _as_utc(as_of)
    schedule = NBS_2026_RELEASES.get(calendar_id, ())
    next_release = next((value for value in schedule if datetime.fromisoformat(value).astimezone(UTC) > now), "")
    inferred_frequency = frequency or (
        "tenday" if calendar_id.endswith("tenday") else "monthly" if calendar_id.startswith("nbs.") else "trading_daily"
    )
    result = {
        "id": calendar_id,
        "frequency": inferred_frequency,
        "timezone": "Asia/Shanghai" if calendar_id.startswith("nbs.") else "source_local",
        "scheduleStatus": "verified_2026" if schedule else "rule_based",
        "scheduleRule": _schedule_rule(calendar_id),
    }
    if calendar_id.startswith("nbs."):
        result["sourceUrl"] = NBS_2026_CALENDAR_URL
        result["calendarYear"] = 2026
    if next_release:
        result["nextScheduledAt"] = next_release
    return result


def bounded_history(
    points: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    key: str = "period",
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("history limit must be positive")
    by_key: dict[str, dict[str, Any]] = {}
    for point in points:
        if not isinstance(point, Mapping):
            continue
        point_key = str(point.get(key) or "").strip()
        if point_key:
            by_key[point_key] = dict(point)
    return [by_key[point_key] for point_key in sorted(by_key)[-limit:]]


def _macro_calendar_id(country_code: str, row_id: str, frequency: str) -> str:
    if country_code == "cn" and row_id in {"cpi", "ppi"}:
        return "nbs.price.monthly"
    if country_code == "cn" and row_id in {"official_pmi", "services_pmi"}:
        return "nbs.pmi.monthly"
    if country_code == "cn" and row_id in {
        "gdp_yoy",
        "industrial_output",
        "retail_sales",
        "retail_sales_ytd",
        "retail_ex_auto",
        "online_retail_ytd",
        "online_goods_ytd",
        "online_services_ytd",
        "property_investment",
        "fai_ytd_yoy",
        "urban_unemployment",
        "major_city_unemployment",
        "weekly_hours",
    }:
        return "nbs.activity.monthly"
    return f"official.{country_code}.{frequency}"


def _macro_frequency(row: Mapping[str, Any]) -> str:
    period = str(row.get("period") or "").lower()
    row_id = str(row.get("id") or "")
    if "q" in period or "季度" in period:
        return "quarterly"
    if "实时" in period:
        return "daily"
    if row_id in {"policy_rate", "fed_funds", "deposit_rate"}:
        return "event"
    return "monthly"


def _schedule_rule(calendar_id: str) -> str:
    rules = {
        "nbs.activity.monthly": "国家统计局年度发布日程；2月不发布1月工业、能源、投资与社零数据",
        "nbs.energy.monthly": "国家统计局年度发布日程；随国民经济运行情况发布，2月停发1月数据",
        "nbs.price.monthly": "国家统计局 CPI/PPI 月度发布日程",
        "nbs.pmi.monthly": "国家统计局 PMI 月度发布日程；春节月份按公告调整",
        "nbs.materials.tenday": "原则上每月4日、14日、24日09:30，节假日按年度日程调整",
        "market.price.daily": "交易日按来源收盘/报价节奏更新",
        "market.futures.daily": "交易日盘中快照与日线更新",
        "market.inventory.mixed": "交易所仓单可日更；港口、社会、厂库和样本库存按各自周度/不定期发布",
    }
    return rules.get(calendar_id, "由对应官方来源日历驱动；未验证具体日期时不推断固定发布日期")


def _energy_sector(category: str) -> str:
    return {"煤炭": "coal", "油气": "oil_gas", "电力": "power"}.get(str(category), _slug(category) or "energy")


def _slug(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized


def _stable_hash(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
