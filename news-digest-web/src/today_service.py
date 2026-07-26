from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .ai_service import read_ai_news_snapshot
from .commodity_service import read_commodity_snapshot
from .energy_service import read_energy_snapshot
from .investment_quality import build_metric_quality, quality_summary
from .stock_service import read_stock_snapshot


TODAY_SCHEMA_VERSION = 1
TODAY_CHANGE_LIMIT = 8
TODAY_AI_LIMIT = 4
TODAY_SOURCE_TIMEOUT_SECONDS = 1.5

SOURCE_DEFINITIONS = {
    "stocks": {"label": "股票", "href": "/stocks"},
    "commodities": {"label": "大宗", "href": "/commodities"},
    "energy": {"label": "能源", "href": "/energy"},
    "ai_news": {"label": "AI", "href": "/ai"},
}


async def get_today() -> dict[str, Any]:
    """Load independent snapshots and turn them into a read-only decision dashboard."""

    readers = {
        "stocks": read_stock_snapshot,
        "commodities": read_commodity_snapshot,
        "energy": read_energy_snapshot,
        "ai_news": read_ai_news_snapshot,
    }
    payloads: dict[str, dict[str, Any] | None] = {}
    failures: dict[str, str] = {}
    results = await asyncio.gather(*(_read_bounded_snapshot(source_id, reader) for source_id, reader in readers.items()))
    for source_id, payload, failure in results:
        payloads[source_id] = payload
        if failure:
            failures[source_id] = failure

    return build_today_dashboard(**payloads, failures=failures)


async def _read_bounded_snapshot(source_id: str, reader: Any) -> tuple[str, dict[str, Any] | None, str]:
    try:
        payload = await asyncio.wait_for(reader(), timeout=TODAY_SOURCE_TIMEOUT_SECONDS)
    except TimeoutError:
        return source_id, None, f"快照读取超时（{TODAY_SOURCE_TIMEOUT_SECONDS:g}s）"
    except Exception as error:
        return source_id, None, str(error) or error.__class__.__name__
    return source_id, payload, ""


