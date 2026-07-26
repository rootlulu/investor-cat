from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from src.app import app
from src.financial_service import (
    empty_financial_snapshot,
    financial_source_catalog,
    get_financial_snapshot,
    normalize_sec_companyfacts,
)


def sec_companyfacts_fixture() -> dict:
    revenue_rows = [
        {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "val": 1000,
            "accn": "0000000123-25-000001",
            "fy": 2024,
            "fp": "FY",
            "form": "10-K",
            "filed": "2025-02-01",
        },
        {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "val": 1010,
            "accn": "0000000123-25-000002",
            "fy": 2024,
            "fp": "FY",
            "form": "10-K/A",
            "filed": "2025-02-10",
        },
        {
            "start": "2025-01-01",
            "end": "2025-03-31",
            "val": 280,
            "accn": "0000000123-25-000010",
            "fy": 2025,
            "fp": "Q1",
            "form": "10-Q",
            "filed": "2025-05-01",
        },
        {
            "start": "2020-01-01",
            "end": "2020-12-31",
            "val": 1,
            "accn": "0000000123-21-000001",
            "fy": 2020,
            "fp": "FY",
            "form": "8-K",
            "filed": "2021-01-01",
        },
    ]
    return {
        "cik": 123,
        "entityName": "Example Corp",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "label": "Revenue",
                    "description": "Revenue from contracts with customers.",
                    "units": {"USD": revenue_rows},
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "label": "Operating cash flow",
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 200,
                                "accn": "0000000123-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    },
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "label": "Capital expenditure",
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 50,
                                "accn": "0000000123-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 2500,
                                "accn": "0000000123-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    },
                },
            }
        },
    }


def test_normalize_sec_companyfacts_preserves_filing_provenance_and_derives_fcf() -> None:
    snapshot = normalize_sec_companyfacts(
        sec_companyfacts_fixture(),
        symbol="EXM",
        fetched_at="2026-07-26T00:00:00+00:00",
    )

    assert snapshot["status"] == "ok"
    assert snapshot["cik"] == "0000000123"
    revenue = next(item for item in snapshot["facts"] if item["id"] == "revenue")
    assert [point["value"] for point in revenue["points"]] == [280, 1010]
    assert revenue["points"][1]["form"] == "10-K/A"
    assert revenue["points"][1]["accession"] == "0000000123-25-000002"
    assert revenue["points"][1]["sourceUrl"].startswith("https://www.sec.gov/Archives/edgar/data/123/")
    free_cash_flow = snapshot["derived"][0]
    assert free_cash_flow["id"] == "free_cash_flow"
    assert free_cash_flow["points"][0]["value"] == 150.0
    assert free_cash_flow["points"][0]["method"] == "derived"


def test_official_source_catalog_and_unlicensed_markets_are_explicit() -> None:
    with patch.dict(os.environ, {}, clear=True):
        catalog = financial_source_catalog()
        us = next(item for item in catalog["sources"] if item["market"] == "us")
        hk = next(item for item in catalog["sources"] if item["market"] == "hk")
        cn = next(item for item in catalog["sources"] if item["market"] == "a_share")

        assert us["status"] == "configuration_required"
        assert us["configured"] is False
        assert hk["status"] == "license_required"
        assert cn["status"] == "license_required"
        assert empty_financial_snapshot("hk", "00700")["facts"] == []
        assert empty_financial_snapshot("a_share", "600519")["facts"] == []


def test_v88_read_financial_snapshot_never_syncs_when_cache_is_missing(tmp_path) -> None:
    async def exercise() -> dict:
        with (
            patch("src.financial_service.FINANCIAL_CACHE_PATH", tmp_path / "financials.json"),
            patch.dict(os.environ, {}, clear=True),
            patch("src.financial_service._sec_get_json", new=AsyncMock()) as sec_get,
        ):
            snapshot = await get_financial_snapshot("us", "AAPL")
            sec_get.assert_not_awaited()
            return snapshot

    snapshot = asyncio.run(exercise())
    assert snapshot["status"] == "configuration_required"
    assert snapshot["facts"] == []


def test_financial_routes_are_data_only_and_sync_requires_explicit_action() -> None:
    client = TestClient(app)

    sources = client.get("/api/financials/sources")
    cached = client.get("/api/financials", params={"market": "hk", "symbol": "700"})
    rejected = client.post("/api/financials/sync", json={"market": "hk", "symbol": "700"})
    removed_agent = client.get("/api/investment-agent/readiness")

    assert sources.status_code == 200
    assert sources.json()["analysisBoundary"] == "data_only_codex_analyzes"
    assert cached.status_code == 200
    assert cached.json()["symbol"] == "00700"
    assert cached.json()["status"] == "license_required"
    assert rejected.status_code == 403
    assert removed_agent.status_code == 404
