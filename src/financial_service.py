from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


ROOT_DIR = Path(__file__).resolve().parents[1]
FINANCIAL_CACHE_PATH = ROOT_DIR / "data" / "financial_snapshots.json"
FINANCIAL_SCHEMA_VERSION = 1

SEC_USER_AGENT_ENV = "NEWS_DIGEST_SEC_USER_AGENT"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_API_DOCUMENTATION_URL = "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
SEC_FAIR_ACCESS_URL = "https://www.sec.gov/about/developer-resources"
SEC_REQUEST_INTERVAL_SECONDS = 0.5
SEC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"})

HKEX_DISCLOSURE_URL = "https://www.hkexnews.hk/"
HKEX_DATA_PRODUCTS_URL = "https://www.hkex.com.hk/eng/ods/historicalData.aspx"
HKEX_IIS_URL = (
    "https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/"
    "Issuer-Information-feed-Service-%28IIS%29"
)
CNINFO_DISCLOSURE_URL = "https://www.cninfo.com.cn/"
CNINFO_DATA_SERVICE_URL = "https://webapi.cninfo.com.cn/"
SSE_DISCLOSURE_URL = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
SZSE_DISCLOSURE_URL = "https://www.szse.cn/disclosure/listed/notice/"

_CACHE_LOCK = asyncio.Lock()
_SEC_REQUEST_LOCK = asyncio.Lock()
_SEC_NEXT_REQUEST_AT = 0.0
_SEC_TICKER_INDEX: dict[str, dict[str, Any]] | None = None


class FinancialSourceError(RuntimeError):
    pass


FINANCIAL_FACT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "revenue",
        "label": "Revenue",
        "periodType": "duration",
        "aliases": (
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"),
            ("ifrs-full", "Revenue"),
        ),
    },
    {
        "id": "net_income",
        "label": "Net income",
        "periodType": "duration",
        "aliases": (("us-gaap", "NetIncomeLoss"), ("us-gaap", "ProfitLoss"), ("ifrs-full", "ProfitLoss")),
    },
    {
        "id": "operating_cash_flow",
        "label": "Operating cash flow",
        "periodType": "duration",
        "aliases": (
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
        ),
    },
    {
        "id": "capital_expenditure",
        "label": "Capital expenditure",
        "periodType": "duration",
        "aliases": (
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
            ("us-gaap", "PaymentsForAdditionsToPropertyPlantAndEquipment"),
            ("ifrs-full", "PurchaseOfPropertyPlantAndEquipment"),
        ),
    },
    {
        "id": "assets",
        "label": "Total assets",
        "periodType": "instant",
        "aliases": (("us-gaap", "Assets"), ("ifrs-full", "Assets")),
    },
    {
        "id": "liabilities",
        "label": "Total liabilities",
        "periodType": "instant",
        "aliases": (("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities")),
    },
    {
        "id": "equity",
        "label": "Equity",
        "periodType": "instant",
        "aliases": (
            ("us-gaap", "StockholdersEquity"),
            ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
            ("ifrs-full", "Equity"),
        ),
    },
    {
        "id": "cash",
        "label": "Cash and cash equivalents",
        "periodType": "instant",
        "aliases": (
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
            ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
            ("ifrs-full", "CashAndCashEquivalents"),
        ),
    },
    {
        "id": "diluted_eps",
        "label": "Diluted EPS",
        "periodType": "duration",
        "aliases": (
            ("us-gaap", "EarningsPerShareDiluted"),
            ("ifrs-full", "DilutedEarningsLossPerShare"),
        ),
    },
)


