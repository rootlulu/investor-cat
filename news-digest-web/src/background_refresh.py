from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import Any

from .ai_service import get_ai_news, get_ai_projects
from .commodity_service import get_commodities
from .consumption_service import get_consumption
from .energy_service import get_energy
from .game_service import get_games
from .macro_service import get_macro
from .news_service import get_news
from .stock_service import get_stocks
from .xueqiu_service import get_xueqiu
from .watchlist_service import prefetch_stock_watchlist_details

REFRESH_LOCK = asyncio.Lock()
REFRESH_TIMEOUT_SECONDS = {
    "news": 180,
    "ai-news": 180,
    "ai-projects": 180,
    "stocks": 900,
    "commodities": 180,
    "energy": 180,
    "consumption": 180,
    "macro": 180,
    "games": 180,
    "xueqiu": 360,
}
REFRESH_STATE: dict[str, dict[str, Any]] = {
    "news": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "ai-news": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "ai-projects": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "stocks": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "commodities": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "energy": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "consumption": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "macro": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "games": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
    "xueqiu": {
        "status": "idle",
        "version": 0,
        "runId": 0,
        "startedAt": "",
        "finishedAt": "",
        "message": "",
        "refreshed": False,
    },
}

STARTUP_REFRESH_KINDS = tuple(REFRESH_STATE)


async def start_background_refresh(kind: str, reason: str = "manual", force: bool = False) -> dict[str, Any]:
    if kind not in REFRESH_STATE:
        raise ValueError(f"unknown refresh kind: {kind}")

    async with REFRESH_LOCK:
        state = REFRESH_STATE[kind]
        if state["status"] == "running":
            return dict(state)

        run_id = int(state.get("runId", 0)) + 1
        state.update(
            {
                "status": "running",
                "runId": run_id,
                "startedAt": now_iso(),
                "finishedAt": "",
                "message": f"{reason} 后台刷新中",
                "refreshed": False,
                "authRequired": False,
            }
        )
        asyncio.create_task(run_refresh(kind, reason, run_id, force))
        return dict(state)


async def start_startup_refreshes() -> None:
    for kind in STARTUP_REFRESH_KINDS:
        await start_background_refresh(kind, "startup", force=True)


async def run_refresh(kind: str, reason: str, run_id: int, force: bool = False) -> None:
    state = REFRESH_STATE[kind]
    try:
        if reason != "startup":
            await asyncio.sleep(random.uniform(1.0, 3.0))

        if kind == "news":
            data = await asyncio.wait_for(
                get_news(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "ai-news":
            data = await asyncio.wait_for(
                get_ai_news(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "ai-projects":
            data = await asyncio.wait_for(
                get_ai_projects(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "stocks":
            data = await asyncio.wait_for(
                get_stocks(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
            try:
                prefetch = await asyncio.wait_for(
                    prefetch_stock_watchlist_details(force=force and reason != "startup"),
                    timeout=360,
                )
                data["watchlistDetailPrefetch"] = prefetch
                if prefetch.get("errors"):
                    data.setdefault("errors", []).extend(prefetch["errors"])
            except Exception as detail_error:
                data.setdefault("errors", []).append(f"自选详情预抓取未完成：{detail_error}")
        elif kind == "commodities":
            data = await asyncio.wait_for(
                get_commodities(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "energy":
            data = await asyncio.wait_for(
                get_energy(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "consumption":
            data = await asyncio.wait_for(
                get_consumption(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "macro":
            data = await asyncio.wait_for(
                get_macro(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        elif kind == "games":
            data = await asyncio.wait_for(
                get_games(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )
        else:
            data = await asyncio.wait_for(
                get_xueqiu(refresh=True, allow_stale=False, force=force),
                timeout=REFRESH_TIMEOUT_SECONDS[kind],
            )

        if kind == "xueqiu" and data.get("authRequired"):
            async with REFRESH_LOCK:
                if state.get("runId") != run_id:
                    return
                state["status"] = "error"
                state["finishedAt"] = now_iso()
                state["refreshed"] = False
                state["generatedAt"] = data.get("generatedAt", "")
                state["message"] = data.get("loginMessage") or "雪球抓取失败，需要登录或完成滑块验证"
                state["authRequired"] = True
            return

        refreshed = (
            not data.get("cached")
            and not data.get("stale")
            and not data.get("throttled")
            and data.get("hasData", True)
        )
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            state["status"] = "done" if refreshed else "skipped"
            state["finishedAt"] = now_iso()
            state["refreshed"] = refreshed
            state["generatedAt"] = data.get("generatedAt", "")
            state["message"] = "后台刷新完成" if refreshed else "半小时内已有快照，跳过真实抓取"
            state["authRequired"] = False
            if refreshed:
                state["version"] += 1
    except TimeoutError:
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            state["status"] = "error"
            state["finishedAt"] = now_iso()
            state["refreshed"] = False
            state["message"] = f"{kind} refresh timed out after {REFRESH_TIMEOUT_SECONDS[kind]} seconds"
    except Exception as error:
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            state["status"] = "error"
            state["finishedAt"] = now_iso()
            state["refreshed"] = False
            state["message"] = f"后台刷新失败：{error}"


async def refresh_status() -> dict[str, dict[str, Any]]:
    async with REFRESH_LOCK:
        return {key: dict(value) for key, value in REFRESH_STATE.items()}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
