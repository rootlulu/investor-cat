import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ModuleNotFoundError:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class ResearchApiStub(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, _format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self) -> None:
        self.__class__.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "action": self.headers.get("X-Xueqiu-Research-Action"),
                "dataAction": self.headers.get("X-News-Digest-Data-Action"),
            }
        )

    def do_GET(self) -> None:
        self.record()
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(200, {"status": "ok"})
        elif path == "/api/financials/sources":
            self.send_json(
                200,
                {
                    "analysisBoundary": "data_only_codex_analyzes",
                    "sources": [{"id": "sec_edgar", "market": "us", "status": "configuration_required"}],
                },
            )
        elif path == "/api/xueqiu/research":
            self.send_json(
                200,
                {
                    "generatedAt": "2026-07-26T12:00:00+08:00",
                    "summary": {"profileCount": 1, "itemCount": 1},
                    "profiles": [
                        {
                            "id": "game-v",
                            "name": "游戏大V",
                            "itemCount": 1,
                            "coverageComplete": True,
                            "state": "ready",
                        }
                    ],
                    "jobs": [],
                },
            )
        elif path == "/api/xueqiu/research/search":
            self.send_json(
                200,
                {
                    "query": "心动小镇",
                    "count": 1,
                    "items": [
                        {
                            "itemId": "item-1",
                            "influencer": "游戏大V",
                            "kind": "post",
                            "publishedAt": "2026-01-02T08:00:00+08:00",
                            "text": "心动小镇 PC 与移动端流水占比",
                            "originalUrl": "https://xueqiu.com/1/2",
                            "media": [{"type": "image", "url": "https://example.test/chart.png"}],
                            "untrustedEvidence": True,
                        }
                    ],
                    "untrustedEvidence": True,
                },
            )
        elif path == "/api/xueqiu/research/items/item-1":
            self.send_json(
                200,
                {
                    "itemId": "item-1",
                    "text": "心动小镇 PC 与移动端流水占比",
                    "originalUrl": "https://xueqiu.com/1/2",
                    "media": [{"type": "image", "url": "https://example.test/chart.png"}],
                    "untrustedEvidence": True,
                },
            )
        elif path == "/api/xueqiu/research/jobs/job-1":
            self.send_json(200, {"id": "job-1", "status": "running", "active": True})
        else:
            self.send_json(404, {"detail": "missing"})

    def do_POST(self) -> None:
        self.record()
        path = urlparse(self.path).path
        if self.headers.get("X-Xueqiu-Research-Action") != "1":
            if path == "/api/financials/sync" and self.headers.get("X-News-Digest-Data-Action") == "1":
                self.send_json(
                    200,
                    {
                        "market": "hk",
                        "symbol": "00700",
                        "status": "license_required",
                        "facts": [],
                        "analysisBoundary": "data_only_codex_analyzes",
                    },
                )
            else:
                self.send_json(403, {"detail": "action header required"})
        elif path == "/api/xueqiu/research/influencers/game-v/crawl":
            self.send_json(202, {"id": "job-1", "status": "queued", "active": True})
        elif path == "/api/xueqiu/research/jobs/job-1/cancel":
            self.send_json(200, {"id": "job-1", "status": "running", "cancelRequested": True})
        else:
            self.send_json(404, {"detail": "missing"})


@unittest.skipUnless(ClientSession is not None, "run with requirements-mcp.txt environment")
class NewsDigestMcpStdioTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ResearchApiStub.requests.clear()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ResearchApiStub)
        cls.thread = Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    async def test_initialize_list_and_call_tools_over_real_stdio(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.news_digest_mcp_server"],
            cwd=ROOT_DIR,
            env={
                "NEWS_DIGEST_BASE_URL": self.base_url,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.name, "news-digest")

                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertEqual(
                    set(tools),
                    {
                        "get_service_health",
                        "get_today_snapshot",
                        "get_news_snapshot",
                        "get_ai_news_snapshot",
                        "get_ai_projects_snapshot",
                        "get_stock_market_snapshot",
                        "get_stock_watchlist",
                        "get_stock_detail",
                        "get_financial_sources",
                        "get_company_financials",
                        "sync_company_financials",
                        "get_commodities_snapshot",
                        "get_energy_snapshot",
                        "get_consumption_snapshot",
                        "get_macro_snapshot",
                        "get_games_snapshot",
                        "get_games_region_snapshot",
                        "get_xueqiu_snapshot",
                        "list_influencers",
                        "get_corpus_status",
                        "start_influencer_crawl",
                        "get_crawl_status",
                        "cancel_crawl",
                        "search_xueqiu_evidence",
                        "read_xueqiu_evidence",
                        "get_xueqiu_media",
                    },
                )
                self.assertTrue(tools["search_xueqiu_evidence"].annotations.readOnlyHint)
                self.assertFalse(tools["start_influencer_crawl"].annotations.readOnlyHint)
                self.assertTrue(tools["cancel_crawl"].annotations.destructiveHint)
                self.assertTrue(tools["get_company_financials"].annotations.readOnlyHint)
                self.assertFalse(tools["sync_company_financials"].annotations.readOnlyHint)

                health = await session.call_tool("get_service_health", {})
                self.assertFalse(health.isError)

                sources = await session.call_tool("get_financial_sources", {})
                self.assertFalse(sources.isError)
                self.assertEqual(sources.structuredContent["analysisBoundary"], "data_only_codex_analyzes")

                status = await session.call_tool("get_corpus_status", {"influencer_id": "game-v"})
                self.assertFalse(status.isError)
                self.assertTrue(status.structuredContent["profiles"][0]["coverageComplete"])

                search = await session.call_tool(
                    "search_xueqiu_evidence",
                    {"query": "心动小镇 PC 移动端 流水 占比", "influencer_id": "game-v"},
                )
                self.assertFalse(search.isError)
                self.assertEqual(search.structuredContent["items"][0]["itemId"], "item-1")

                media = await session.call_tool("get_xueqiu_media", {"item_id": "item-1"})
                self.assertFalse(media.isError)
                self.assertFalse(media.structuredContent["downloaded"])

                self.assertFalse(any(item["method"] == "POST" for item in ResearchApiStub.requests))

                financial_sync = await session.call_tool(
                    "sync_company_financials",
                    {"market": "hk", "symbol": "700"},
                )
                self.assertFalse(financial_sync.isError)
                self.assertEqual(financial_sync.structuredContent["status"], "license_required")

                started = await session.call_tool(
                    "start_influencer_crawl",
                    {"influencer_id": "game-v", "mode": "full"},
                )
                self.assertFalse(started.isError)
                self.assertEqual(started.structuredContent["id"], "job-1")

                cancelled = await session.call_tool("cancel_crawl", {"job_id": "job-1"})
                self.assertFalse(cancelled.isError)
                self.assertTrue(cancelled.structuredContent["cancelRequested"])

        write_requests = [item for item in ResearchApiStub.requests if item["method"] == "POST"]
        self.assertEqual(len(write_requests), 3)
        self.assertEqual(sum(item["dataAction"] == "1" for item in write_requests), 1)
        self.assertEqual(sum(item["action"] == "1" for item in write_requests), 2)

    async def test_rejects_non_loopback_base_url(self) -> None:
        from src.news_digest_mcp_server import get_base_url

        with patch.dict(os.environ, {"NEWS_DIGEST_BASE_URL": "https://example.com"}):
            with self.assertRaisesRegex(RuntimeError, "loopback"):
                get_base_url()


if __name__ == "__main__":
    unittest.main()