def financial_source_catalog() -> dict[str, Any]:
    return {
        "schemaVersion": FINANCIAL_SCHEMA_VERSION,
        "generatedAt": _now_iso(),
        "analysisBoundary": "data_only_codex_analyzes",
        "sources": [
            {
                "id": "sec_edgar",
                "market": "us",
                "access": "official_public_rest_json",
                "authorization": "no_api_key_user_agent_required",
                "structured": True,
                "status": "available" if _sec_user_agent() else "configuration_required",
                "configured": bool(_sec_user_agent()),
                "sourceUrl": "https://data.sec.gov/",
                "documentationUrl": SEC_API_DOCUMENTATION_URL,
                "policyUrl": SEC_FAIR_ACCESS_URL,
                "note": f"Set {SEC_USER_AGENT_ENV} to an identifiable application/contact value before syncing.",
            },
            {
                "id": "hkex_disclosures",
                "market": "hk",
                "access": "official_disclosure_page_and_licensed_products",
                "authorization": "license_required_for_machine_feed",
                "structured": False,
                "status": "license_required",
                "configured": False,
                "sourceUrl": HKEX_DISCLOSURE_URL,
                "documentationUrl": HKEX_DATA_PRODUCTS_URL,
                "feedDocumentationUrl": HKEX_IIS_URL,
                "note": "Do not treat HKEXnews website internals as a supported public financial API.",
            },
            {
                "id": "cninfo_disclosures",
                "market": "a_share",
                "access": "official_disclosure_page_and_registered_data_service",
                "authorization": "license_or_account_required_for_api",
                "structured": False,
                "status": "license_required",
                "configured": False,
                "sourceUrl": CNINFO_DISCLOSURE_URL,
                "documentationUrl": CNINFO_DATA_SERVICE_URL,
                "note": "Use CNINFO Data Service or an explicitly licensed exchange feed; undocumented page endpoints are excluded.",
            },
        ],
    }


async def get_financial_snapshot(market: str, symbol: str, cik: str = "") -> dict[str, Any]:
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(normalized_market, symbol)
    normalized_cik = normalize_cik(cik) if cik else ""
    key = cache_key(normalized_market, normalized_symbol)
    async with _CACHE_LOCK:
        payload = await asyncio.to_thread(_read_cache)
        cached = payload.get("snapshots", {}).get(key)
    if isinstance(cached, dict):
        result = dict(cached)
        result["cached"] = True
        return result
    return empty_financial_snapshot(normalized_market, normalized_symbol, normalized_cik)


