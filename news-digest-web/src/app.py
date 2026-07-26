from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .ai_service import get_ai_news, get_ai_projects
from .background_refresh import refresh_status, start_background_refresh, start_startup_refreshes
from .commodity_service import get_commodities
from .consumption_service import get_consumption
from .energy_service import get_energy
from .game_provider_service import (
    GameProviderError,
    cancel_game_provider_login,
    complete_game_provider_login,
    crawl_game_provider_rankings,
    get_game_provider_auth_states,
    start_game_provider_login,
)
from .game_service import get_games
from .macro_service import get_macro
from .news_service import get_news, render_markdown
from .stock_service import get_stocks
from .watchlist_service import delete_stock_from_watchlist, get_stock_watch_detail, get_stock_watchlist, import_stock_to_watchlist, update_stock_watchlist_item
from .xueqiu_research_service import (
    cancel_research_job,
    get_research_item,
    get_research_job,
    get_research_overview,
    initialize_research_runtime,
    search_research_evidence,
    start_research_crawl,
)
from .xueqiu_service import close_xueqiu_auth_session, get_xueqiu, get_xueqiu_auth_status, import_xueqiu_influencer, remove_xueqiu_influencer, search_xueqiu_users, start_xueqiu_auth_qrcode

ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT_DIR / "public"

app = FastAPI(title="News Digest", version="0.2.0")


@app.on_event("startup")
async def startup_refresh() -> None:
    await initialize_research_runtime()
    await start_startup_refreshes()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/news")
async def api_news(refresh: bool = False) -> dict:
    return await get_news(refresh=refresh)


@app.get("/api/ai-news")
async def api_ai_news(refresh: bool = False) -> dict:
    return await get_ai_news(refresh=refresh)


@app.get("/api/ai-projects")
async def api_ai_projects(refresh: bool = False) -> dict:
    return await get_ai_projects(refresh=refresh)


@app.get("/api/stocks")
async def api_stocks(refresh: bool = False) -> dict:
    return await get_stocks(refresh=refresh)


@app.get("/api/stock-watchlist")
async def api_stock_watchlist(refresh: bool = False) -> dict:
    return await get_stock_watchlist(refresh=refresh)


