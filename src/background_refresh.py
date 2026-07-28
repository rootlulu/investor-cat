from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from .ai_service import get_ai_news, get_ai_projects
from .commodity_service import get_commodities
from .consumption_service import get_consumption
from .energy_service import get_energy
from .game_region_service import get_region_games, region_payload_has_data
from .game_service import get_games
from .macro_service import get_macro
from .news_service import get_news
from .stock_service import get_stocks
from .xueqiu_service import get_xueqiu
from .watchlist_service import prefetch_stock_watchlist_details

REFRESH_LOCK = asyncio.Lock()
STARTUP_MAX_CONCURRENCY = 2
STARTUP_STAGGER_SECONDS = 0.75
_STARTUP_RUNTIME_LOOP: asyncio.AbstractEventLoop | None = None
_STARTUP_SEMAPHORE: asyncio.Semaphore | None = None
_STARTUP_PACE_LOCK: asyncio.Lock | None = None
_STARTUP_NEXT_START_AT = 0.0
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
    "games-region": 900,
    "xueqiu": 360,
}
REFRESH_DISPLAY_NAMES = {
    "news": "新闻",
    "ai-news": "AI 新闻",
    "ai-projects": "AI 工具",
    "stocks": "股票",
    "commodities": "大宗",
    "energy": "能源",
    "consumption": "消费",
    "macro": "宏观",
    "games": "游戏总览",
    "games-region": "游戏区域",
    "xueqiu": "雪球",
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
    "games-region": {
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
                "phase": "queued" if reason == "startup" else "running",
                "runId": run_id,
                "startedAt": now_iso(),
                "finishedAt": "",
                "message": f"{reason} {'排队等待后台刷新' if reason == 'startup' else '后台刷新中'}",
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
        if reason == "startup":
            async with startup_refresh_slot():
                async with REFRESH_LOCK:
                    if state.get("runId") != run_id:
                        return
                    state["phase"] = "running"
                    state["message"] = "startup 后台刷新中"
                data = await execute_refresh(kind, reason, force)
        else:
            await asyncio.sleep(random.uniform(1.0, 3.0))
            data = await execute_refresh(kind, reason, force)

        if kind == "xueqiu" and data.get("authRequired"):
            async with REFRESH_LOCK:
                if state.get("runId") != run_id:
                    return
                state["status"] = "error"
                state["phase"] = "finished"
                state["finishedAt"] = now_iso()
                state["refreshed"] = False
                state["generatedAt"] = data.get("generatedAt", "")
                state["message"] = data.get("loginMessage") or "雪球抓取失败，需要登录或完成滑块验证"
                state["authRequired"] = True
            return

        has_data = refresh_payload_has_data(kind, data)
        refreshed = (
            not data.get("cached")
            and not data.get("stale")
            and not data.get("throttled")
            and has_data
        )
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            failed_without_data = not has_data and bool(data.get("errors"))
            state["status"] = "done" if refreshed else "error" if failed_without_data else "skipped"
            state["phase"] = "finished"
            state["finishedAt"] = now_iso()
            state["refreshed"] = refreshed
            state["generatedAt"] = data.get("generatedAt", "")
            if refreshed:
                state["message"] = "后台刷新完成"
            elif failed_without_data:
                first_error = next((str(error) for error in data.get("errors", []) if error), "未返回可用数据")
                state["message"] = f"后台刷新失败：{first_error}"
            else:
                state["message"] = "半小时内已有快照，跳过真实抓取"
            state["authRequired"] = False
            if refreshed:
                state["version"] += 1
    except TimeoutError:
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            state["status"] = "error"
            state["phase"] = "finished"
            state["finishedAt"] = now_iso()
            state["refreshed"] = False
            label = REFRESH_DISPLAY_NAMES.get(kind, kind)
            state["message"] = f"{label}刷新超时（{REFRESH_TIMEOUT_SECONDS[kind]}秒），已保留现有快照"
    except Exception as error:
        async with REFRESH_LOCK:
            if state.get("runId") != run_id:
                return
            state["status"] = "error"
            state["phase"] = "finished"
            state["finishedAt"] = now_iso()
            state["refreshed"] = False
            state["message"] = f"后台刷新失败：{error}"


async def execute_refresh(kind: str, reason: str, force: bool) -> dict[str, Any]:
    if kind == "news":
        operation = get_news(refresh=True, allow_stale=False, force=force)
    elif kind == "ai-news":
        operation = get_ai_news(refresh=True, allow_stale=False, force=force)
    elif kind == "ai-projects":
        operation = get_ai_projects(refresh=True, allow_stale=False, force=force)
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
        return data
    elif kind == "commodities":
        operation = get_commodities(refresh=True, allow_stale=False, force=force)
    elif kind == "energy":
        operation = get_energy(refresh=True, allow_stale=False, force=force)
    elif kind == "consumption":
        operation = get_consumption(refresh=True, allow_stale=False, force=force)
    elif kind == "macro":
        operation = get_macro(refresh=True, allow_stale=False, force=force)
    elif kind == "games":
        operation = get_games(refresh=True, allow_stale=False, force=force)
    elif kind == "games-region":
        operation = get_region_games(
            cc="global",
            refresh=True,
            allow_stale=False,
            force=force,
        )
    elif kind == "xueqiu":
        operation = get_xueqiu(refresh=True, allow_stale=False, force=force)
    else:
        raise ValueError(f"unknown refresh kind: {kind}")
    return await asyncio.wait_for(operation, timeout=REFRESH_TIMEOUT_SECONDS[kind])


def refresh_payload_has_data(kind: str, data: dict[str, Any]) -> bool:
    if "hasData" in data:
        return bool(data.get("hasData"))
    if kind == "games-region":
        return region_payload_has_data(data)
    return True


@asynccontextmanager
async def startup_refresh_slot() -> AsyncIterator[None]:
    semaphore, pace_lock = _startup_runtime()
    async with semaphore:
        async with pace_lock:
            await _wait_for_startup_turn()
        yield


def _startup_runtime() -> tuple[asyncio.Semaphore, asyncio.Lock]:
    global _STARTUP_RUNTIME_LOOP, _STARTUP_SEMAPHORE, _STARTUP_PACE_LOCK, _STARTUP_NEXT_START_AT
    loop = asyncio.get_running_loop()
    if _STARTUP_RUNTIME_LOOP is not loop:
        _STARTUP_RUNTIME_LOOP = loop
        _STARTUP_SEMAPHORE = asyncio.Semaphore(STARTUP_MAX_CONCURRENCY)
        _STARTUP_PACE_LOCK = asyncio.Lock()
        _STARTUP_NEXT_START_AT = 0.0
    assert _STARTUP_SEMAPHORE is not None
    assert _STARTUP_PACE_LOCK is not None
    return _STARTUP_SEMAPHORE, _STARTUP_PACE_LOCK


async def _wait_for_startup_turn() -> None:
    global _STARTUP_NEXT_START_AT
    loop = asyncio.get_running_loop()
    delay = max(0.0, _STARTUP_NEXT_START_AT - loop.time())
    if delay:
        await asyncio.sleep(delay)
    _STARTUP_NEXT_START_AT = loop.time() + STARTUP_STAGGER_SECONDS


async def refresh_status() -> dict[str, dict[str, Any]]:
    async with REFRESH_LOCK:
        return {key: dict(value) for key, value in REFRESH_STATE.items()}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