async def sync_financial_snapshot(market: str, symbol: str, cik: str = "") -> dict[str, Any]:
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(normalized_market, symbol)
    normalized_cik = normalize_cik(cik) if cik else ""
    if normalized_market != "us":
        return empty_financial_snapshot(normalized_market, normalized_symbol, normalized_cik)

    user_agent = _sec_user_agent()
    if not user_agent:
        return empty_financial_snapshot(normalized_market, normalized_symbol, normalized_cik)

    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    timeout = httpx.Timeout(20.0, connect=5.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        if not normalized_cik:
            normalized_cik = await resolve_sec_cik(client, normalized_symbol)
        payload = await _sec_get_json(client, SEC_COMPANY_FACTS_URL.format(cik=normalized_cik))

    snapshot = normalize_sec_companyfacts(payload, symbol=normalized_symbol, fetched_at=_now_iso())
    async with _CACHE_LOCK:
        cache = await asyncio.to_thread(_read_cache)
        cache.setdefault("snapshots", {})[cache_key(normalized_market, normalized_symbol)] = snapshot
        await asyncio.to_thread(_write_cache, cache)
    return snapshot


async def resolve_sec_cik(client: httpx.AsyncClient, symbol: str) -> str:
    global _SEC_TICKER_INDEX
    if _SEC_TICKER_INDEX is None:
        payload = await _sec_get_json(client, SEC_TICKERS_URL)
        if not isinstance(payload, Mapping):
            raise FinancialSourceError("SEC ticker map returned a non-object payload")
        index: dict[str, dict[str, Any]] = {}
        for raw in payload.values():
            if not isinstance(raw, Mapping):
                continue
            ticker = str(raw.get("ticker") or "").strip().upper()
            if ticker:
                index[ticker] = dict(raw)
        _SEC_TICKER_INDEX = index
    row = _SEC_TICKER_INDEX.get(symbol.upper())
    if not row:
        raise FinancialSourceError(f"SEC ticker map does not contain {symbol}")
    return normalize_cik(str(row.get("cik_str") or ""))


async def _sec_get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    global _SEC_NEXT_REQUEST_AT
    last_error: Exception | None = None
    for attempt in range(2):
        async with _SEC_REQUEST_LOCK:
            loop = asyncio.get_running_loop()
            delay = max(0.0, _SEC_NEXT_REQUEST_AT - loop.time())
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await client.get(url)
                _SEC_NEXT_REQUEST_AT = loop.time() + SEC_REQUEST_INTERVAL_SECONDS
            except httpx.HTTPError as error:
                _SEC_NEXT_REQUEST_AT = loop.time() + SEC_REQUEST_INTERVAL_SECONDS
                last_error = error
                response = None
        if response is None:
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            raise FinancialSourceError(f"SEC request failed: {last_error}") from last_error
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as error:
                raise FinancialSourceError("SEC returned invalid JSON") from error
            if not isinstance(payload, dict):
                raise FinancialSourceError("SEC returned a non-object payload")
            return payload
        if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
            await asyncio.sleep(1.0)
            continue
        raise FinancialSourceError(f"SEC returned HTTP {response.status_code}")
    raise FinancialSourceError(f"SEC request failed: {last_error}")


def normalize_sec_companyfacts(payload: Mapping[str, Any], *, symbol: str, fetched_at: str) -> dict[str, Any]:
    cik = normalize_cik(str(payload.get("cik") or ""))
    entity = str(payload.get("entityName") or symbol).strip()
    facts_payload = payload.get("facts")
    if not isinstance(facts_payload, Mapping):
        raise FinancialSourceError("SEC companyfacts payload is missing facts")

    facts = []
    for spec in FINANCIAL_FACT_SPECS:
        normalized = _normalize_first_available_fact(facts_payload, spec, cik)
        if normalized:
            facts.append(normalized)
    derived = _derive_free_cash_flow(facts)
    status = "ok" if facts else "empty"
    warnings = [
        "SEC facts use standard taxonomies only; issuer-specific extension concepts are not silently substituted.",
        "Periods and forms must be compared before calculating growth; the project does not auto-generate an investment conclusion.",
    ]
    if not facts:
        warnings.append("No supported standard financial concepts were present in this filing history.")
    return {
        "schemaVersion": FINANCIAL_SCHEMA_VERSION,
        "market": "us",
        "symbol": symbol,
        "entity": entity,
        "cik": cik,
        "status": status,
        "asOf": max((point["end"] for fact in facts for point in fact["points"]), default=""),
        "fetchedAt": fetched_at,
        "cached": False,
        "analysisBoundary": "data_only_codex_analyzes",
        "source": {
            "id": "sec_edgar",
            "sourceUrl": SEC_COMPANY_FACTS_URL.format(cik=cik),
            "documentationUrl": SEC_API_DOCUMENTATION_URL,
            "method": "official_structured_xbrl",
        },
        "facts": facts,
        "derived": derived,
        "qualityWarnings": warnings,
    }


def _normalize_first_available_fact(
    facts_payload: Mapping[str, Any],
    spec: Mapping[str, Any],
    cik: str,
) -> dict[str, Any] | None:
    for taxonomy, concept in spec["aliases"]:
        taxonomy_payload = facts_payload.get(taxonomy)
        if not isinstance(taxonomy_payload, Mapping):
            continue
        concept_payload = taxonomy_payload.get(concept)
        if not isinstance(concept_payload, Mapping):
            continue
        points = _normalize_concept_points(concept_payload.get("units"), spec["periodType"], cik)
        if points:
            return {
                "id": spec["id"],
                "label": str(concept_payload.get("label") or spec["label"]),
                "description": str(concept_payload.get("description") or ""),
                "taxonomy": taxonomy,
                "concept": concept,
                "periodType": spec["periodType"],
                "points": points,
            }
    return None


def _normalize_concept_points(units: Any, period_type: str, cik: str) -> list[dict[str, Any]]:
    if not isinstance(units, Mapping):
        return []
    unit = _preferred_unit(units)
    rows = units.get(unit)
    if not unit or not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []

    latest_by_period: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        form = str(raw.get("form") or "")
        end = str(raw.get("end") or "")
        start = str(raw.get("start") or "")
        filed = str(raw.get("filed") or "")
        accession = str(raw.get("accn") or "")
        if form not in SEC_FORMS or not end or raw.get("val") is None or not accession:
            continue
        if period_type == "duration" and not start:
            continue
        if period_type == "instant":
            start = ""
        key = (start, end, str(raw.get("fy") or ""), str(raw.get("fp") or ""))
        current = latest_by_period.get(key)
        if current and (current["filed"], current["accession"]) >= (filed, accession):
            continue
        latest_by_period[key] = {
            "value": raw.get("val"),
            "unit": unit,
            "start": start,
            "end": end,
            "fy": raw.get("fy"),
            "fp": raw.get("fp"),
            "form": form,
            "filed": filed,
            "accession": accession,
            "frame": str(raw.get("frame") or ""),
            "sourceUrl": sec_filing_index_url(cik, accession),
        }
    points = sorted(latest_by_period.values(), key=lambda item: (item["end"], item["filed"]), reverse=True)
    for point in points:
        if not point["start"]:
            point.pop("start")
        if not point["frame"]:
            point.pop("frame")
    return points[:12]


def _preferred_unit(units: Mapping[str, Any]) -> str:
    if "USD" in units:
        return "USD"
    if "USD/shares" in units:
        return "USD/shares"
    currency_units = sorted(key for key in units if re.fullmatch(r"[A-Z]{3}", str(key)))
    if currency_units:
        return currency_units[0]
    share_units = sorted(key for key in units if str(key).lower() in {"shares", "pure"} or "/shares" in str(key))
    return share_units[0] if share_units else ""


def _derive_free_cash_flow(facts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("id")): item for item in facts}
    cash_flow = by_id.get("operating_cash_flow")
    capex = by_id.get("capital_expenditure")
    if not isinstance(cash_flow, Mapping) or not isinstance(capex, Mapping):
        return []
    capex_by_period = {_period_key(point): point for point in capex.get("points", []) if isinstance(point, Mapping)}
    points = []
    for operating_point in cash_flow.get("points", []):
        if not isinstance(operating_point, Mapping):
            continue
        capex_point = capex_by_period.get(_period_key(operating_point))
        if not capex_point or operating_point.get("unit") != capex_point.get("unit"):
            continue
        try:
            value = float(operating_point["value"]) - abs(float(capex_point["value"]))
        except (KeyError, TypeError, ValueError):
            continue
        points.append(
            {
                "value": value,
                "unit": operating_point["unit"],
                "start": operating_point.get("start", ""),
                "end": operating_point.get("end", ""),
                "fy": operating_point.get("fy"),
                "fp": operating_point.get("fp"),
                "method": "derived",
                "formula": "operating_cash_flow - abs(capital_expenditure)",
                "sourceUrls": list(
                    dict.fromkeys([str(operating_point.get("sourceUrl") or ""), str(capex_point.get("sourceUrl") or "")])
                ),
            }
        )
    for point in points:
        point["sourceUrls"] = [url for url in point["sourceUrls"] if url]
        if not point["start"]:
            point.pop("start")
    return [{"id": "free_cash_flow", "label": "Free cash flow", "periodType": "duration", "points": points[:12]}] if points else []