def build_today_dashboard(
    *,
    stocks: Mapping[str, Any] | None,
    commodities: Mapping[str, Any] | None,
    energy: Mapping[str, Any] | None,
    ai_news: Mapping[str, Any] | None,
    failures: Mapping[str, str] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    payloads = {
        "stocks": stocks,
        "commodities": commodities,
        "energy": energy,
        "ai_news": ai_news,
    }
    failure_map = dict(failures or {})
    health = [build_source_health(source_id, payload, failure_map.get(source_id, "")) for source_id, payload in payloads.items()]

    changes = [
        *_stock_changes(stocks),
        *_commodity_changes(commodities),
        *_energy_changes(energy),
    ]
    changes.sort(key=lambda item: (-float(item.pop("_score", 0)), str(item.get("label") or "")))
    changes = changes[:TODAY_CHANGE_LIMIT]
    risks = build_today_risks(payloads, health)
    ai_focus = build_ai_focus(ai_news)
    impacts = build_directional_impacts(changes)
    source_quality_records = [
        {"quality": {"status": item["status"], "method": "observed"}}
        for item in health
    ]
    signal_quality = quality_summary([*source_quality_records, *changes, *ai_focus])

    return {
        "schemaVersion": TODAY_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "hasData": any(item["status"] in {"ok", "partial", "stale"} for item in health),
        "disclaimer": "仅聚合可审计事实与方向性推断，不构成投资建议。",
        "healthSummary": _health_summary(health),
        "qualitySummary": signal_quality,
        "health": health,
        "changes": changes,
        "risks": risks,
        "impacts": impacts,
        "aiFocus": ai_focus,
    }


def build_source_health(source_id: str, payload: Mapping[str, Any] | None, failure: str = "") -> dict[str, Any]:
    definition = SOURCE_DEFINITIONS[source_id]
    errors: list[str] = []
    warnings: list[str] = []
    quality: Mapping[str, Any] = {}
    if failure:
        status = "error"
        note = failure
        errors = [failure]
    elif not isinstance(payload, Mapping):
        status = "unavailable"
        note = "本轮没有返回快照"
    else:
        errors = _diagnostic_strings(payload.get("errors"))
        warnings = _diagnostic_strings(payload.get("warnings"))
        has_data = _payload_has_data(source_id, payload)
        quality = payload.get("qualitySummary") if isinstance(payload.get("qualitySummary"), Mapping) else {}
        stale_components = int(_number(quality.get("stale")))
        broken_components = int(_number(quality.get("error")) + _number(quality.get("partial")))
        if payload.get("stale"):
            status = "stale"
        elif not has_data:
            status = "empty"
        elif errors or stale_components or broken_components:
            status = "partial"
        else:
            status = "ok"
        note_parts = []
        if errors:
            note_parts.append(f"{len(errors)} 项来源异常")
        if warnings:
            note_parts.append(f"{len(warnings)} 项来源已切换备用")
        if stale_components and not payload.get("stale"):
            note_parts.append(f"{stale_components} 项子模块陈旧")
        if broken_components:
            note_parts.append(f"{broken_components} 项子模块异常")
        if _number(quality.get("invalid")):
            metric_label = "基差" if source_id == "commodities" else "指标"
            note_parts.append(f"{int(_number(quality.get('invalid')))} 项{metric_label}已安全禁算")
        if _number(quality.get("estimated")):
            note_parts.append(f"{int(_number(quality.get('estimated')))} 项含估算")
        note = "；".join(note_parts) or "快照可用"

    return {
        "id": source_id,
        "label": definition["label"],
        "href": definition["href"],
        "status": status,
        "asOf": str((payload or {}).get("generatedAt") or ""),
        "coverage": _source_coverage(source_id, payload),
        "note": note,
        "diagnostics": {"errors": errors, "warnings": warnings},
    }


def _payload_has_data(source_id: str, payload: Mapping[str, Any]) -> bool:
    if "hasData" in payload:
        return bool(payload.get("hasData"))
    if source_id == "stocks":
        return bool(payload.get("markets") or (payload.get("marginalSignals") or {}).get("cards"))
    if source_id == "commodities":
        return bool(payload.get("items"))
    if source_id == "energy":
        return bool(payload.get("rows") or payload.get("sections"))
    return bool(payload.get("items"))


def _source_coverage(source_id: str, payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return "0"
    if source_id == "stocks":
        market_count = len(payload.get("markets") or [])
        signal_count = len((payload.get("marginalSignals") or {}).get("cards") or [])
        return f"{market_count} 个市场 · {signal_count} 个边际信号"
    if source_id == "commodities":
        return f"{len(payload.get('items') or [])} 个品种"
    if source_id == "energy":
        return f"{len(payload.get('rows') or [])} 个实物指标"
    return f"{len(payload.get('items') or [])} 条近 7 日新闻"


def _stock_changes(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    results = []
    for market in payload.get("markets") or []:
        if not isinstance(market, Mapping):
            continue
        source_url = str(market.get("sourceUrl") or "").strip()
        as_of = str(market.get("dataTimestamp") or payload.get("generatedAt") or "").strip()
        if not source_url or not as_of:
            continue
        for index in market.get("indices") or []:
            if not isinstance(index, Mapping):
                continue
            value = _finite(index.get("changePct"))
            if value is None:
                continue
            item_id = str(index.get("symbol") or index.get("name") or "index")
            results.append(
                _change_item(
                    item_id=f"stock-{item_id}",
                    domain="stocks",
                    label=str(index.get("name") or item_id),
                    value=value,
                    unit="%",
                    as_of=as_of,
                    source_url=source_url,
                    definition="指数相对上一交易日收盘的涨跌幅",
                    method="observed",
                    status="stale" if payload.get("stale") or market.get("stale") else "ok",
                    context=str(market.get("name") or "股票市场"),
                    href="/stocks#stock-market",
                )
            )
    return results


def _commodity_changes(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    results = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        quality = item.get("basisQuality") if isinstance(item.get("basisQuality"), Mapping) else {}
        source_url = str(item.get("domesticFutureSourceUrl") or quality.get("sourceUrl") or "").strip()
        as_of = str(item.get("domesticFutureDate") or payload.get("generatedAt") or "").strip()
        value = _finite(item.get("domesticFutureChangePct"))
        if value is None or not source_url or not as_of:
            continue
        results.append(
            _change_item(
                item_id=f"commodity-{item.get('id') or item.get('name') or 'future'}",
                domain="commodities",
                label=f"{item.get('name') or '商品'}国内期货",
                value=value,
                unit="%",
                as_of=as_of,
                source_url=source_url,
                definition="国内期货最新价相对上一结算价的涨跌幅",
                method="observed",
                status="stale" if payload.get("stale") else "ok",
                context=str(item.get("sector") or "大宗商品"),
                href="/commodities",
            )
        )
    return results


def _energy_changes(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    results = []
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        row_quality = row.get("quality") if isinstance(row.get("quality"), Mapping) else {}
        if row_quality.get("method") != "observed" or row_quality.get("status") not in {"ok", "stale"}:
            continue
        value = _finite(row.get("yoy"))
        as_of = str(row.get("period") or row_quality.get("asOf") or "").strip()
        source_url = str(row.get("sourceUrl") or row_quality.get("sourceUrl") or "").strip()
        if value is None or not as_of or not source_url:
            continue
        results.append(
            _change_item(
                item_id=f"energy-{row.get('id') or row.get('name') or 'metric'}",
                domain="energy",
                label=f"{row.get('name') or '能源指标'}同比",
                value=value,
                unit="%",
                as_of=as_of,
                source_url=source_url,
                definition="官方披露的当期实物量同比增速",
                method="observed",
                status="stale" if payload.get("stale") or row_quality.get("status") == "stale" else "ok",
                context=str(row.get("category") or row.get("unit") or "能源生产"),
                href="/energy",
            )
        )
    return results


def _change_item(
    *,
    item_id: str,
    domain: str,
    label: str,
    value: float,
    unit: str,
    as_of: str,
    source_url: str,
    definition: str,
    method: str,
    status: str,
    context: str,
    href: str,
) -> dict[str, Any]:
    quality = build_metric_quality(
        value=value,
        unit=unit,
        as_of=as_of,
        source_url=source_url,
        definition=definition,
        method=method,
        status=status,
    )
    return {
        "id": item_id,
        "domain": domain,
        "label": label,
        "value": value,
        "unit": unit,
        "direction": "up" if value > 0 else "down" if value < 0 else "flat",
        "context": context,
        "href": href,
        "quality": quality,
        "_score": abs(value),
    }


def build_today_risks(
    payloads: Mapping[str, Mapping[str, Any] | None],
    health: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for source in health:
        if source["status"] == "ok":
            continue
        risks.append(
            {
                "id": f"source-{source['id']}",
                "domain": source["id"],
                "severity": "high" if source["status"] in {"error", "unavailable", "empty"} else "medium",
                "title": f"{source['label']}数据{_status_label(source['status'])}",
                "detail": source["note"],
                "impact": "相关结论需要降权，优先核对来源和时间。",
                "href": source["href"],
            }
        )

    commodity_payload = payloads.get("commodities") or {}
    invalid_items = [
        item
        for item in commodity_payload.get("items") or []
        if isinstance(item, Mapping) and (item.get("basisQuality") or {}).get("status") == "invalid"
    ]
    if invalid_items:
        names = "、".join(str(item.get("name") or item.get("id") or "商品") for item in invalid_items[:3])
        risks.append(
            {
                "id": "commodity-basis-invalid",
                "domain": "commodities",
                "severity": "medium",
                "title": f"{len(invalid_items)} 个基差口径不可比",
                "detail": f"{names}{'等' if len(invalid_items) > 3 else ''}只保留原始参考，不进入信号。",
                "impact": "不能据此判断期现套利或库存紧张程度。",
                "href": "/commodities",
            }
        )

    energy_payload = payloads.get("energy") or {}
    estimated_count = int(_number((energy_payload.get("summary") or {}).get("estimatedPointCount")))
    if estimated_count:
        risks.append(
            {
                "id": "energy-estimated",
                "domain": "energy",
                "severity": "medium",
                "title": f"能源历史含 {estimated_count} 个估算点",
                "detail": "估算点只作趋势背景，以虚线标示，不计算环比且不进入今日显著变化。",
                "impact": "方向判断应等待下一次官方月度发布确认。",
                "href": "/energy",
            }
        )
    return risks[:8]


def build_ai_focus(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    results = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "").strip()
        published_at = str(item.get("publishedAt") or "").strip()
        source_url = str(item.get("url") or "").strip()
        if not title or not published_at or not source_url:
            continue
        quality = build_metric_quality(
            value=title,
            unit="news item",
            as_of=published_at,
            source_url=source_url,
            definition="近 7 日 AI 主题新闻标题，未进行投资因果推断",
            method="observed",
            status="stale" if payload.get("stale") else "ok",
            published_at=published_at,
        )
        results.append(
            {
                "id": str(item.get("id") or source_url),
                "title": title,
                "category": str(item.get("categoryLabel") or item.get("category") or "AI"),
                "source": str(item.get("source") or "公开来源"),
                "url": source_url,
                "publishedAt": published_at,
                "quality": quality,
            }
        )
        if len(results) >= TODAY_AI_LIMIT:
            break
    return results


def build_directional_impacts(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    impacts = []
    for change in changes[:4]:
        value = float(change["value"])
        direction = "走强" if value > 0 else "走弱" if value < 0 else "持平"
        if change["domain"] == "stocks":
            implication = "可能对应风险偏好改善" if value > 0 else "可能对应风险偏好承压"
            check = "需结合市场扩散、成交额和对冲信号确认"
        elif change["domain"] == "commodities":
            implication = "可能改变相关产业链成本与库存预期"
            check = "需结合可比基差、库存类型和上下游关系确认"
        else:
            implication = "可能反映供给或需求侧实物量变化"
            check = "需结合季节性、累计同比和下一次官方发布确认"
        impacts.append(
            {
                "id": f"impact-{change['id']}",
                "title": f"{change['label']}{direction}",
                "statement": f"{implication}；{check}。",
                "method": "derived",
                "sourceId": change["id"],
                "asOf": change["quality"]["asOf"],
                "href": change["href"],
            }
        )
    return impacts


def _health_summary(health: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(health), "ok": 0, "stale": 0, "partial": 0, "empty": 0, "error": 0, "unavailable": 0}
    for item in health:
        status = str(item.get("status") or "")
        if status in summary:
            summary[status] += 1
    summary["problemCount"] = summary["total"] - summary["ok"]
    return summary


def _status_label(status: str) -> str:
    return {
        "stale": "陈旧",
        "partial": "部分异常",
        "empty": "为空",
        "error": "失败",
        "unavailable": "不可用",
    }.get(status, status)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number(value: Any) -> float:
    return _finite(value) or 0.0


def _diagnostic_strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item).strip())))