@app.post("/api/stock-watchlist/import")
async def api_import_stock_watchlist(payload: dict[str, Any]) -> dict:
    try:
        return await import_stock_to_watchlist(
            str(payload.get("query") or payload.get("code") or ""),
            market=str(payload.get("market") or ""),
            name=str(payload.get("name") or ""),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/stock-watchlist/{stock_id}")
async def api_stock_watch_detail(stock_id: str, refresh: bool = False) -> dict:
    return await get_stock_watch_detail(stock_id, refresh=refresh)


@app.patch("/api/stock-watchlist/{stock_id}")
async def api_update_stock_watchlist_item(stock_id: str, payload: dict[str, Any]) -> dict:
    try:
        return await update_stock_watchlist_item(stock_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/stock-watchlist/{stock_id}")
async def api_delete_stock_watchlist_item(stock_id: str) -> dict:
    try:
        return await delete_stock_from_watchlist(stock_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/commodities")
async def api_commodities(refresh: bool = False) -> dict:
    return await get_commodities(refresh=refresh)


@app.get("/api/energy")
async def api_energy(refresh: bool = False) -> dict:
    return await get_energy(refresh=refresh)


@app.get("/api/consumption")
async def api_consumption(refresh: bool = False) -> dict:
    return await get_consumption(refresh=refresh)


@app.get("/api/macro")
async def api_macro(refresh: bool = False) -> dict:
    return await get_macro(refresh=refresh)


@app.get("/api/games")
async def api_games(refresh: bool = False) -> dict:
    return await get_games(refresh=refresh)


@app.get("/api/games/providers/auth")
async def api_game_provider_auth_states() -> dict:
    return await get_game_provider_auth_states()


@app.post("/api/games/providers/{provider}/login")
async def api_start_game_provider_login(provider: str) -> dict:
    try:
        return await start_game_provider_login(provider)
    except GameProviderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/games/providers/{provider}/login/complete")
async def api_complete_game_provider_login(provider: str) -> dict:
    try:
        return await complete_game_provider_login(provider)
    except GameProviderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/games/providers/{provider}/login")
async def api_cancel_game_provider_login(provider: str) -> dict:
    try:
        return await cancel_game_provider_login(provider)
    except GameProviderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/games/providers/{provider}/crawl")
async def api_crawl_game_provider(provider: str, country_code: str = "cn") -> dict:
    try:
        result = await crawl_game_provider_rankings(provider, country_code)
        result["games"] = await get_games(force=True)
        return result
    except GameProviderError as error:
        status_code = 429 if "低频保护" in str(error) or "冷却" in str(error) else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@app.get("/api/xueqiu")
async def api_xueqiu(refresh: bool = False) -> dict:
    return await get_xueqiu(refresh=refresh)


@app.post("/api/xueqiu/import")
async def api_import_xueqiu_influencer(payload: dict[str, Any]) -> dict:
    try:
        return await import_xueqiu_influencer(
            str(payload.get("query") or payload.get("url") or payload.get("userId") or ""),
            name=str(payload.get("name") or ""),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/xueqiu/search-users")
async def api_search_xueqiu_users(q: str = "", limit: int = 6) -> dict:
    return await search_xueqiu_users(q, limit=limit)


@app.delete("/api/xueqiu/influencers/{influencer_id}")
async def api_remove_xueqiu_influencer(influencer_id: str) -> dict:
    try:
        return await remove_xueqiu_influencer(influencer_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/xueqiu/auth/qrcode")
async def api_start_xueqiu_auth_qrcode(force: bool = False) -> dict:
    return await start_xueqiu_auth_qrcode(force=force)


@app.get("/api/xueqiu/auth/status")
async def api_xueqiu_auth_status() -> dict:
    return await get_xueqiu_auth_status()


@app.delete("/api/xueqiu/auth/session")
async def api_close_xueqiu_auth_session() -> dict:
    return await close_xueqiu_auth_session()


def require_xueqiu_research_action(action: str | None) -> None:
    if action != "1":
        raise HTTPException(
            status_code=403,
            detail="雪球研究写操作仅允许由明确的本机交互触发",
        )


@app.get("/api/xueqiu/research")
async def api_xueqiu_research() -> dict:
    return await get_research_overview()


@app.post("/api/xueqiu/research/influencers/{influencer_id}/crawl", status_code=202)
async def api_start_xueqiu_research_crawl(
    influencer_id: str,
    payload: dict[str, Any],
    research_action: str | None = Header(None, alias="X-Xueqiu-Research-Action"),
) -> dict:
    require_xueqiu_research_action(research_action)
    try:
        return await start_research_crawl(influencer_id, str(payload.get("mode") or "full"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/xueqiu/research/jobs/{job_id}")
async def api_xueqiu_research_job(job_id: str) -> dict:
    try:
        return await get_research_job(job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/xueqiu/research/jobs/{job_id}/cancel")
async def api_cancel_xueqiu_research_job(
    job_id: str,
    research_action: str | None = Header(None, alias="X-Xueqiu-Research-Action"),
) -> dict:
    require_xueqiu_research_action(research_action)
    try:
        return await cancel_research_job(job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/xueqiu/research/search")
async def api_search_xueqiu_research(
    q: str = "",
    influencer_id: str = "",
    influencer_id_camel: str = Query("", alias="influencerId"),
    kind: str = "",
    limit: int = 20,
) -> dict:
    try:
        return await search_research_evidence(
            q,
            influencer_id=influencer_id or influencer_id_camel,
            kind=kind,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/xueqiu/research/items/{item_id}")
async def api_xueqiu_research_item(item_id: str) -> dict:
    try:
        return await get_research_item(item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/refresh-status")
async def api_refresh_status() -> dict:
    return await refresh_status()


@app.post("/api/refresh/{kind}")
async def api_start_refresh(kind: str, reason: str = "manual", force: bool | None = None) -> dict:
    should_force = reason == "manual" if force is None else force
    return await start_background_refresh(kind, reason, force=should_force)


@app.get("/api/markdown", response_class=PlainTextResponse)
async def api_markdown() -> str:
    return render_markdown(await get_news())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/news")
async def news_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/ai")
async def ai_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/stocks")
async def stocks_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/stocks/{stock_id}")
async def stock_detail_page(stock_id: str) -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/commodities")
async def commodities_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/energy")
async def energy_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/consumption")
async def consumption_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/macro")
async def macro_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/games")
async def games_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/xueqiu")
async def xueqiu_page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=PUBLIC_DIR), name="public")
