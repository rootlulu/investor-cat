"""Exercise the stdio MCP adapter against a running local News Digest API."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT_DIR = Path(__file__).resolve().parents[1]


async def smoke(base_url: str) -> dict:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.xueqiu_mcp_server"],
        cwd=ROOT_DIR,
        env={
            "NEWS_DIGEST_BASE_URL": base_url,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            status = await session.call_tool("get_corpus_status", {})
            if status.isError:
                raise RuntimeError("get_corpus_status returned an MCP error")
            return {
                "server": initialized.serverInfo.name,
                "toolCount": len(tools.tools),
                "profileCount": len(status.structuredContent.get("profiles", [])),
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(smoke(args.base_url)), ensure_ascii=False))


if __name__ == "__main__":
    main()
