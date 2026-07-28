from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


INVESTMENT_QUALITY_SCHEMA_VERSION = 1
METRIC_METHODS = frozenset({"observed", "derived", "estimated", "proxy"})
METRIC_STATUSES = frozenset(
    {
        "ok",
        "stale",
        "partial",
        "empty",
        "unsupported",
        "error",
        "unavailable",
        "invalid",
    }
)
PROBLEM_STATUSES = frozenset({"stale", "partial", "empty", "unsupported", "error", "unavailable", "invalid"})


def _required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def build_metric_quality(
    *,
    value: Any,
    unit: str,
    as_of: str,
    source_url: str,
    definition: str,
    method: str = "observed",
    status: str | None = None,
    currency: str | None = None,
    published_at: str | None = None,
    fetched_at: str | None = None,
    derived_at: str | None = None,
    coverage: Any = None,
    quality_flags: Sequence[str] = (),
    revision: str | int | None = None,
    formula: str | None = None,
) -> dict[str, Any]:
    """Build JSON-ready provenance metadata for an investment metric."""

    normalized_method = str(method or "").strip().lower()
    if normalized_method not in METRIC_METHODS:
        raise ValueError(f"unknown metric method: {method}")

    normalized_formula = _optional_text(formula)
    if normalized_method in {"proxy", "estimated"} and not normalized_formula:
        raise ValueError(f"{normalized_method} method requires formula")

    normalized_status = str(status or ("unavailable" if value is None else "ok")).strip().lower()
    if normalized_status not in METRIC_STATUSES:
        raise ValueError(f"unknown metric status: {status}")
    if value is None and normalized_status == "ok":
        raise ValueError("status ok requires a non-null value")

    flags = list(dict.fromkeys(str(flag).strip() for flag in quality_flags if str(flag).strip()))
    result: dict[str, Any] = {
        "schemaVersion": INVESTMENT_QUALITY_SCHEMA_VERSION,
        "value": value,
        "unit": _required_text(unit, "unit"),
        "asOf": _required_text(as_of, "as_of"),
        "sourceUrl": _required_text(source_url, "source_url"),
        "definition": _required_text(definition, "definition"),
        "method": normalized_method,
        "status": normalized_status,
        "qualityFlags": flags,
    }

    optional_fields = {
        "currency": _optional_text(currency),
        "publishedAt": _optional_text(published_at),
        "fetchedAt": _optional_text(fetched_at),
        "derivedAt": _optional_text(derived_at),
        "formula": normalized_formula,
    }
    result.update({key: field_value for key, field_value in optional_fields.items() if field_value is not None})
    if coverage is not None:
        result["coverage"] = coverage
    if revision is not None:
        result["revision"] = revision
    return result


def quality_summary(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Count quality states while treating pre-schema payloads as legacy."""

    summary = {
        "total": 0,
        "legacy": 0,
        "ok": 0,
        "stale": 0,
        "partial": 0,
        "empty": 0,
        "unsupported": 0,
        "error": 0,
        "unavailable": 0,
        "invalid": 0,
        "observed": 0,
        "derived": 0,
        "estimated": 0,
        "proxy": 0,
        "problemCount": 0,
    }
    for item in items:
        summary["total"] += 1
        quality = item.get("quality")
        if not isinstance(quality, Mapping):
            summary["legacy"] += 1
            continue

        status = str(quality.get("status") or "").strip().lower()
        method = str(quality.get("method") or "").strip().lower()
        if status in METRIC_STATUSES:
            summary[status] += 1
            if status in PROBLEM_STATUSES:
                summary["problemCount"] += 1
        else:
            summary["legacy"] += 1
        if method in METRIC_METHODS:
            summary[method] += 1
    return summary
