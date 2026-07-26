import unittest
from unittest.mock import AsyncMock, patch

import httpx

from src.app import app


class XueqiuResearchApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_overview_is_read_only(self) -> None:
        payload = {"profiles": [], "activeJobs": []}
        with patch("src.app.get_research_overview", AsyncMock(return_value=payload)):
            response = await self.client.get("/api/xueqiu/research")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    async def test_crawl_requires_explicit_local_action_header(self) -> None:
        start = AsyncMock(return_value={"id": "job-1", "status": "queued"})
        with patch("src.app.start_research_crawl", start):
            rejected = await self.client.post(
                "/api/xueqiu/research/influencers/user-1/crawl",
                json={"mode": "full"},
            )
            accepted = await self.client.post(
                "/api/xueqiu/research/influencers/user-1/crawl",
                headers={"X-Xueqiu-Research-Action": "1"},
                json={"mode": "incremental"},
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 202)
        start.assert_awaited_once_with("user-1", "incremental")

    async def test_cancel_requires_action_header_and_maps_missing_job(self) -> None:
        cancel = AsyncMock(side_effect=ValueError("missing"))
        with patch("src.app.cancel_research_job", cancel):
            rejected = await self.client.post("/api/xueqiu/research/jobs/missing/cancel")
            missing = await self.client.post(
                "/api/xueqiu/research/jobs/missing/cancel",
                headers={"X-Xueqiu-Research-Action": "1"},
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(missing.status_code, 404)

    async def test_search_passes_filters_and_maps_validation_errors(self) -> None:
        search = AsyncMock(
            return_value={"query": "心动小镇", "count": 1, "items": [{"id": "item-1"}]}
        )
        with patch("src.app.search_research_evidence", search):
            response = await self.client.get(
                "/api/xueqiu/research/search",
                params={
                    "q": "心动小镇",
                    "influencer_id": "user-1",
                    "kind": "comment",
                    "limit": 8,
                },
            )

        self.assertEqual(response.status_code, 200)
        search.assert_awaited_once_with(
            "心动小镇",
            influencer_id="user-1",
            kind="comment",
            limit=8,
        )

        search.reset_mock()
        with patch("src.app.search_research_evidence", search):
            camel = await self.client.get(
                "/api/xueqiu/research/search",
                params={"q": "心动小镇", "influencerId": "user-2"},
            )
        self.assertEqual(camel.status_code, 200)
        search.assert_awaited_once_with(
            "心动小镇",
            influencer_id="user-2",
            kind="",
            limit=20,
        )

        with patch(
            "src.app.search_research_evidence",
            AsyncMock(side_effect=ValueError("query required")),
        ):
            invalid = await self.client.get("/api/xueqiu/research/search")
        self.assertEqual(invalid.status_code, 400)

    async def test_missing_job_and_item_are_404(self) -> None:
        with (
            patch("src.app.get_research_job", AsyncMock(side_effect=ValueError("missing"))),
            patch("src.app.get_research_item", AsyncMock(side_effect=ValueError("missing"))),
        ):
            job = await self.client.get("/api/xueqiu/research/jobs/missing")
            item = await self.client.get("/api/xueqiu/research/items/missing")

        self.assertEqual(job.status_code, 404)
        self.assertEqual(item.status_code, 404)


if __name__ == "__main__":
    unittest.main()
