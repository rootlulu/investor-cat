from __future__ import annotations

from collections import Counter
from typing import Any

from .investment_quality import build_metric_quality


STOCK_RESEARCH_SCHEMA_VERSION = 1
FUNDAMENTAL_METRICS = (
    ("revenue_growth", "营收增速"),
    ("earnings_growth", "归母净利润增速"),
    ("gross_margin", "毛利率"),
    ("operating_margin", "经营利润率"),
    ("operating_cash_flow", "经营现金流"),
    ("free_cash_flow", "自由现金流"),
    ("net_debt", "净负债或净现金"),
    ("roe_roic", "ROE / ROIC"),
    ("share_dilution", "股本稀释"),
)
VALUATION_GAPS = (
    "forward_pe",
    "ev_ebitda",
    "free_cash_flow_yield",
    "earnings_yield",
)
EXPECTATION_GAPS = (
    "consensus_revenue_growth",
    "consensus_eps_growth",
    "estimate_revision",
    "target_price_distribution",
)
EVENT_GAPS = ("earnings_calendar", "management_guidance", "corporate_actions")
QUOTE_FIELDS = ("marketCap", "floatMarketCap", "pe", "pb")


def build_stock_research_snapshot(
    stock: dict[str, Any],
    sections: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Build an evidence inventory; it deliberately does not make an investment call."""

    valuation_metrics = _valuation_metrics(stock, generated_at)
    valuation_evidence = [
        {"metricId": item["id"], "label": item["label"], "value": item["quality"]["value"]}
        for item in valuation_metrics
        if item["quality"]["value"] is not None
    ]
    valuation_sources = _unique(
        item["quality"].get("sourceUrl") for item in valuation_metrics if item["quality"].get("value") is not None
    )

    liquidity_fields = (
        ("price", "当前价"),
        ("amount", "成交额"),
        ("turnoverRate", "换手率"),
    )
    liquidity_evidence = [
        {"metricId": field, "label": label, "value": stock.get(field)}
        for field, label in liquidity_fields
        if stock.get(field) is not None
    ]
    liquidity_missing = [field for field, _ in liquidity_fields if stock.get(field) is None]

    ratings = _items(sections, "ratings")
    announcements = _items(sections, "announcements")
    news = _items(sections, "news")
    ownership_sections = ("shortInterest", "fundHoldings", "shareholders", "shareholderDistribution")
    ownership_counts = {name: len(_items(sections, name)) for name in ownership_sections}
    ownership_evidence = [
        {"metricId": name, "label": _ownership_label(name), "value": count}
        for name, count in ownership_counts.items()
        if count
    ]
    ownership_missing = [name for name, count in ownership_counts.items() if not count]

    capital_section = sections.get("capitalFlow") if isinstance(sections.get("capitalFlow"), dict) else {}
    capital_items = capital_section.get("items") if isinstance(capital_section.get("items"), list) else []
    capital_method = "proxy" if capital_section.get("method") == "proxy" or capital_section.get("kind") == "price_pressure_proxy" else "observed"
    capital_source_urls = _section_source_urls(capital_section)
    capital_status = (
        "ok"
        if capital_items and capital_method == "observed" and capital_source_urls
        else "partial"
        if capital_items
        else "unavailable"
    )
    capital_warnings = []
    if capital_method == "proxy":
        capital_warnings.append(capital_section.get("note") or "该序列是代理值，不是实测主力净流入。")
    if capital_items and not capital_source_urls:
        capital_warnings.append("该序列缺少可点击来源，暂不能标为完整可审计证据。")

    checklist = [
        _checklist_item(
            item_id="fundamentals",
            label="基本面与现金流",
            question="增长是否由可持续利润和现金流支撑？",
            priority="high",
            status="unavailable",
            method="observed",
            as_of=generated_at,
            source_urls=[],
            evidence=[],
            missing_metric_ids=[metric_id for metric_id, _ in FUNDAMENTAL_METRICS],
            next_action="接入交易所/公司公告或有审计许可的财务报表源，再核验增长、利润率、现金流、资本回报与杠杆。",
            quality_warnings=["当前没有可审计财报数据；行情、新闻和券商评级不能替代财务事实。"],
        ),
        _checklist_item(
            item_id="valuation",
            label="估值与隐含预期",
            question="当前估值对应了多高的增长与回报预期？",
            priority="high",
            status="partial" if valuation_evidence else "unavailable",
            method="observed",
            as_of=stock.get("updatedAt") or generated_at,
            source_urls=valuation_sources,
            evidence=valuation_evidence,
            missing_metric_ids=list(VALUATION_GAPS),
            next_action="先核验 PE/PB 的静态、滚动或预测口径，再结合可审计现金流计算 FCF yield、EV/EBITDA 与情景估值。",
            quality_warnings=["行情源未披露本页 PE/PB 的完整计算口径，不能直接跨市场或跨行业比较。"],
        ),
        _checklist_item(
            item_id="expectations",
            label="一致预期与修正",
            question="市场预期是在上修还是下修？",
            priority="high",
            status="partial" if ratings else "unavailable",
            method="observed",
            as_of=_section_as_of(sections.get("ratings"), generated_at),
            source_urls=_section_source_urls(sections.get("ratings")),
            evidence=[{"metricId": "rating_reports", "label": "评级/研报样本", "value": len(ratings)}] if ratings else [],
            missing_metric_ids=list(EXPECTATION_GAPS),
            next_action="接入可追溯的一致预期历史，关注收入/EPS 修正方向、分歧度与目标价分布，而不是只看单篇评级。",
            quality_warnings=["公开研报列表是选择性样本，不代表完整卖方一致预期。"] if ratings else [],
        ),
        _checklist_item(
            item_id="events",
            label="事件与催化剂",
            question="未来 30–90 天哪些事件能验证或推翻逻辑？",
            priority="high",
            status="partial" if announcements or news else "unavailable",
            method="observed",
            as_of=_latest_section_as_of(sections, ("announcements", "news"), generated_at),
            source_urls=_section_source_urls(sections.get("announcements")) + _section_source_urls(sections.get("news")),
            evidence=[
                {"metricId": "announcements", "label": "公司公告", "value": len(announcements)},
                {"metricId": "news", "label": "新闻", "value": len(news)},
            ] if announcements or news else [],
            missing_metric_ids=list(EVENT_GAPS),
            next_action="把业绩日历、管理层指引、解禁/回购/分红等事件结构化，并为每个催化剂写明证伪条件。",
            quality_warnings=["新闻只能作为线索；公司公告优先，且仍需阅读原文。"] if news else [],
        ),
        _checklist_item(
            item_id="ownership",
            label="股权、机构与做空",
            question="持有人结构和拥挤度是否正在变化？",
            priority="medium",
            status="partial" if ownership_evidence else "unavailable",
            method="observed",
            as_of=_latest_section_as_of(sections, ownership_sections, generated_at),
            source_urls=_many_section_source_urls(sections, ownership_sections),
            evidence=ownership_evidence,
            missing_metric_ids=ownership_missing,
            next_action="分别核对披露期、覆盖范围与变动方向；不同市场的基金、权益披露和融券口径不可直接相加。",
            quality_warnings=["各持仓来源披露期和覆盖范围可能不同。"] if ownership_evidence else [],
        ),
        _checklist_item(
            item_id="capital_flow",
            label="资金流与价格压力",
            question="资金证据是实测净流入，还是价格压力代理？",
            priority="medium",
            status=capital_status,
            method=capital_method,
            as_of=_section_as_of(capital_section, generated_at),
            source_urls=capital_source_urls,
            evidence=[{"metricId": "capital_flow_rows", "label": "可用序列点", "value": len(capital_items)}] if capital_items else [],
            missing_metric_ids=["observed_main_net_flow"] if capital_method == "proxy" or not capital_items else [],
            next_action="代理值只用于观察价格与成交额共振；没有实测分单数据时，不得解释为主力净流入。",
            quality_warnings=capital_warnings,
        ),
        _checklist_item(
            item_id="liquidity",
            label="流动性与交易约束",
            question="交易规模、换手和流通市值能否承载计划仓位？",
            priority="medium",
            status="ok" if not liquidity_missing else "partial" if liquidity_evidence else "unavailable",
            method="observed",
            as_of=stock.get("updatedAt") or generated_at,
            source_urls=_quote_source_urls(stock, ("price", "amount", "turnoverRate")),
            evidence=liquidity_evidence,
            missing_metric_ids=liquidity_missing,
            next_action="结合计划下单金额评估成交额占比、滑点、停牌/涨跌停和跨市场交易时段。",
            quality_warnings=[],
        ),
    ]

    available = sum(item["status"] not in {"unavailable", "empty", "unsupported", "error", "invalid"} for item in checklist)
    return {
        "schemaVersion": STOCK_RESEARCH_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "status": "partial" if available < len(checklist) or any(item["status"] == "partial" for item in checklist) else "ok",
        "coverage": {"available": available, "total": len(checklist)},
        "valuationMetrics": valuation_metrics,
        "checklist": checklist,
        "priorityUnknowns": [metric_id for metric_id, _ in FUNDAMENTAL_METRICS] + list(VALUATION_GAPS) + list(EXPECTATION_GAPS),
        "guardrails": [
            "本清单只整理证据与缺口，不生成买入、卖出或仓位建议。",
            "财报缺失时拒绝用行情、新闻、社区热度或单篇研报补造基本面结论。",
            "跨市场比较前先统一币种、会计口径、估值定义与数据截止日。",
        ],
    }


def build_portfolio_exposure_notice(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe watchlist composition without inventing portfolio weights."""

    labels: dict[str, str] = {}
    order: list[str] = []
    counts: Counter[str] = Counter()
    for stock in stocks:
        market = str(stock.get("market") or "unknown")
        if market not in labels:
            order.append(market)
            labels[market] = str(stock.get("marketLabel") or market)
        counts[market] += 1
    return {
        "status": "unavailable",
        "method": "not_computed",
        "basis": "watchlist_only",
        "reason": "当前只有自选清单，没有持仓数量/权重、成本、基准币种和现金仓位；不能据此计算组合暴露。",
        "requiredInputs": ["持仓数量或目标权重", "成本价", "基准币种与汇率", "现金仓位"],
        "composition": [{"market": market, "label": labels[market], "count": counts[market]} for market in order],
    }


def _valuation_metrics(stock: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    market = str(stock.get("market") or "")
    currency = {"a_share": "CNY", "hk": "HKD", "us": "USD"}.get(market)
    definitions = {
        "marketCap": "行情源返回的总市值。",
        "floatMarketCap": "行情源返回的流通市值。",
        "pe": "行情源返回的市盈率；静态、滚动或预测口径尚未核验。",
        "pb": "行情源返回的市净率；美股 Tencent 行情未提供时保持不可用。",
    }
    labels = {"marketCap": "总市值", "floatMarketCap": "流通市值", "pe": "PE", "pb": "PB"}
    ids = {"marketCap": "market_cap", "floatMarketCap": "float_market_cap", "pe": "pe", "pb": "pb"}
    field_sources = stock.get("fieldSources") if isinstance(stock.get("fieldSources"), dict) else {}
    result = []
    for field in QUOTE_FIELDS:
        metadata = field_sources.get(field) if isinstance(field_sources.get(field), dict) else {}
        value = stock.get(field)
        source_url = metadata.get("sourceUrl") or stock.get("sourceUrl") or stock.get("quoteUrl") or "https://quote.eastmoney.com/"
        method = metadata.get("method") if metadata.get("method") in {"observed", "derived"} else "observed"
        partial_definition = field in {"pe", "pb"} and value is not None
        quality = build_metric_quality(
            value=value,
            unit="元" if field in {"marketCap", "floatMarketCap"} else "倍",
            currency=currency if field in {"marketCap", "floatMarketCap"} else None,
            as_of=stock.get("updatedAt") or generated_at,
            fetched_at=generated_at,
            source_url=source_url,
            definition=definitions[field],
            method=method,
            status="unavailable" if value is None else "partial" if partial_definition else "ok",
            quality_flags=["provider_definition_unverified"] if partial_definition else metadata.get("qualityFlags") or [],
            formula=metadata.get("formula"),
        )
        result.append({"id": ids[field], "field": field, "label": labels[field], "quality": quality})
    return result


def _checklist_item(**values: Any) -> dict[str, Any]:
    return {
        "id": values["item_id"],
        "label": values["label"],
        "question": values["question"],
        "priority": values["priority"],
        "status": values["status"],
        "method": values["method"],
        "asOf": values["as_of"],
        "sourceUrls": _unique(values["source_urls"]),
        "evidence": values["evidence"],
        "missingMetricIds": values["missing_metric_ids"],
        "nextAction": values["next_action"],
        "qualityWarnings": [warning for warning in values["quality_warnings"] if warning],
    }


def _items(sections: dict[str, Any], name: str) -> list[dict[str, Any]]:
    section = sections.get(name)
    if not isinstance(section, dict) or not isinstance(section.get("items"), list):
        return []
    return [item for item in section["items"] if isinstance(item, dict)]


def _section_source_urls(section: Any) -> list[str]:
    if not isinstance(section, dict):
        return []
    urls = [section.get("sourceUrl"), section.get("url")]
    for item in section.get("items") if isinstance(section.get("items"), list) else []:
        if isinstance(item, dict):
            urls.extend((item.get("sourceUrl"), item.get("url")))
    return _unique(urls)


def _many_section_source_urls(sections: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    return _unique(url for name in names for url in _section_source_urls(sections.get(name)))


def _section_as_of(section: Any, fallback: str) -> str:
    if not isinstance(section, dict):
        return fallback
    candidates = [section.get("asOf"), section.get("updatedAt")]
    for item in section.get("items") if isinstance(section.get("items"), list) else []:
        if isinstance(item, dict):
            candidates.extend((item.get("asOf"), item.get("publishedAt"), item.get("date")))
    normalized = [str(value) for value in candidates if value]
    return max(normalized) if normalized else fallback


def _latest_section_as_of(sections: dict[str, Any], names: tuple[str, ...], fallback: str) -> str:
    candidates = [_section_as_of(sections.get(name), "") for name in names]
    return max((value for value in candidates if value), default=fallback)


def _quote_source_urls(stock: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    field_sources = stock.get("fieldSources") if isinstance(stock.get("fieldSources"), dict) else {}
    urls = []
    for field in fields:
        metadata = field_sources.get(field) if isinstance(field_sources.get(field), dict) else {}
        urls.append(metadata.get("sourceUrl"))
    urls.extend((stock.get("sourceUrl"), stock.get("quoteUrl")))
    return _unique(urls)


def _ownership_label(name: str) -> str:
    return {
        "shortInterest": "做空/融券样本",
        "fundHoldings": "基金/机构持仓样本",
        "shareholders": "主要股东样本",
        "shareholderDistribution": "股东户数样本",
    }[name]


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if value and str(value).strip()))
