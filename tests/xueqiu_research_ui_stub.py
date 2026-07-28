"""Deterministic local API fixture for manual/browser Xueqiu research UI smoke tests."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlparse


RESEARCH_OVERVIEW = {
    "generatedAt": "2026-07-26T12:00:00+08:00",
    "summary": {
        "profileCount": 2,
        "indexedProfileCount": 2,
        "itemCount": 152,
        "activeJobCount": 0,
    },
    "profiles": [
        {
            "id": "game-v",
            "userId": "10001",
            "name": "游戏研究大V",
            "profileUrl": "https://xueqiu.com/u/10001",
            "itemCount": 128,
            "postCount": 44,
            "repostCount": 12,
            "commentCount": 58,
            "replyCount": 14,
            "earliestAt": "2021-01-01T08:00:00+08:00",
            "latestAt": "2026-07-25T20:00:00+08:00",
            "coverageComplete": True,
            "state": "ready",
            "latestJob": {
                "id": "job-ready",
                "status": "ready",
                "pagesFetched": 18,
                "itemsUpserted": 128,
                "active": False,
            },
        },
        {
            "id": "partial-v",
            "userId": "10002",
            "name": "等待登录的大V",
            "profileUrl": "https://xueqiu.com/u/10002",
            "itemCount": 24,
            "postCount": 9,
            "repostCount": 2,
            "commentCount": 11,
            "replyCount": 2,
            "earliestAt": "2025-11-01T08:00:00+08:00",
            "latestAt": "2026-07-24T18:00:00+08:00",
            "coverageComplete": False,
            "state": "paused_auth",
            "latestJob": {
                "id": "job-auth",
                "status": "paused_auth",
                "pagesFetched": 3,
                "itemsUpserted": 24,
                "active": False,
                "authRequired": True,
                "resumable": True,
                "error": "雪球登录已失效，请扫码后继续",
            },
        },
    ],
    "jobs": [],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/xueqiu":
            self.send_json(
                200,
                {
                    "influencers": [],
                    "activities": [],
                    "summary": {},
                    "rangeLabel": "2026-07-20 至 2026-07-26",
                },
            )
        elif path == "/api/xueqiu/research":
            self.send_json(200, RESEARCH_OVERVIEW)
        elif path == "/api/xueqiu/research/search":
            self.send_json(
                200,
                {
                    "query": "心动小镇",
                    "count": 2,
                    "untrustedEvidence": True,
                    "items": [
                        {
                            "itemId": "evidence-1",
                            "influencerId": "game-v",
                            "influencer": "游戏研究大V",
                            "kind": "post",
                            "publishedAt": "2026-01-15T10:00:00+08:00",
                            "text": "心动小镇 2026 年 PC 与移动端流水占比需要按同一统计口径比较。",
                            "targetTitle": "示例证据，不代表真实结论",
                            "originalUrl": "https://xueqiu.com/10001/20001",
                            "media": [],
                            "score": -1.2,
                        },
                        {
                            "itemId": "evidence-2",
                            "influencerId": "game-v",
                            "influencer": "游戏研究大V",
                            "kind": "comment",
                            "publishedAt": "2026-02-02T11:30:00+08:00",
                            "text": "这个数字还需要原始流水数据才能确认。",
                            "targetTitle": "",
                            "originalUrl": "https://xueqiu.com/10001/20002",
                            "media": [],
                            "score": -0.8,
                        },
                    ],
                },
            )
        elif path.startswith("/api/xueqiu/research/jobs/"):
            self.send_json(200, {"id": "job-smoke", "status": "running", "active": True})
        else:
            self.send_json(404, {"detail": "fixture route not found"})

    def do_POST(self) -> None:
        if self.headers.get("X-Xueqiu-Research-Action") != "1":
            self.send_json(403, {"detail": "action header required"})
            return
        path = urlparse(self.path).path
        if path.endswith("/crawl"):
            self.send_json(202, {"id": "job-smoke", "status": "queued", "active": True})
        elif path.endswith("/cancel"):
            self.send_json(200, {"id": "job-smoke", "status": "running", "cancelRequested": True})
        else:
            self.send_json(404, {"detail": "fixture route not found"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5188)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