def _period_key(point: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(point.get("start") or ""),
        str(point.get("end") or ""),
        str(point.get("fy") or ""),
        str(point.get("fp") or ""),
    )


def empty_financial_snapshot(market: str, symbol: str, cik: str = "") -> dict[str, Any]:
    if market == "us":
        configured = bool(_sec_user_agent())
        status = "not_synced" if configured else "configuration_required"
        source = {
            "id": "sec_edgar",
            "sourceUrl": "https://data.sec.gov/",
            "documentationUrl": SEC_API_DOCUMENTATION_URL,
            "method": "official_structured_xbrl",
            "configured": configured,
        }
        warning = (
            "No cached SEC snapshot. Ask Codex to call sync_company_financials."
            if configured
            else f"Set {SEC_USER_AGENT_ENV}; no request was sent to SEC."
        )
    elif market == "hk":
        status = "license_required"
        source = {
            "id": "hkex_disclosures",
            "sourceUrl": HKEX_DISCLOSURE_URL,
            "documentationUrl": HKEX_DATA_PRODUCTS_URL,
            "method": "official_disclosure_or_licensed_feed",
            "configured": False,
        }
        warning = "HKEX structured financial feed is not configured; use the official disclosure page or a licensed HKEX product."
    else:
        status = "license_required"
        exchange_url = SSE_DISCLOSURE_URL if symbol.startswith(("5", "6", "9")) else SZSE_DISCLOSURE_URL
        source = {
            "id": "cninfo_disclosures",
            "sourceUrl": CNINFO_DISCLOSURE_URL,
            "exchangeDisclosureUrl": exchange_url,
            "documentationUrl": CNINFO_DATA_SERVICE_URL,
            "method": "official_disclosure_or_licensed_data_service",
            "configured": False,
        }
        warning = "CNINFO/exchange structured data authorization is not configured; undocumented page APIs are intentionally not used."
    return {
        "schemaVersion": FINANCIAL_SCHEMA_VERSION,
        "market": market,
        "symbol": symbol,
        "entity": "",
        "cik": cik,
        "status": status,
        "asOf": "",
        "fetchedAt": "",
        "cached": False,
        "analysisBoundary": "data_only_codex_analyzes",
        "source": source,
        "facts": [],
        "derived": [],
        "qualityWarnings": [warning],
    }


