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
            }
        )

    def do_GET(self) -> None:
        self.record()
        path = urlparse(self.path).path
        if path == "/api/xueqiu/research":
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
            self.send_json(403, {"detail": "action header required"})
        elif path == "/api/xueqiu/research/influencers/game-v/crawl":
            self.send_json(202, {"id": "job-1", "status": "queued", "active": True})
        elif path == "/api/xueqiu/research/jobs/job-1/cancel":
            self.send_json(200, {"id": "job-1", "status": "running", "cancelRequested": True})
        else:
            self.send_json(404, {"detail": "missing"})


@unittest.skipUnless(ClientSession is not None, "run with requirements-mcp.txt environment")
class XueqiuMcpStdioTests(unittest.IsolatedAsyncioTestCase):
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
            args=["-m", "src.xueqiu_mcp_server"],
            cwd=ROOT_DIR,
            env={
                "NEWS_DIGEST_BASE_URL": self.base_url,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.name, "xueqiu-research")

                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertEqual(
                    set(tools),
                    {
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
        self.assertEqual(len(write_requests), 2)
        self.assertTrue(all(item["action"] == "1" for item in write_requests))

    async def test_rejects_non_loopback_base_url(self) -> None:
        from src.xueqiu_mcp_server import get_base_url

        with patch.dict(os.environ, {"NEWS_DIGEST_BASE_URL": "https://example.com"}):
            with self.assertRaisesRegex(RuntimeError, "loopback"):
                get_base_url()


if __name__ == "__main__":
    unittest.main()
