from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import hashlib
import json
import os
import re
import threading
import time
from datetime import UTC, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlencode
from zoneinfo import ZoneInfo

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
XUEQIU_CONFIG_PATH = ROOT_DIR / "config" / "xueqiu_influencers.json"
XUEQIU_SETTINGS_PATH = ROOT_DIR / "config" / "xueqiu_settings.json"
XUEQIU_COOKIE_FILE = ROOT_DIR / "config" / "xueqiu_cookie.txt"

XUEQIU_HOME_URL = "https://xueqiu.com/"
XUEQIU_TOKEN_WARMUP_URL = "https://xueqiu.com/about"
XUEQIU_USER_SHOW_APIS = (
    "https://api.xueqiu.com/user/show.json",
    "https://xueqiu.com/user/show.json",
    "https://xueqiu.com/users/show.json",
)
XUEQIU_USER_SEARCH_APIS = (
    "https://api.xueqiu.com/query/v1/search/user.json",
    "https://api.xueqiu.com/users/search.json",
    "https://xueqiu.com/query/v1/search/user.json",
    "https://xueqiu.com/users/search.json",
)
XUEQIU_TIMELINE_APIS = (
    "https://api.xueqiu.com/v4/statuses/user_timeline.json",
    "https://xueqiu.com/v4/statuses/user_timeline.json",
    "https://xueqiu.com/statuses/user_timeline.json",
)
XUEQIU_COMMENT_TIMELINE_APIS = (
    "https://xueqiu.com/v4/statuses/comments_timeline.json",
    "https://xueqiu.com/statuses/comments_timeline.json",
)

CHINA_TZ = ZoneInfo("Asia/Shanghai")
XUEQIU_CACHE_SECONDS = 150
XUEQIU_SEARCH_CACHE_SECONDS = 60
XUEQIU_LOOKBACK_DAYS = 7
XUEQIU_FETCH_LIMIT = 20
XUEQIU_FETCH_MAX_PAGES = 5
XUEQIU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
XUEQIU_BROWSER_PROFILE_DIR = ROOT_DIR / "data" / "xueqiu-browser-profile"
XUEQIU_AUTH_PROFILE_DIR = ROOT_DIR / "data" / "xueqiu-auth-profile"
XUEQIU_BROWSER_LIBRARY_DIR = ROOT_DIR / "data" / "playwright-libs" / "usr" / "lib" / "x86_64-linux-gnu"
XUEQIU_BROWSER_COOKIE_SECONDS = 20 * 60
XUEQIU_BROWSER_LOCK_POLL_SECONDS = 0.25
XUEQIU_BROWSER_INTERACTIVE_WAIT_SECONDS = 180
XUEQIU_BROWSER_VERIFY_POLL_SECONDS = 1.0
XUEQIU_DEFAULT_SETTINGS: dict[str, Any] = {
    "request": {
        "userAgent": XUEQIU_USER_AGENT,
    },
    "auth": {
        "cookie": "",
        "cookieFile": "config/xueqiu_cookie.txt",
    },
    "browser": {
        "enabled": True,
        "headless": False,
        "channel": "chromium",
        "executable": "",
        "profileDir": "data/xueqiu-browser-profile",
        "libraryPath": "data/playwright-libs/usr/lib/x86_64-linux-gnu",
        "timeoutMs": 18000,
        "waitMs": 1000,
        "lockTimeoutMs": 23000,
        "interactiveWaitSeconds": XUEQIU_BROWSER_INTERACTIVE_WAIT_SECONDS,
        "verifyPollSeconds": XUEQIU_BROWSER_VERIFY_POLL_SECONDS,
    },
}

XUEQIU_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": None}
XUEQIU_SEARCH_CACHE: dict[str, dict[str, Any]] = {}
XUEQIU_BROWSER_COOKIE_CACHE: dict[str, Any] = {"expires_at": 0.0, "cookie": ""}
XUEQIU_BROWSER_FAILURE_CACHE: dict[str, Any] = {"expires_at": 0.0, "message": ""}
XUEQIU_LOCK = asyncio.Lock()
XUEQIU_SEARCH_LOCK = asyncio.Lock()
XUEQIU_AUTH_LOCK = threading.Lock()
XUEQIU_AUTH_SESSION: dict[str, Any] = {}


class XueqiuApiError(RuntimeError):
    pass