def normalize_market(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "us": "us",
        "usa": "us",
        "us_stock": "us",
        "hk": "hk",
        "hong_kong": "hk",
        "a": "a_share",
        "cn": "a_share",
        "a_share": "a_share",
    }
    market = aliases.get(normalized, "")
    if not market:
        raise ValueError("market must be us, hk, or a_share")
    return market


def normalize_symbol(market: str, value: str) -> str:
    symbol = str(value or "").strip().upper()
    if market == "us" and not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise ValueError("US symbol is invalid")
    if market == "hk":
        digits = re.sub(r"\D", "", symbol)
        if not 1 <= len(digits) <= 5:
            raise ValueError("HK symbol is invalid")
        symbol = digits.zfill(5)
    if market == "a_share" and not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("A-share symbol must contain six digits")
    return symbol


def normalize_cik(value: str) -> str:
    digits = str(value or "").strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError("CIK must contain at most ten digits")
    return digits.zfill(10)


def sec_filing_index_url(cik: str, accession: str) -> str:
    cik_path = str(int(cik))
    accession_path = re.sub(r"\D", "", accession)
    accession_name = quote(accession, safe="-")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{accession_name}-index.html"


def cache_key(market: str, symbol: str) -> str:
    return f"{market}:{symbol}"


def _read_cache() -> dict[str, Any]:
    try:
        payload = json.loads(FINANCIAL_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schemaVersion": FINANCIAL_SCHEMA_VERSION, "snapshots": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshots"), dict):
        return {"schemaVersion": FINANCIAL_SCHEMA_VERSION, "snapshots": {}}
    return payload


def _write_cache(payload: Mapping[str, Any]) -> None:
    FINANCIAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = FINANCIAL_CACHE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(FINANCIAL_CACHE_PATH)


def _sec_user_agent() -> str:
    return str(os.getenv(SEC_USER_AGENT_ENV) or "").strip()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