async def get_xueqiu(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    async with XUEQIU_LOCK:
        if not refresh and XUEQIU_CACHE["data"] and time.time() < XUEQIU_CACHE["expires_at"]:
            data = dict(XUEQIU_CACHE["data"])
            data["cached"] = True
            return data

    if not refresh:
        return build_xueqiu_snapshot()

    data = await asyncio.to_thread(fetch_xueqiu_sync)
    async with XUEQIU_LOCK:
        XUEQIU_CACHE["data"] = data
        XUEQIU_CACHE["expires_at"] = time.time() + XUEQIU_CACHE_SECONDS
    return data


async def import_xueqiu_influencer(query: str, name: str = "") -> dict[str, Any]:
    candidate = await asyncio.to_thread(resolve_influencer_sync, query, name)

    async with XUEQIU_LOCK:
        influencers = load_influencers_config()
        existing = find_influencer_match(influencers, candidate)
        if existing:
            imported = False
            existing_name = normalize_text(name)
            if existing_name and existing_name != existing.get("name"):
                existing["name"] = existing_name
                save_influencers_config(influencers)
                invalidate_xueqiu_cache()
            influencer = existing
        else:
            influencers.append(candidate)
            save_influencers_config(influencers)
            invalidate_xueqiu_cache()
            imported = True
            influencer = candidate

    data = await asyncio.to_thread(build_xueqiu_snapshot)
    async with XUEQIU_LOCK:
        XUEQIU_CACHE["data"] = data
        XUEQIU_CACHE["expires_at"] = time.time() + XUEQIU_CACHE_SECONDS
    return {**data, "imported": imported, "influencer": influencer_public_fields(influencer)}


async def search_xueqiu_users(query: str, limit: int = 6) -> dict[str, Any]:
    nickname = normalize_nickname_query(query)
    if not nickname:
        return {"query": "", "suggestions": [], "message": ""}

    safe_limit = max(1, min(int(limit or 6), 10))
    cache_key = f"{nickname.casefold()}:{safe_limit}"
    async with XUEQIU_SEARCH_LOCK:
        cached = XUEQIU_SEARCH_CACHE.get(cache_key)
        if cached and float(cached.get("expiresAt") or 0) > time.time():
            return dict(cached["data"])

    suggestions, errors = await asyncio.to_thread(search_user_profiles_sync, nickname, safe_limit)
    message = ""
    if not suggestions and errors:
        message = f"雪球搜索暂不可用：{normalize_error(errors[0])}"
    elif not suggestions:
        message = "没有找到匹配的雪球用户"
    data = {"query": nickname, "suggestions": suggestions, "message": message}

    async with XUEQIU_SEARCH_LOCK:
        XUEQIU_SEARCH_CACHE[cache_key] = {
            "expiresAt": time.time() + XUEQIU_SEARCH_CACHE_SECONDS,
            "data": data,
        }
        if len(XUEQIU_SEARCH_CACHE) > 50:
            expired_keys = [
                key for key, value in XUEQIU_SEARCH_CACHE.items()
                if float(value.get("expiresAt") or 0) <= time.time()
            ]
            for key in expired_keys or list(XUEQIU_SEARCH_CACHE)[:10]:
                XUEQIU_SEARCH_CACHE.pop(key, None)
    return data


async def remove_xueqiu_influencer(influencer_id: str) -> dict[str, Any]:
    async with XUEQIU_LOCK:
        influencers = load_influencers_config()
        next_influencers = [item for item in influencers if item.get("id") != influencer_id]
        if len(next_influencers) == len(influencers):
            raise ValueError("没有找到这个雪球大V。")
        save_influencers_config(next_influencers)
        invalidate_xueqiu_cache()

    data = await asyncio.to_thread(fetch_xueqiu_sync)
    async with XUEQIU_LOCK:
        XUEQIU_CACHE["data"] = data
        XUEQIU_CACHE["expires_at"] = time.time() + XUEQIU_CACHE_SECONDS
    return data


async def start_xueqiu_auth_qrcode(force: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(start_xueqiu_auth_qrcode_sync, force)


async def get_xueqiu_auth_status() -> dict[str, Any]:
    return await asyncio.to_thread(get_xueqiu_auth_status_sync)


async def close_xueqiu_auth_session() -> dict[str, Any]:
    return await asyncio.to_thread(close_xueqiu_auth_session_sync)


def start_xueqiu_auth_qrcode_sync(force: bool = False) -> dict[str, Any]:
    with XUEQIU_AUTH_LOCK:
        if not force:
            current = current_xueqiu_auth_session_response_locked()
            if current.get("status") == "pending":
                return current

        close_xueqiu_auth_session_locked()
        try:
            apply_xueqiu_browser_library_path()
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            profile_dir = xueqiu_config_path("browser.authProfileDir", XUEQIU_AUTH_PROFILE_DIR)
            profile_dir.mkdir(parents=True, exist_ok=True)
            timeout_ms = max(15000, xueqiu_config_int("browser.timeoutMs", 18000))
            launch_options: dict[str, Any] = {
                "headless": True,
                "channel": xueqiu_config_text("browser.channel", "chromium"),
                "viewport": {"width": 1280, "height": 900},
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "user_agent": xueqiu_config_text("request.userAgent", XUEQIU_USER_AGENT),
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            executable_path = xueqiu_config_text("browser.executable", "")
            if executable_path:
                launch_options["executable_path"] = executable_path

            context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
            context.set_default_timeout(timeout_ms)
            context.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "X-Requested-With": "XMLHttpRequest",
            })
            page = context.pages[0] if context.pages else context.new_page()
            qr_data_url = open_xueqiu_qr_login_page(page, timeout_ms)
            expires_at = time.time() + xueqiu_config_int("browser.interactiveWaitSeconds", XUEQIU_BROWSER_INTERACTIVE_WAIT_SECONDS)
            XUEQIU_AUTH_SESSION.update({
                "playwright": playwright,
                "context": context,
                "page": page,
                "qrDataUrl": qr_data_url,
                "startedAt": datetime.now(UTC).isoformat(),
                "expiresAt": expires_at,
                "message": "请用雪球 App 扫码登录。",
            })
            return current_xueqiu_auth_session_response_locked()
        except Exception as error:
            close_xueqiu_auth_session_locked()
            return {
                "status": "error",
                "message": f"无法生成雪球登录二维码：{summarize_browser_error(error)}",
            }


def open_xueqiu_qr_login_page(page: Any, timeout_ms: int) -> str:
    page.goto(XUEQIU_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(1500)
    controls = page.locator(".newLogin_modal__login__control_2mV").first.locator("a")
    if controls.count() >= 3:
        controls.nth(2).click()
    page.wait_for_timeout(2000)
    canvas = page.locator(".newLogin_modal__login__jj canvas").first
    canvas.wait_for(state="visible", timeout=timeout_ms)
    png = canvas.screenshot()
    return f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"


def get_xueqiu_auth_status_sync() -> dict[str, Any]:
    with XUEQIU_AUTH_LOCK:
        if not XUEQIU_AUTH_SESSION:
            return {"status": "idle", "message": "尚未开始雪球扫码登录。"}
        if time.time() >= float(XUEQIU_AUTH_SESSION.get("expiresAt") or 0):
            close_xueqiu_auth_session_locked()
            return {"status": "expired", "message": "雪球登录二维码已过期，请重新刷新二维码。"}

        context = XUEQIU_AUTH_SESSION.get("context")
        if not context:
            close_xueqiu_auth_session_locked()
            return {"status": "error", "message": "雪球登录会话已失效，请重新刷新二维码。"}

        if xueqiu_auth_probe_succeeded(context):
            cache_xueqiu_browser_cookies(context.cookies([XUEQIU_HOME_URL]))
            invalidate_xueqiu_cache()
            close_xueqiu_auth_session_locked()
            return {"status": "authenticated", "message": "雪球扫码登录已确认，正在重新抓取动态。"}

        return current_xueqiu_auth_session_response_locked()


def xueqiu_auth_probe_succeeded(context: Any) -> bool:
    influencers = load_influencers_config()
    if not influencers:
        return False
    user_id = normalize_text(influencers[0].get("userId") or influencers[0].get("id"))
    if not user_id:
        return False
    api_url = build_url(XUEQIU_TIMELINE_APIS[0], {"user_id": user_id, "page": "1", "count": "1"})
    try:
        fetch_xueqiu_json_with_browser_request_once(context, api_url, xueqiu_config_int("browser.timeoutMs", 18000))
        return True
    except Exception:
        return False


def current_xueqiu_auth_session_response_locked() -> dict[str, Any]:
    qr_data_url = normalize_text(XUEQIU_AUTH_SESSION.get("qrDataUrl"))
    if not qr_data_url:
        return {"status": "idle", "message": "尚未开始雪球扫码登录。"}
    return {
        "status": "pending",
        "qrDataUrl": qr_data_url,
        "startedAt": XUEQIU_AUTH_SESSION.get("startedAt", ""),
        "expiresAt": datetime.fromtimestamp(float(XUEQIU_AUTH_SESSION.get("expiresAt") or 0), UTC).isoformat(),
        "message": normalize_text(XUEQIU_AUTH_SESSION.get("message")) or "请用雪球 App 扫码登录。",
    }


def close_xueqiu_auth_session_sync() -> dict[str, Any]:
    with XUEQIU_AUTH_LOCK:
        close_xueqiu_auth_session_locked()
    return {"status": "closed"}


def close_xueqiu_auth_session_locked() -> None:
    context = XUEQIU_AUTH_SESSION.get("context")
    playwright = XUEQIU_AUTH_SESSION.get("playwright")
    try:
        if context:
            context.close()
    except Exception:
        pass
    try:
        if playwright:
            playwright.stop()
    except Exception:
        pass
    XUEQIU_AUTH_SESSION.clear()


def build_xueqiu_snapshot() -> dict[str, Any]:
    influencers = [influencer_public_fields(item) for item in load_influencers_config()]
    today = datetime.now(CHINA_TZ).date()
    window_start = xueqiu_window_start(today)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "cached": False,
        "source": "雪球配置",
        "today": today.isoformat(),
        "todayLabel": f"{today.month}月{today.day}日",
        "rangeStart": window_start.isoformat(),
        "rangeEnd": today.isoformat(),
        "rangeLabel": xueqiu_range_label(window_start, today),
        "influencers": influencers,
        "activities": [],
        "summary": summarize_activities(influencers, []),
        "errors": [],
        "hasData": True,
        "needsRefresh": True,
    }


def fetch_xueqiu_sync() -> dict[str, Any]:
    influencers = load_influencers_config()
    today = datetime.now(CHINA_TZ).date()
    window_start = xueqiu_window_start(today)
    generated_at = datetime.now(UTC).isoformat()
    errors: list[str] = []
    auth_errors: list[str] = []
    activities: list[dict[str, Any]] = []
    influencer_rows: list[dict[str, Any]] = []

    for influencer in influencers:
        row = influencer_public_fields(influencer)
        try:
            fetched = fetch_influencer_recent_sync(influencer, window_start, today)
            row["activityCount"] = len(fetched)
            row["lastFetchedAt"] = generated_at
            activities.extend(fetched)
        except Exception as error:
            message = normalize_error(error)
            row["activityCount"] = 0
            row["activityError"] = message
            errors.append(f"{row['name']}：{message}")
            if is_xueqiu_auth_error(message):
                auth_errors.append(message)
        influencer_rows.append(row)

    activities = sorted(dedupe_activities(activities), key=lambda item: item.get("publishedAt") or "", reverse=True)
    summary = summarize_activities(influencer_rows, activities)
    auth_required = bool(auth_errors and not activities)

    return {
        "generatedAt": generated_at,
        "cached": False,
        "source": "雪球公开主页/API",
        "today": today.isoformat(),
        "todayLabel": f"{today.month}月{today.day}日",
        "rangeStart": window_start.isoformat(),
        "rangeEnd": today.isoformat(),
        "rangeLabel": xueqiu_range_label(window_start, today),
        "influencers": influencer_rows,
        "activities": activities,
        "summary": summary,
        "errors": errors,
        "authRequired": auth_required,
        "loginRequired": auth_required,
        "loginMessage": build_xueqiu_login_message(auth_errors[0] if auth_errors else ""),
        "hasData": not auth_required,
    }


def is_xueqiu_auth_error(message: Any) -> bool:
    text = normalize_text(message).lower()
    return any(
        token in text
        for token in (
            "login",
            "auth.cookie",
            "auth.cookiefile",
            "browser.headless",
            "captcha",
            "challenge",
            "waf",
            "风控",
            "验证",
            "滑块",
            "登录",
            "é£ŽæŽ§",
            "éªŒè¯",
            "æ»‘å—",
            "ç™»å½•",
        )
    )


def build_xueqiu_login_message(error: str = "") -> str:
    base = "雪球需要登录或完成验证，请在页面弹出的二维码中用雪球 App 扫码登录。"
    detail = normalize_text(error)
    return f"{base} 最后错误：{detail}" if detail else base


def xueqiu_window_start(today: Any) -> Any:
    return today - timedelta(days=max(1, XUEQIU_LOOKBACK_DAYS) - 1)


def xueqiu_range_label(start: Any, end: Any) -> str:
    if start.month == end.month:
        return f"{start.month}月{start.day}日-{end.day}日"
    return f"{start.month}月{start.day}日-{end.month}月{end.day}日"


def fetch_influencer_recent_sync(influencer: dict[str, Any], start_date: Any, end_date: Any) -> list[dict[str, Any]]:
    session = create_xueqiu_session()
    rows: list[dict[str, Any]] = []
    required_errors: list[str] = []

    for url in XUEQIU_TIMELINE_APIS:
        try:
            rows.extend(fetch_activity_rows_for_window(session, url, influencer, start_date, XUEQIU_FETCH_LIMIT, XUEQIU_FETCH_MAX_PAGES))
            if rows:
                break
        except Exception as error:
            required_errors.append(str(error))

    comment_errors: list[str] = []
    for url in XUEQIU_COMMENT_TIMELINE_APIS:
        try:
            comment_rows = fetch_activity_rows_for_window(session, url, influencer, start_date, XUEQIU_FETCH_LIMIT, XUEQIU_FETCH_MAX_PAGES)
            rows.extend(comment_rows)
            if comment_rows:
                break
        except Exception as error:
            comment_errors.append(str(error))

    if not rows and required_errors:
        raise XueqiuApiError(required_errors[0])

    activities = []
    for row in rows:
        activity = parse_activity_row(row, influencer)
        if activity and is_in_date_window(activity.get("publishedAt"), start_date, end_date):
            activities.append(activity)

    if comment_errors and activities:
        for activity in activities[:1]:
            activity["note"] = "评论/回复接口可能未完全返回。"
            break
    return activities


def fetch_activity_rows_for_window(
    session: requests.Session,
    url: str,
    influencer: dict[str, Any],
    start_date: Any,
    limit: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max(1, max_pages) + 1):
        try:
            page_rows = fetch_activity_rows(session, url, influencer, limit, page)
        except Exception:
            if rows:
                break
            raise
        if not page_rows:
            break
        if page > 1 and rows_are_before_window(page_rows, influencer, start_date):
            break
        rows.extend(page_rows)
        if len(page_rows) < limit:
            break
    return rows


def rows_are_before_window(rows: list[dict[str, Any]], influencer: dict[str, Any], start_date: Any) -> bool:
    dates = []
    for row in rows:
        activity = parse_activity_row(row, influencer)
        activity_date = xueqiu_activity_date(activity.get("publishedAt") if activity else "")
        if activity_date:
            dates.append(activity_date)
    return bool(dates) and all(activity_date < start_date for activity_date in dates)


def fetch_activity_rows(session: requests.Session, url: str, influencer: dict[str, Any], limit: int, page: int = 1) -> list[dict[str, Any]]:
    payload = fetch_xueqiu_json(
        session,
        url,
        params={
            "user_id": influencer.get("userId"),
            "page": str(page),
            "count": str(limit),
        },
        timeout=12,
    )
    return extract_rows(payload)


def resolve_influencer_sync(query: str, name: str = "") -> dict[str, Any]:
    raw = normalize_text(query)
    display_name = normalize_text(name)
    if not raw:
        raise ValueError("请输入雪球大V主页链接、用户ID或昵称。")

    user_id = extract_user_id(raw)
    if user_id:
        profile = fetch_user_profile_sync(user_id)
        resolved_name = display_name or profile.get("name") or profile.get("screenName") or f"雪球用户 {user_id}"
        return make_influencer(user_id, resolved_name, profile)

    profile = search_user_profile_sync(raw)
    user_id = normalize_text(profile.get("userId") or profile.get("id"))
    if not user_id:
        raise ValueError("没有识别到雪球用户ID，请粘贴大V主页链接。")
    resolved_name = display_name or profile.get("name") or profile.get("screenName") or raw
    return make_influencer(user_id, resolved_name, profile)


def fetch_user_profile_sync(user_id: str) -> dict[str, Any]:
    session = create_xueqiu_session()
    errors = []
    for url in XUEQIU_USER_SHOW_APIS:
        for params in ({"id": user_id}, {"user_id": user_id}):
            try:
                payload = fetch_xueqiu_json(session, url, params=params, timeout=10)
                profile = normalize_user_profile(payload)
                if profile:
                    return profile
            except Exception as error:
                errors.append(str(error))
    return {"userId": user_id}


def search_user_profile_sync(query: str) -> dict[str, Any]:
    suggestions, errors = search_user_profiles_sync(query, 6)
    if suggestions:
        return suggestions[0]

    hint = "没有找到匹配的雪球用户，请换一个昵称、粘贴主页链接或数字用户ID。"
    if errors:
        raise ValueError(f"{hint}（{normalize_error(errors[0])}）")
    raise ValueError(hint)


def search_user_profiles_sync(query: str, limit: int = 6) -> tuple[list[dict[str, Any]], list[str]]:
    session = create_xueqiu_session()
    nickname = normalize_nickname_query(query)
    safe_limit = max(1, min(int(limit or 6), 10))
    imported_by_id = {item.get("userId"): item for item in load_influencers_config()}
    suggestions: list[dict[str, Any]] = []
    seen_user_ids: set[str] = set()
    errors: list[str] = []

    def add_profile(profile: dict[str, Any]) -> None:
        user_id = normalize_text(profile.get("userId") or profile.get("id"))
        if not user_id or user_id in seen_user_ids or len(suggestions) >= safe_limit:
            return
        candidate = influencer_public_fields(
            make_influencer(
                user_id,
                profile.get("name") or profile.get("screenName") or f"雪球用户 {user_id}",
                profile,
            )
        )
        candidate["imported"] = user_id in imported_by_id
        suggestions.append(candidate)
        seen_user_ids.add(user_id)

    user_id = extract_user_id(query)
    if user_id:
        add_profile(fetch_user_profile_sync(user_id))
        return suggestions, errors

    normalized_query = nickname.casefold()
    local_matches = [
        item for item in imported_by_id.values()
        if normalized_query in normalize_text(item.get("name")).casefold()
        or normalized_query in normalize_text(item.get("userId")).casefold()
    ]
    local_matches.sort(
        key=lambda item: (
            normalize_text(item.get("name")).casefold() != normalized_query,
            not normalize_text(item.get("name")).casefold().startswith(normalized_query),
            normalize_text(item.get("name")).casefold(),
        )
    )
    for item in local_matches:
        add_profile(item)

    profile = fetch_user_profile_by_nickname_url_sync(session, nickname)
    if profile.get("userId"):
        add_profile(profile)

    for url in XUEQIU_USER_SEARCH_APIS:
        try:
            payload = fetch_xueqiu_json(
                session,
                url,
                params={"q": nickname, "page": "1", "count": str(safe_limit)},
                timeout=10,
            )
            for row in extract_rows(payload):
                profile = normalize_user_profile(row)
                if profile.get("userId"):
                    add_profile(profile)
            if len(suggestions) >= safe_limit:
                break
        except Exception as error:
            errors.append(str(error))
    return suggestions, errors


def fetch_user_profile_by_nickname_url_sync(session: requests.Session, nickname: str) -> dict[str, Any]:
    if not nickname:
        return {}
    try:
        response = session.get(f"{XUEQIU_HOME_URL}n/{quote(nickname, safe='')}", allow_redirects=False, timeout=10)
    except Exception:
        return {}

    location = response.headers.get("Location") or response.headers.get("location") or ""
    user_id = extract_user_id(location)
    if not user_id:
        return {}
    return {
        "userId": user_id,
        "name": nickname,
        "screenName": nickname,
        "profileUrl": f"https://xueqiu.com/u/{user_id}",
    }


def normalize_nickname_query(value: Any) -> str:
    text = normalize_text(value)
    match = re.search(r"xueqiu\.com/n/([^/?#]+)", text, re.IGNORECASE)
    if match:
        text = unquote(match.group(1))
    return text.lstrip("@＠").strip()


def load_xueqiu_settings() -> dict[str, Any]:
    settings = deep_merge_dicts(XUEQIU_DEFAULT_SETTINGS, {})
    try:
        payload = json.loads(XUEQIU_SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except Exception:
        return settings
    if isinstance(payload, dict):
        settings = deep_merge_dicts(settings, payload)
    return settings


def xueqiu_setting(path: str, default: Any = None) -> Any:
    value: Any = load_xueqiu_settings()
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def xueqiu_config_text(path: str, default: str = "") -> str:
    text = normalize_text(xueqiu_setting(path, default))
    return text or default


def xueqiu_config_bool(path: str, default: bool) -> bool:
    value = xueqiu_setting(path, default)
    if isinstance(value, bool):
        return value
    text = normalize_text(value).lower()
    if not text:
        return default
    return text not in {"0", "false", "off", "no"}


def xueqiu_config_int(path: str, default: int) -> int:
    try:
        return int(normalize_text(xueqiu_setting(path, default)) or default)
    except (TypeError, ValueError):
        return default


def xueqiu_config_float(path: str, default: float) -> float:
    try:
        return float(normalize_text(xueqiu_setting(path, default)) or default)
    except (TypeError, ValueError):
        return default


def xueqiu_config_path(path: str, default: Path) -> Path:
    configured = normalize_text(xueqiu_setting(path, ""))
    if not configured:
        return default
    candidate = Path(configured).expanduser()
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


def deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def create_xueqiu_session() -> requests.Session:
    session = requests.Session()
    headers = {
        "User-Agent": xueqiu_config_text("request.userAgent", XUEQIU_USER_AGENT),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://xueqiu.com",
        "Referer": XUEQIU_HOME_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    cookie = get_xueqiu_cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)
    try:
        session.get(XUEQIU_TOKEN_WARMUP_URL, allow_redirects=False, timeout=8)
    except Exception:
        pass
    warmup_cookie = requests_cookies_to_header(session.cookies)
    if warmup_cookie:
        session.headers["Cookie"] = merge_cookie_headers(session.headers.get("Cookie", ""), warmup_cookie)
    return session


def fetch_xueqiu_json(session: requests.Session, url: str, params: dict[str, Any] | None = None, timeout: int = 12) -> dict[str, Any]:
    try:
        response = session.get(url, params=params, timeout=timeout)
        return response_json_or_error(response, url)
    except XueqiuApiError as error:
        if is_retryable_xueqiu_error(error) and not xueqiu_browser_headless():
            raise XueqiuApiError(f"{normalize_error(error)}；需要扫码登录，请在页面弹出的雪球二维码登录。") from error
        if not should_retry_with_browser(error):
            browser_failure = get_recent_xueqiu_browser_failure()
            if browser_failure and is_retryable_xueqiu_error(error):
                raise XueqiuApiError(f"{normalize_error(error)}；浏览器兜底暂不可用：{browser_failure}") from error
            raise
        try:
            payload = fetch_xueqiu_json_with_browser_sync(url, params=params, timeout=timeout)
            apply_xueqiu_cookie_header(session)
            return payload
        except Exception as browser_error:
            message = summarize_browser_error(browser_error)
            remember_xueqiu_browser_failure(message)
            raise XueqiuApiError(f"{normalize_error(error)}；浏览器兜底失败：{message}") from browser_error


def response_json_or_error(response: requests.Response, url: str) -> dict[str, Any]:
    response.encoding = "utf-8"
    return parse_xueqiu_json_response(response.text, response.status_code, url)


def parse_xueqiu_json_response(text: str, status_code: int, url: str) -> dict[str, Any]:
    text = (text or "").strip()
    if status_code >= 400:
        message = extract_error_message(text)
        raise XueqiuApiError(message or f"雪球接口返回 {status_code}")
    if is_xueqiu_risk_control_page(text):
        raise XueqiuApiError(xueqiu_risk_control_message(text))
    try:
        payload = json.loads(text)
    except Exception as error:
        raise XueqiuApiError(f"雪球返回内容不是 JSON：{error}") from error
    if not isinstance(payload, dict):
        raise XueqiuApiError("雪球返回结构异常。")
    if payload.get("error_code") or payload.get("error_description"):
        raise XueqiuApiError(normalize_text(payload.get("error_description")) or f"雪球错误 {payload.get('error_code')}")
    if payload.get("success") is False:
        raise XueqiuApiError(normalize_text(payload.get("message")) or f"雪球错误 {payload.get('code') or ''}".strip())
    return payload


def fetch_xueqiu_json_with_browser_sync(url: str, params: dict[str, Any] | None = None, timeout: int = 12) -> dict[str, Any]:
    if not xueqiu_browser_enabled():
        raise XueqiuApiError("浏览器兜底已关闭，请设置 config/xueqiu_settings.json: browser.enabled=true。")
    apply_xueqiu_browser_library_path()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise XueqiuApiError(
            "浏览器模式需要安装 Playwright：pip install -r requirements.txt && python -m playwright install chromium"
        ) from error

    api_url = build_url(url, params)
    timeout_ms = max(timeout * 1000, xueqiu_config_int("browser.timeoutMs", 18000))
    wait_ms = xueqiu_config_int("browser.waitMs", 1000)
    profile_dir = xueqiu_config_path("browser.profileDir", XUEQIU_BROWSER_PROFILE_DIR)
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        lock_timeout_ms = max(timeout_ms, xueqiu_config_int("browser.lockTimeoutMs", timeout_ms + 5000))
        with xueqiu_browser_profile_lock(profile_dir, lock_timeout_ms):
            cleanup_stale_chromium_profile_locks(profile_dir)
            wait_for_chromium_profile_release(profile_dir, lock_timeout_ms)
            with sync_playwright() as playwright:
                return fetch_xueqiu_json_with_browser_context(playwright, profile_dir, api_url, timeout_ms, wait_ms)
    except XueqiuApiError:
        raise
    except Exception as error:
        raise XueqiuApiError(f"浏览器抓取失败：{summarize_browser_error(error)}") from error


def fetch_xueqiu_json_with_browser_context(playwright: Any, profile_dir: Path, api_url: str, timeout_ms: int, wait_ms: int) -> dict[str, Any]:
    try:
        headless = xueqiu_browser_headless()
        launch_options: dict[str, Any] = {
            "headless": headless,
            "channel": xueqiu_config_text("browser.channel", "chromium"),
            "viewport": {"width": 1280, "height": 900},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "user_agent": xueqiu_config_text("request.userAgent", XUEQIU_USER_AGENT),
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        executable_path = xueqiu_config_text("browser.executable", "")
        if executable_path:
            launch_options["executable_path"] = executable_path

        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
        try:
            context.set_default_timeout(timeout_ms)
            context.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "X-Requested-With": "XMLHttpRequest",
            })
            add_cookie_header_to_browser_context(context, get_manual_xueqiu_cookie_header())
            if headless:
                payload = fetch_xueqiu_json_with_browser_request_once(context, api_url, timeout_ms)
            else:
                page = context.pages[0] if context.pages else context.new_page()
                warm_xueqiu_browser_page(page, timeout_ms, wait_ms)
                payload = fetch_xueqiu_json_with_browser_page(page, api_url, timeout_ms, wait_ms)
            cache_xueqiu_browser_cookies(context.cookies([XUEQIU_HOME_URL]))
            return payload
        finally:
            context.close()
    except XueqiuApiError:
        raise
    except Exception as error:
        raise XueqiuApiError(f"浏览器抓取失败：{summarize_browser_error(error)}") from error


def fetch_xueqiu_json_with_browser_request_once(context: Any, api_url: str, timeout_ms: int) -> dict[str, Any]:
    try:
        response = context.request.get(
            api_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": XUEQIU_HOME_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout_ms,
        )
        return parse_xueqiu_json_response(response.text(), response.status, response.url)
    except XueqiuApiError as error:
        if is_xueqiu_browser_interaction_error(error, ""):
            raise XueqiuApiError(
                f"{normalize_error(error)}；雪球需要可交互浏览器完成登录或滑块验证。"
                "请用 config/xueqiu_settings.json: browser.headless=false 启动服务后刷新，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
            ) from error
        raise


def warm_xueqiu_browser_page(page: Any, timeout_ms: int, wait_ms: int) -> None:
    try:
        page.goto(XUEQIU_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
    except Exception:
        return

    page_text = read_browser_page_text(page)
    if page_text and is_xueqiu_risk_control_page(page_text):
        wait_for_xueqiu_browser_json(page, XUEQIU_HOME_URL, timeout_ms, XueqiuApiError(xueqiu_risk_control_message(page_text)))


def fetch_xueqiu_json_with_browser_page(page: Any, api_url: str, timeout_ms: int, wait_ms: int) -> dict[str, Any]:
    try:
        return fetch_xueqiu_json_with_browser_fetch_once(page, api_url, timeout_ms)
    except XueqiuApiError as fetch_error:
        if not is_xueqiu_browser_interaction_error(fetch_error, ""):
            raise
        return fetch_xueqiu_json_with_browser_navigation(page, api_url, timeout_ms, wait_ms, fetch_error)


def fetch_xueqiu_json_with_browser_fetch_once(page: Any, api_url: str, timeout_ms: int) -> dict[str, Any]:
    result = page.evaluate(
        """
        async ({ url, timeout }) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), timeout);
          try {
            const response = await fetch(url, {
              credentials: "include",
              signal: controller.signal,
              headers: {
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest"
              }
            });
            return {
              status: response.status,
              text: await response.text(),
              url: response.url,
              contentType: response.headers.get("content-type") || ""
            };
          } catch (error) {
            return {
              status: 0,
              text: `${error && error.name ? error.name : "Error"}: ${error && error.message ? error.message : error}`,
              url,
              contentType: ""
            };
          } finally {
            clearTimeout(timer);
          }
        }
        """,
        {"url": api_url, "timeout": timeout_ms},
    )
    if int(result.get("status") or 0) == 0:
        raise XueqiuApiError(f"浏览器页面请求失败：{normalize_text(result.get('text'))}")
    return parse_xueqiu_json_response(
        str(result.get("text") or ""),
        int(result.get("status") or 0),
        normalize_text(result.get("url")) or api_url,
    )


def fetch_xueqiu_json_with_browser_navigation(page: Any, api_url: str, timeout_ms: int, wait_ms: int, previous_error: Exception) -> dict[str, Any]:
    try:
        response = page.goto(api_url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
    except Exception as error:
        raise XueqiuApiError(f"{normalize_error(previous_error)}；浏览器打开验证页失败：{summarize_browser_error(error)}") from error

    status_code = int(response.status) if response else 200
    page_text = read_browser_page_text(page)
    try:
        return parse_xueqiu_json_response(page_text, status_code, page.url or api_url)
    except XueqiuApiError as error:
        if not is_xueqiu_browser_interaction_error(error, page_text):
            raise
        return wait_for_xueqiu_browser_json(page, api_url, timeout_ms, error)


def wait_for_xueqiu_browser_json(page: Any, api_url: str, timeout_ms: int, error: Exception) -> dict[str, Any]:
    if xueqiu_browser_headless():
        raise XueqiuApiError(
            f"{normalize_error(error)}；雪球需要可交互浏览器完成登录或滑块验证。"
            "请用 config/xueqiu_settings.json: browser.headless=false 启动服务后刷新，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
        ) from error

    wait_seconds = xueqiu_config_int("browser.interactiveWaitSeconds", XUEQIU_BROWSER_INTERACTIVE_WAIT_SECONDS)
    if wait_seconds <= 0:
        raise XueqiuApiError(
            f"{normalize_error(error)}；已关闭交互等待，请调大 browser.interactiveWaitSeconds，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
        ) from error

    try:
        page.bring_to_front()
    except Exception:
        pass

    deadline = time.monotonic() + wait_seconds
    last_error = normalize_error(error)
    poll_seconds = xueqiu_config_float("browser.verifyPollSeconds", XUEQIU_BROWSER_VERIFY_POLL_SECONDS)
    poll_ms = max(250, int(poll_seconds * 1000))
    while time.monotonic() < deadline:
        try:
            page.wait_for_timeout(poll_ms)
            page_text = read_browser_page_text(page)
            try:
                return parse_xueqiu_json_response(page_text, 200, page.url or api_url)
            except XueqiuApiError as page_error:
                last_error = normalize_error(page_error)
                if page_text and not is_xueqiu_risk_control_page(page_text):
                    return fetch_xueqiu_json_with_browser_fetch_once(page, api_url, timeout_ms)
                if not is_xueqiu_browser_interaction_error(page_error, page_text):
                    return fetch_xueqiu_json_with_browser_fetch_once(page, api_url, timeout_ms)
        except XueqiuApiError as retry_error:
            last_error = normalize_error(retry_error)
        except Exception as retry_error:
            last_error = summarize_browser_error(retry_error)

    raise XueqiuApiError(
        f"雪球需要登录或滑块验证；已打开浏览器等待 {wait_seconds} 秒但仍未通过。"
        f"请在弹出的浏览器完成验证后再次刷新，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。最后错误：{last_error}"
    ) from error


def read_browser_page_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=2000) or "").strip()
    except Exception:
        try:
            return str(page.content() or "").strip()
        except Exception:
            return ""


def is_xueqiu_browser_interaction_error(error: Exception, text: str) -> bool:
    if text and is_xueqiu_risk_control_page(text):
        return True
    message = normalize_error(error)
    return is_retryable_xueqiu_error(error) or any(
        token in message
        for token in ("登录", "验证", "滑块", "风控", "risk", "captcha", "challenge", "WAF")
    )


@contextmanager
def xueqiu_browser_profile_lock(profile_dir: Path, timeout_ms: int):
    lock_path = profile_dir / ".codex-xueqiu-browser.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout_ms, 1000) / 1000
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        if not acquire_file_lock(handle, deadline):
            raise XueqiuApiError("雪球浏览器 profile 正在被另一个刷新任务使用，请稍后重试。")
        yield
    finally:
        try:
            release_file_lock(handle)
        finally:
            handle.close()


def acquire_file_lock(handle: Any, deadline: float) -> bool:
    try:
        import fcntl

        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(XUEQIU_BROWSER_LOCK_POLL_SECONDS)
    except ImportError:
        return True


def release_file_lock(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except ImportError:
        return


def wait_for_chromium_profile_release(profile_dir: Path, timeout_ms: int) -> None:
    deadline = time.monotonic() + max(timeout_ms, 1000) / 1000
    while chromium_profile_owner_alive(profile_dir):
        if time.monotonic() >= deadline:
            raise XueqiuApiError("雪球浏览器 profile 正在被另一个 Chromium 进程占用，请关闭残留浏览器进程或稍后重试。")
        time.sleep(XUEQIU_BROWSER_LOCK_POLL_SECONDS)
        cleanup_stale_chromium_profile_locks(profile_dir)


def cleanup_stale_chromium_profile_locks(profile_dir: Path) -> None:
    owner = chromium_profile_owner_pid(profile_dir)
    if owner and is_process_alive(owner):
        return
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = profile_dir / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass


def chromium_profile_owner_alive(profile_dir: Path) -> bool:
    owner = chromium_profile_owner_pid(profile_dir)
    return bool(owner and is_process_alive(owner))


def chromium_profile_owner_pid(profile_dir: Path) -> int | None:
    lock_path = profile_dir / "SingletonLock"
    try:
        target = os.readlink(lock_path)
    except OSError:
        return None
    match = re.search(r"-(\d+)$", target)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def summarize_browser_error(error: Any) -> str:
    message = normalize_error(error)
    if message.startswith("浏览器抓取失败："):
        message = message.split("：", 1)[1]
    if "需要可交互浏览器" in message or "已打开浏览器等待" in message:
        return "雪球需要可交互浏览器登录/滑块验证；请用 config/xueqiu_settings.json: browser.headless=false 启动服务后刷新，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
    if "libnspr4.so" in message or "libnss3.so" in message or "libasound.so.2" in message:
        return "Chromium 缺少运行库；请运行 Playwright 依赖安装，或配置 browser.libraryPath。"
    if "ProcessSingleton" in message or "SingletonLock" in message:
        return "浏览器 profile 被其他 Chromium 进程占用，请稍后重试。"
    if "BROWSER_FETCH_ERROR:AbortError" in message or "Timeout" in message:
        return "浏览器 API 请求超时；通常需要可用登录态、手动滑动验证一次，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
    if "ERR_CONNECTION_CLOSED" in message:
        return "雪球主动断开了浏览器连接，通常需要可用登录态；请配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile 或用非 headless 浏览器登录一次。"
    if "Executable doesn't exist" in message or "executable doesn't exist" in message or "does not support chromium" in message:
        return "没有找到 Playwright Chromium，请运行 python -m playwright install chromium。"
    if len(message) > 220:
        return f"{message[:220]}..."
    return message

def build_url(url: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def should_retry_with_browser(error: Exception) -> bool:
    if not xueqiu_browser_enabled():
        return False
    if xueqiu_browser_headless() and get_recent_xueqiu_browser_failure():
        return False
    return is_retryable_xueqiu_error(error)


def is_retryable_xueqiu_error(error: Exception) -> bool:
    message = normalize_error(error)
    return any(token in message for token in ("风控", "HTML", "不是 JSON", "接口返回", "参数/登录态", "滑动验证"))


def is_xueqiu_risk_control_page(text: str) -> bool:
    if not text:
        return True
    head = text[:5000]
    return text.startswith("<") or "aliyun_waf" in head or "_waf_" in head or "滑动验证" in head or "访问验证" in head


def xueqiu_risk_control_message(text: str) -> str:
    if "滑动验证" in text or "访问验证" in text:
        return "雪球返回滑动验证页面。请设置 config/xueqiu_settings.json: browser.headless=false 手动验证一次，或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"
    return "雪球返回风控页面，稍后重试或配置 config/xueqiu_settings.json: auth.cookie or auth.cookieFile。"


def remember_xueqiu_browser_failure(message: str, seconds: int = 60) -> None:
    XUEQIU_BROWSER_FAILURE_CACHE["message"] = normalize_text(message)
    XUEQIU_BROWSER_FAILURE_CACHE["expires_at"] = time.time() + seconds


def get_recent_xueqiu_browser_failure() -> str:
    if time.time() >= float(XUEQIU_BROWSER_FAILURE_CACHE.get("expires_at") or 0):
        return ""
    return normalize_text(XUEQIU_BROWSER_FAILURE_CACHE.get("message"))


def xueqiu_browser_enabled() -> bool:
    return xueqiu_config_bool("browser.enabled", True)


def xueqiu_browser_headless() -> bool:
    return xueqiu_config_bool("browser.headless", True)


def apply_xueqiu_browser_library_path() -> None:
    lib_dir = xueqiu_config_path("browser.libraryPath", XUEQIU_BROWSER_LIBRARY_DIR)
    if not lib_dir.exists():
        return
    current_paths = [path for path in normalize_text(os.getenv("LD_LIBRARY_PATH")).split(":") if path]
    lib_path = str(lib_dir)
    if lib_path in current_paths:
        return
    os.environ["LD_LIBRARY_PATH"] = ":".join([lib_path, *current_paths])


def get_xueqiu_cookie_header() -> str:
    return merge_cookie_headers(get_manual_xueqiu_cookie_header(), get_cached_xueqiu_browser_cookie_header())


def get_manual_xueqiu_cookie_header() -> str:
    cookie = xueqiu_config_text("auth.cookie", "")
    if cookie:
        return cookie
    cookie_file = xueqiu_config_path("auth.cookieFile", XUEQIU_COOKIE_FILE)
    try:
        return normalize_text(cookie_file.read_text(encoding="utf-8"))
    except OSError:
        return ""


def get_cached_xueqiu_browser_cookie_header() -> str:
    if time.time() >= float(XUEQIU_BROWSER_COOKIE_CACHE.get("expires_at") or 0):
        return ""
    return normalize_text(XUEQIU_BROWSER_COOKIE_CACHE.get("cookie"))


def apply_xueqiu_cookie_header(session: requests.Session) -> None:
    cookie = get_xueqiu_cookie_header()
    if cookie:
        session.headers["Cookie"] = cookie


def add_cookie_header_to_browser_context(context: Any, cookie_header: str) -> None:
    cookies = parse_cookie_header_for_browser(cookie_header)
    if cookies:
        context.add_cookies(cookies)


def parse_cookie_header_for_browser(cookie_header: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        name, value = chunk.strip().split("=", 1)
        if not name:
            continue
        cookies.append({"name": name, "value": value, "domain": ".xueqiu.com", "path": "/"})
    return cookies


def merge_cookie_headers(*headers: str) -> str:
    cookies: dict[str, str] = {}
    for header in headers:
        for chunk in normalize_text(header).split(";"):
            if "=" not in chunk:
                continue
            name, value = chunk.strip().split("=", 1)
            if name:
                cookies[name] = value
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def requests_cookies_to_header(cookie_jar: Any) -> str:
    parts = []
    for cookie in cookie_jar:
        name = normalize_text(getattr(cookie, "name", ""))
        value = normalize_text(getattr(cookie, "value", ""))
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def cache_xueqiu_browser_cookies(cookies: list[dict[str, Any]]) -> None:
    cookie_header = browser_cookies_to_header(cookies)
    if not cookie_header:
        return
    XUEQIU_BROWSER_COOKIE_CACHE["cookie"] = cookie_header
    XUEQIU_BROWSER_COOKIE_CACHE["expires_at"] = time.time() + XUEQIU_BROWSER_COOKIE_SECONDS


def browser_cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    now = time.time()
    parts = []
    for cookie in cookies:
        domain = normalize_text(cookie.get("domain")).lstrip(".")
        expires = safe_number(cookie.get("expires"))
        if domain and not domain.endswith("xueqiu.com"):
            continue
        if expires and expires > 0 and expires < now:
            continue
        name = normalize_text(cookie.get("name"))
        value = normalize_text(cookie.get("value"))
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def extract_error_message(text: str) -> str:
    if not text:
        return ""
    try:
        payload = json.loads(text)
        return normalize_text(payload.get("error_description") or payload.get("message") or payload.get("error"))
    except Exception:
        return normalize_text(strip_html(text))[:160]


def load_influencers_config() -> list[dict[str, Any]]:
    if not XUEQIU_CONFIG_PATH.exists():
        return []
    try:
        payload = json.loads(XUEQIU_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    influencers = payload.get("influencers") if isinstance(payload, dict) else []
    result = []
    for raw in influencers or []:
        user_id = normalize_text(raw.get("userId") or raw.get("user_id") or raw.get("id"))
        if not user_id:
            continue
        if user_id.startswith("user-"):
            user_id = user_id[5:]
        result.append(make_influencer(user_id, raw.get("name") or raw.get("screenName") or f"雪球用户 {user_id}", raw))
    return result


def save_influencers_config(influencers: list[dict[str, Any]]) -> None:
    XUEQIU_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = [make_influencer(item.get("userId"), item.get("name"), item) for item in influencers if item.get("userId")]
    XUEQIU_CONFIG_PATH.write_text(json.dumps({"influencers": normalized}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def invalidate_xueqiu_cache() -> None:
    XUEQIU_CACHE["data"] = None
    XUEQIU_CACHE["expires_at"] = 0.0
    XUEQIU_SEARCH_CACHE.clear()


def find_influencer_match(influencers: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    for influencer in influencers:
        if influencer.get("id") == candidate.get("id") or influencer.get("userId") == candidate.get("userId"):
            return influencer
    return None


def make_influencer(user_id: Any, name: Any, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    user_id_text = normalize_text(user_id)
    profile = profile or {}
    screen_name = normalize_text(name) or normalize_text(profile.get("screenName") or profile.get("screen_name")) or f"雪球用户 {user_id_text}"
    verified = bool(profile.get("verified") or profile.get("verified_type"))
    description = normalize_text(profile.get("description") or profile.get("desc") or profile.get("remark"))
    followers = safe_number(profile.get("followersCount") or profile.get("followers_count") or profile.get("followers"))
    avatar_url = normalize_xueqiu_avatar_url(
        profile.get("avatarUrl")
        or profile.get("profileImageUrl")
        or profile.get("profile_image_url")
    )
    return {
        "id": f"user-{user_id_text}",
        "userId": user_id_text,
        "name": screen_name,
        "profileUrl": f"https://xueqiu.com/u/{user_id_text}",
        "verified": verified,
        "description": description,
        "followersCount": followers,
        "avatarUrl": avatar_url,
    }


def influencer_public_fields(influencer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": influencer.get("id") or f"user-{influencer.get('userId')}",
        "userId": influencer.get("userId") or "",
        "name": influencer.get("name") or influencer.get("screenName") or influencer.get("userId") or "",
        "profileUrl": influencer.get("profileUrl") or f"https://xueqiu.com/u/{influencer.get('userId')}",
        "verified": bool(influencer.get("verified")),
        "description": influencer.get("description") or "",
        "followersCount": influencer.get("followersCount"),
        "avatarUrl": normalize_xueqiu_avatar_url(influencer.get("avatarUrl")),
    }


def extract_user_id(value: str) -> str:
    text = normalize_text(value)
    match = re.search(r"xueqiu\.com/(?:u/)?(\d{5,})", text, re.IGNORECASE)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d{5,}", text):
        return text
    return ""


def normalize_user_profile(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    nested = row.get("user") if isinstance(row.get("user"), dict) else row
    user_id = first_value(nested, "userId", "user_id", "id")
    return {
        "userId": normalize_text(user_id),
        "name": normalize_text(first_value(nested, "screen_name", "screenName", "name")),
        "screenName": normalize_text(first_value(nested, "screen_name", "screenName", "name")),
        "description": normalize_text(first_value(nested, "description", "desc", "remark")),
        "followersCount": safe_number(first_value(nested, "followers_count", "followersCount", "followers")),
        "verified": bool(first_value(nested, "verified", "verified_type")),
        "avatarUrl": normalize_xueqiu_avatar_url(first_value(nested, "profile_image_url", "profileImageUrl", "avatar", "avatarUrl")),
    }


def normalize_xueqiu_avatar_url(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""

    candidates = [candidate.strip() for candidate in text.split(",") if candidate.strip()]
    if not candidates:
        return ""
    selected = next((candidate for candidate in candidates if "!180x180" in candidate), "")
    selected = selected or next((candidate for candidate in candidates if "!50x50" in candidate), "")
    selected = selected or candidates[0]

    if selected.startswith("//"):
        return f"https:{selected}"
    if selected.startswith("http://"):
        return f"https://{selected[7:]}"
    if selected.startswith("https://"):
        return selected
    return f"https://xavatar.imedao.com/{selected.lstrip('/')}"


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [
        payload.get("statuses"),
        payload.get("list"),
        payload.get("items"),
        payload.get("users"),
        payload.get("result"),
        payload.get("data"),
    ]
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            rows.extend(item for item in candidate if isinstance(item, dict))
        elif isinstance(candidate, dict):
            rows.extend(extract_rows(candidate))
    return rows


def parse_activity_row(row: dict[str, Any], influencer: dict[str, Any]) -> dict[str, Any] | None:
    text = strip_html(first_value(row, "title", "description", "text", "content", "status"))
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    published_at = parse_xueqiu_time(first_value(row, "created_at", "timeBefore", "createdAt", "created_at_str"))
    kind = classify_activity(row, text)
    target = first_nested_row(row, "status", "target_status", "targetStatus", "retweeted_status", "target")
    target_title = strip_html(first_value(target, "title", "description", "text")) if target else ""
    media = extract_xueqiu_media(row)
    if target:
        media = dedupe_media([*media, *extract_xueqiu_media(target)])
    if not text and not target_title and not media:
        return None

    activity_id = xueqiu_activity_identifier(row, kind)
    comment_id = xueqiu_comment_identifier(row, kind, activity_id)
    status_id = xueqiu_status_identifier(row, target, kind, activity_id)
    author_user_id = xueqiu_row_user_id(row, influencer)
    status_user_id = xueqiu_status_user_id(row, target, kind, author_user_id, influencer)
    url = build_xueqiu_activity_url(row, target, influencer, kind, status_id, activity_id, comment_id, status_user_id, author_user_id)
    media_signature = ",".join(item.get("url", "") for item in media)

    return {
        "id": f"{influencer.get('id')}:{kind}:{activity_id or status_id or stable_text_id(text, target_title, published_at, media_signature)}",
        "activityId": activity_id,
        "statusId": status_id,
        "commentId": comment_id,
        "influencerId": influencer.get("id"),
        "influencerName": influencer.get("name"),
        "userId": influencer.get("userId"),
        "authorUserId": author_user_id,
        "statusUserId": status_user_id,
        "kind": kind,
        "kindLabel": kind_label(kind),
        "text": text,
        "targetTitle": target_title,
        "url": url,
        "originalUrl": url,
        "profileUrl": influencer.get("profileUrl") or (f"https://xueqiu.com/u/{influencer.get('userId')}" if influencer.get("userId") else XUEQIU_HOME_URL),
        "media": media,
        "source": "雪球",
        "publishedAt": published_at,
        "replyCount": safe_number(first_value(row, "reply_count", "comments_count", "comment_count")),
        "retweetCount": safe_number(first_value(row, "retweet_count", "retweets_count")),
        "likeCount": safe_number(first_value(row, "fav_count", "like_count", "likes_count")),
    }


def classify_activity(row: dict[str, Any], text: str) -> str:
    raw_type = normalize_text(first_value(row, "type", "statusType", "timelineType")).lower()
    if "comment" in raw_type or first_value(row, "comment_id", "commentId"):
        return "comment"
    if "reply" in raw_type or first_value(row, "reply_comment_id", "reply_status_id", "reply_user_id"):
        return "reply"
    if "retweet" in raw_type or isinstance(row.get("retweeted_status"), dict):
        return "repost"
    if re.match(r"^(回复|回覆|评论|回评)\b", text):
        return "reply"
    if text.startswith("//@") or text.startswith("转发"):
        return "repost"
    return "post"


def kind_label(kind: str) -> str:
    return {
        "post": "帖子",
        "comment": "评论",
        "reply": "回复",
        "repost": "转发",
    }.get(kind, "动态")


def first_nested_row(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def xueqiu_activity_identifier(row: dict[str, Any], kind: str) -> str:
    keys = ("id", "comment_id", "commentId", "reply_comment_id", "replyCommentId", "status_id", "statusId", "target_id", "targetId")
    if kind in {"comment", "reply"}:
        keys = ("comment_id", "commentId", "reply_comment_id", "replyCommentId", "id", "status_id", "statusId", "target_id", "targetId")
    return first_xueqiu_id(row, *keys)


def xueqiu_comment_identifier(row: dict[str, Any], kind: str, activity_id: str) -> str:
    comment_id = first_xueqiu_id(row, "comment_id", "commentId", "reply_comment_id", "replyCommentId", "reply_id", "replyId")
    if not comment_id and kind in {"comment", "reply"}:
        comment_id = first_xueqiu_id(row, "id") or activity_id
    return comment_id


def xueqiu_status_identifier(row: dict[str, Any], target: dict[str, Any], kind: str, activity_id: str) -> str:
    if kind in {"comment", "reply"}:
        status_id = first_xueqiu_id(row, "status_id", "statusId", "target_id", "targetId", "root_status_id", "rootStatusId", "reply_status_id", "replyStatusId")
        if status_id:
            return status_id
        return first_xueqiu_id(target, "id", "status_id", "statusId", "target_id", "targetId")
    status_id = first_xueqiu_id(row, "status_id", "statusId", "id", "target_id", "targetId", "target")
    return status_id or activity_id


def first_xueqiu_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (dict, list)):
            continue
        candidate = normalize_xueqiu_id(value)
        if candidate:
            return candidate
    return ""


def normalize_xueqiu_id(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+", text):
        return text
    matches = re.findall(r"/(\d+)(?:[/?#]|$)", text)
    return matches[-1] if matches else ""


def xueqiu_row_user_id(row: dict[str, Any], influencer: dict[str, Any]) -> str:
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return normalize_text(first_value(row, "user_id", "userId", "uid") or user.get("id") or user.get("userId") or influencer.get("userId"))


def xueqiu_status_user_id(row: dict[str, Any], target: dict[str, Any], kind: str, author_user_id: str, influencer: dict[str, Any]) -> str:
    if kind in {"comment", "reply"}:
        target_user_id = xueqiu_container_user_id(target)
        if target_user_id:
            return target_user_id
        status_row = first_nested_row(row, "status", "target_status", "targetStatus")
        target_user_id = xueqiu_container_user_id(status_row)
        if target_user_id:
            return target_user_id
    return author_user_id or normalize_text(influencer.get("userId"))


def xueqiu_container_user_id(row: dict[str, Any]) -> str:
    if not row:
        return ""
    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    return normalize_text(first_value(row, "user_id", "userId", "uid") or user.get("id") or user.get("userId"))


def build_xueqiu_activity_url(
    row: dict[str, Any],
    target: dict[str, Any],
    influencer: dict[str, Any],
    kind: str,
    status_id: str,
    activity_id: str,
    comment_id: str,
    status_user_id: str,
    author_user_id: str,
) -> str:
    explicit_url = first_xueqiu_url(row, "url", "target_url", "targetUrl", "source_url", "sourceUrl", "link")
    if explicit_url:
        return append_xueqiu_comment_anchor(explicit_url, comment_id if kind in {"comment", "reply"} else "")

    target_url = first_xueqiu_url(target, "url", "target_url", "targetUrl", "source_url", "sourceUrl", "link") if target else ""
    if target_url and kind in {"comment", "reply"}:
        return append_xueqiu_comment_anchor(target_url, comment_id)

    page_user_id = status_user_id or (author_user_id if kind not in {"comment", "reply"} else "") or normalize_text(influencer.get("userId"))
    if page_user_id and status_id:
        url = f"https://xueqiu.com/{page_user_id}/{status_id}"
    elif status_id:
        url = f"https://xueqiu.com/statuses/{status_id}"
    elif author_user_id and activity_id and kind not in {"comment", "reply"}:
        url = f"https://xueqiu.com/{author_user_id}/{activity_id}"
    else:
        url = influencer.get("profileUrl") or XUEQIU_HOME_URL
    return append_xueqiu_comment_anchor(url, comment_id if kind in {"comment", "reply"} else "")


def first_xueqiu_url(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (dict, list)):
            continue
        url = normalize_xueqiu_url(value)
        if url:
            return url
    return ""


def normalize_xueqiu_url(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"https://xueqiu.com{text}"
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def append_xueqiu_comment_anchor(url: str, comment_id: str) -> str:
    if not url or not comment_id or "#" in url:
        return url
    return f"{url}#comment_{comment_id}"


def extract_xueqiu_media(row: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(row, dict):
        return []
    items: list[dict[str, str]] = []
    for key in ("pic", "pic_url", "picUrl", "picture", "image", "image_url", "imageUrl", "cover_pic", "coverPic", "thumbnail_pic", "thumbnailPic"):
        collect_xueqiu_media_value(row.get(key), items, key)
    for key in ("pics", "pictures", "images", "image_list", "imageList", "pic_sizes", "picSizes", "card", "cover", "photo"):
        collect_xueqiu_media_value(row.get(key), items, key)
    return dedupe_media(items)


def collect_xueqiu_media_value(value: Any, items: list[dict[str, str]], label: str = "", depth: int = 0) -> None:
    if value in (None, "") or depth > 4:
        return
    if isinstance(value, str):
        url = normalize_xueqiu_media_url(value)
        if url:
            items.append({"type": "image", "url": url, "label": label or "图片"})
        return
    if isinstance(value, list):
        for item in value:
            collect_xueqiu_media_value(item, items, label, depth + 1)
        return
    if isinstance(value, dict):
        for key in ("url", "src", "pic", "pic_url", "picUrl", "image", "image_url", "imageUrl", "original", "origin", "large", "thumbnail", "small", "cover"):
            if key in value:
                collect_xueqiu_media_value(value.get(key), items, key, depth + 1)
        for key in ("items", "list", "pictures", "pics", "images", "sizes"):
            if key in value:
                collect_xueqiu_media_value(value.get(key), items, key, depth + 1)


def normalize_xueqiu_media_url(value: Any) -> str:
    url = normalize_xueqiu_url(value)
    if not url and normalize_text(value).startswith("data:image/"):
        url = normalize_text(value)
    if not url:
        return ""
    return url if is_image_url(url) else ""


def is_image_url(url: str) -> bool:
    return bool(
        url.startswith("data:image/")
        or any(host in url for host in ("xqimg.imedao.com", "assets.imedao.com", "xavatar.imedao.com"))
        or re.search(r"\.(?:png|jpe?g|gif|webp|bmp|avif)(?:[!?&#].*)?$", url, re.IGNORECASE)
    )


def dedupe_media(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen = set()
    for item in items:
        url = normalize_text(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({"type": item.get("type") or "image", "url": url, "label": item.get("label") or "图片"})
    return result


def parse_xueqiu_time(value: Any) -> str:
    text = normalize_text(value)
    number = safe_number(value)
    if number and number > 10_000_000_000:
        return datetime.fromtimestamp(number / 1000, UTC).isoformat()
    if number and number > 1_000_000_000:
        return datetime.fromtimestamp(number, UTC).isoformat()
    if not text:
        return ""

    now = datetime.now(CHINA_TZ)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).isoformat()
    except Exception:
        pass

    match = re.match(r"今天\s*(\d{1,2}):(\d{2})", text)
    if match:
        local = datetime.combine(now.date(), datetime_time(int(match.group(1)), int(match.group(2))), CHINA_TZ)
        return local.astimezone(UTC).isoformat()

    match = re.match(r"昨天\s*(\d{1,2}):(\d{2})", text)
    if match:
        local = datetime.combine(now.date() - timedelta(days=1), datetime_time(int(match.group(1)), int(match.group(2))), CHINA_TZ)
        return local.astimezone(UTC).isoformat()

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, pattern)
            if pattern.startswith("%m"):
                parsed = parsed.replace(year=now.year)
            return parsed.replace(tzinfo=CHINA_TZ).astimezone(UTC).isoformat()
        except Exception:
            continue
    return text


def is_in_date_window(value: Any, start_date: Any, end_date: Any) -> bool:
    activity_date = xueqiu_activity_date(value)
    return bool(activity_date and start_date <= activity_date <= end_date)


def xueqiu_activity_date(value: Any) -> Any:
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except Exception:
            return None
    return parsed.astimezone(CHINA_TZ).date()


def dedupe_activities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("id") or stable_text_id(item.get("text"), item.get("publishedAt"))
        if key and key not in by_id:
            by_id[key] = item
    return list(by_id.values())


def summarize_activities(influencers: list[dict[str, Any]], activities: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"post": 0, "comment": 0, "reply": 0, "repost": 0}
    for activity in activities:
        kind = activity.get("kind") or "post"
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "influencerCount": len(influencers),
        "activityCount": len(activities),
        "postCount": counts.get("post", 0),
        "commentCount": counts.get("comment", 0),
        "replyCount": counts.get("reply", 0),
        "repostCount": counts.get("repost", 0),
    }


def first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return normalize_text(text)


def safe_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def stable_text_id(*parts: Any) -> str:
    text = "|".join(normalize_text(part) for part in parts if normalize_text(part))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else ""


def normalize_error(error: Any) -> str:
    message = normalize_text(error)
    return message or "未知错误"
