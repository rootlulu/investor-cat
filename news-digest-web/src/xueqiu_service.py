from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlencode
from zoneinfo import ZoneInfo

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
XUEQIU_CONFIG_PATH = ROOT_DIR / "config" / "xueqiu_influencers.json"
XUEQIU_COOKIE_FILE = ROOT_DIR / "config" / "xueqiu_cookie.txt"

XUEQIU_HOME_URL = "https://xueqiu.com/"
XUEQIU_USER_SHOW_APIS = (
    "https://xueqiu.com/user/show.json",
    "https://xueqiu.com/users/show.json",
)
XUEQIU_USER_SEARCH_APIS = (
    "https://xueqiu.com/query/v1/search/user.json",
    "https://xueqiu.com/users/search.json",
)
XUEQIU_TIMELINE_APIS = (
    "https://xueqiu.com/v4/statuses/user_timeline.json",
    "https://xueqiu.com/statuses/user_timeline.json",
)
XUEQIU_COMMENT_TIMELINE_APIS = (
    "https://xueqiu.com/v4/statuses/comments_timeline.json",
    "https://xueqiu.com/statuses/comments_timeline.json",
)

CHINA_TZ = ZoneInfo("Asia/Shanghai")
XUEQIU_CACHE_SECONDS = 150
XUEQIU_FETCH_LIMIT = 80
XUEQIU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
XUEQIU_BROWSER_PROFILE_DIR = ROOT_DIR / "data" / "xueqiu-browser-profile"
XUEQIU_BROWSER_LIBRARY_DIR = ROOT_DIR / "data" / "playwright-libs" / "usr" / "lib" / "x86_64-linux-gnu"
XUEQIU_BROWSER_COOKIE_SECONDS = 20 * 60
XUEQIU_BROWSER_LOCK_POLL_SECONDS = 0.25

XUEQIU_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": None}
XUEQIU_BROWSER_COOKIE_CACHE: dict[str, Any] = {"expires_at": 0.0, "cookie": ""}
XUEQIU_BROWSER_FAILURE_CACHE: dict[str, Any] = {"expires_at": 0.0, "message": ""}
XUEQIU_LOCK = asyncio.Lock()


class XueqiuApiError(RuntimeError):
    pass


async def get_xueqiu(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    async with XUEQIU_LOCK:
        if not refresh and XUEQIU_CACHE["data"] and time.time() < XUEQIU_CACHE["expires_at"]:
            data = dict(XUEQIU_CACHE["data"])
            data["cached"] = True
            return data

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

    data = await asyncio.to_thread(fetch_xueqiu_sync)
    async with XUEQIU_LOCK:
        XUEQIU_CACHE["data"] = data
        XUEQIU_CACHE["expires_at"] = time.time() + XUEQIU_CACHE_SECONDS
    return {**data, "imported": imported, "influencer": influencer_public_fields(influencer)}


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


def fetch_xueqiu_sync() -> dict[str, Any]:
    influencers = load_influencers_config()
    today = datetime.now(CHINA_TZ).date()
    generated_at = datetime.now(UTC).isoformat()
    errors: list[str] = []
    activities: list[dict[str, Any]] = []
    influencer_rows: list[dict[str, Any]] = []

    for influencer in influencers:
        row = influencer_public_fields(influencer)
        try:
            fetched = fetch_influencer_today_sync(influencer, today)
            row["activityCount"] = len(fetched)
            row["lastFetchedAt"] = generated_at
            activities.extend(fetched)
        except Exception as error:
            message = normalize_error(error)
            row["activityCount"] = 0
            row["activityError"] = message
            errors.append(f"{row['name']}：{message}")
        influencer_rows.append(row)

    activities = sorted(dedupe_activities(activities), key=lambda item: item.get("publishedAt") or "", reverse=True)
    summary = summarize_activities(influencer_rows, activities)

    return {
        "generatedAt": generated_at,
        "cached": False,
        "source": "雪球公开主页/API",
        "today": today.isoformat(),
        "todayLabel": f"{today.month}月{today.day}日",
        "influencers": influencer_rows,
        "activities": activities,
        "summary": summary,
        "errors": errors,
        "hasData": True,
    }


def fetch_influencer_today_sync(influencer: dict[str, Any], today: Any) -> list[dict[str, Any]]:
    session = create_xueqiu_session()
    rows: list[dict[str, Any]] = []
    required_errors: list[str] = []

    for url in XUEQIU_TIMELINE_APIS:
        try:
            rows.extend(fetch_activity_rows(session, url, influencer, XUEQIU_FETCH_LIMIT))
            if rows:
                break
        except Exception as error:
            required_errors.append(str(error))

    comment_errors: list[str] = []
    for url in XUEQIU_COMMENT_TIMELINE_APIS:
        try:
            comment_rows = fetch_activity_rows(session, url, influencer, XUEQIU_FETCH_LIMIT)
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
        if activity and is_today(activity.get("publishedAt"), today):
            activities.append(activity)

    if comment_errors and activities:
        for activity in activities[:1]:
            activity["note"] = "评论/回复接口可能未完全返回。"
            break
    return activities


def fetch_activity_rows(session: requests.Session, url: str, influencer: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    payload = fetch_xueqiu_json(
        session,
        url,
        params={
            "user_id": influencer.get("userId"),
            "page": "1",
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
        try:
            payload = fetch_xueqiu_json(session, url, params={"user_id": user_id}, timeout=10)
            profile = normalize_user_profile(payload)
            if profile:
                return profile
        except Exception as error:
            errors.append(str(error))
    return {"userId": user_id}


def search_user_profile_sync(query: str) -> dict[str, Any]:
    session = create_xueqiu_session()
    nickname = normalize_nickname_query(query)
    profile = fetch_user_profile_by_nickname_url_sync(session, nickname)
    if profile.get("userId"):
        return profile

    errors = []
    for url in XUEQIU_USER_SEARCH_APIS:
        try:
            payload = fetch_xueqiu_json(session, url, params={"q": nickname, "page": "1", "count": "6"}, timeout=10)
            for row in extract_rows(payload):
                profile = normalize_user_profile(row)
                if profile.get("userId"):
                    return profile
        except Exception as error:
            errors.append(str(error))

    hint = "没有找到匹配的雪球用户，请换一个昵称、粘贴主页链接或数字用户ID。"
    if errors:
        raise ValueError(f"{hint}（{normalize_error(errors[0])}）")
    raise ValueError(hint)


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


def create_xueqiu_session() -> requests.Session:
    session = requests.Session()
    headers = {
        "User-Agent": normalize_text(os.getenv("XUEQIU_USER_AGENT")) or XUEQIU_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": XUEQIU_HOME_URL,
    }
    cookie = get_xueqiu_cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)
    try:
        session.get(XUEQIU_HOME_URL, timeout=8)
    except Exception:
        pass
    return session


def fetch_xueqiu_json(session: requests.Session, url: str, params: dict[str, Any] | None = None, timeout: int = 12) -> dict[str, Any]:
    try:
        response = session.get(url, params=params, timeout=timeout)
        return response_json_or_error(response, url)
    except XueqiuApiError as error:
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
        raise XueqiuApiError("浏览器兜底已关闭，请设置 XUEQIU_BROWSER=1。")
    apply_xueqiu_browser_library_path()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise XueqiuApiError(
            "浏览器模式需要安装 Playwright：pip install -r requirements.txt && python -m playwright install chromium"
        ) from error

    api_url = build_url(url, params)
    timeout_ms = max(timeout * 1000, env_int("XUEQIU_BROWSER_TIMEOUT_MS", 18000))
    wait_ms = env_int("XUEQIU_BROWSER_WAIT_MS", 1000)
    profile_dir = Path(normalize_text(os.getenv("XUEQIU_BROWSER_PROFILE_DIR")) or XUEQIU_BROWSER_PROFILE_DIR)
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        lock_timeout_ms = max(timeout_ms, env_int("XUEQIU_BROWSER_LOCK_TIMEOUT_MS", timeout_ms + 5000))
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
        launch_options: dict[str, Any] = {
            "headless": xueqiu_browser_headless(),
            "channel": normalize_text(os.getenv("XUEQIU_BROWSER_CHANNEL")) or "chromium",
            "viewport": {"width": 1280, "height": 900},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "user_agent": normalize_text(os.getenv("XUEQIU_USER_AGENT")) or XUEQIU_USER_AGENT,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        executable_path = normalize_text(os.getenv("XUEQIU_BROWSER_EXECUTABLE"))
        if executable_path:
            launch_options["executable_path"] = executable_path

        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
        try:
            context.set_default_timeout(timeout_ms)
            context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            add_cookie_header_to_browser_context(context, get_manual_xueqiu_cookie_header())
            if not xueqiu_browser_headless():
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(XUEQIU_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
            response = context.request.get(
                api_url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": XUEQIU_HOME_URL,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=timeout_ms,
            )
            result = {"status": response.status, "text": response.text(), "url": response.url}
            cache_xueqiu_browser_cookies(context.cookies([XUEQIU_HOME_URL]))
            if int(result.get("status") or 0) == 0:
                raise XueqiuApiError(summarize_browser_error(result.get("text")))
            return parse_xueqiu_json_response(
                str(result.get("text") or ""),
                int(result.get("status") or 0),
                normalize_text(result.get("url")) or api_url,
            )
        finally:
            context.close()
    except XueqiuApiError:
        raise
    except Exception as error:
        raise XueqiuApiError(f"浏览器抓取失败：{summarize_browser_error(error)}") from error


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
    if "libnspr4.so" in message or "libnss3.so" in message or "libasound.so.2" in message:
        return "Chromium 缺少运行库；请运行 Playwright 依赖安装，或配置 XUEQIU_BROWSER_LIBRARY_PATH。"
    if "ProcessSingleton" in message or "SingletonLock" in message:
        return "浏览器 profile 被其他 Chromium 进程占用，请稍后重试。"
    if "BROWSER_FETCH_ERROR:AbortError" in message or "Timeout" in message:
        return "浏览器 API 请求超时；通常需要可用登录态、手动滑动验证一次，或配置 XUEQIU_COOKIE。"
    if "ERR_CONNECTION_CLOSED" in message:
        return "雪球主动断开了浏览器连接，通常需要可用登录态；请配置 XUEQIU_COOKIE 或用非 headless 浏览器登录一次。"
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
    if get_recent_xueqiu_browser_failure():
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
        return "雪球返回滑动验证页面。请设置 XUEQIU_BROWSER_HEADLESS=0 手动验证一次，或配置 XUEQIU_COOKIE。"
    return "雪球返回风控页面，稍后重试或配置 XUEQIU_COOKIE。"


def remember_xueqiu_browser_failure(message: str, seconds: int = 60) -> None:
    XUEQIU_BROWSER_FAILURE_CACHE["message"] = normalize_text(message)
    XUEQIU_BROWSER_FAILURE_CACHE["expires_at"] = time.time() + seconds


def get_recent_xueqiu_browser_failure() -> str:
    if time.time() >= float(XUEQIU_BROWSER_FAILURE_CACHE.get("expires_at") or 0):
        return ""
    return normalize_text(XUEQIU_BROWSER_FAILURE_CACHE.get("message"))


def xueqiu_browser_enabled() -> bool:
    return normalize_text(os.getenv("XUEQIU_BROWSER")).lower() not in {"0", "false", "off", "no"}


def xueqiu_browser_headless() -> bool:
    return normalize_text(os.getenv("XUEQIU_BROWSER_HEADLESS") or "1").lower() not in {"0", "false", "off", "no"}


def apply_xueqiu_browser_library_path() -> None:
    configured = normalize_text(os.getenv("XUEQIU_BROWSER_LIBRARY_PATH"))
    lib_dir = Path(configured) if configured else XUEQIU_BROWSER_LIBRARY_DIR
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
    cookie = normalize_text(os.getenv("XUEQIU_COOKIE") or os.getenv("XUEQIU_COOKIES"))
    if cookie:
        return cookie
    cookie_file = Path(normalize_text(os.getenv("XUEQIU_COOKIE_FILE")) or XUEQIU_COOKIE_FILE)
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


def env_int(name: str, default: int) -> int:
    try:
        return int(normalize_text(os.getenv(name)) or default)
    except (TypeError, ValueError):
        return default


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
    return {
        "id": f"user-{user_id_text}",
        "userId": user_id_text,
        "name": screen_name,
        "profileUrl": f"https://xueqiu.com/u/{user_id_text}",
        "verified": verified,
        "description": description,
        "followersCount": followers,
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
    }


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
    status_id = normalize_text(first_value(row, "id", "status_id", "target_id", "comment_id"))
    text = strip_html(first_value(row, "title", "description", "text", "content", "status"))
    if not text:
        return None

    user = row.get("user") if isinstance(row.get("user"), dict) else {}
    user_id = normalize_text(user.get("id") or influencer.get("userId"))
    published_at = parse_xueqiu_time(first_value(row, "created_at", "timeBefore", "createdAt", "created_at_str"))
    kind = classify_activity(row, text)
    target = row.get("retweeted_status") if isinstance(row.get("retweeted_status"), dict) else {}
    target_title = strip_html(first_value(target, "title", "description", "text")) if target else ""
    url = normalize_text(first_value(row, "url", "target"))
    if url and url.startswith("/"):
        url = f"https://xueqiu.com{url}"
    elif not url or not url.startswith("http"):
        url = f"https://xueqiu.com/{user_id}/{status_id}" if user_id and status_id else influencer.get("profileUrl") or XUEQIU_HOME_URL

    return {
        "id": f"{influencer.get('id')}:{kind}:{status_id or stable_text_id(text, published_at)}",
        "influencerId": influencer.get("id"),
        "influencerName": influencer.get("name"),
        "userId": influencer.get("userId"),
        "kind": kind,
        "kindLabel": kind_label(kind),
        "text": text,
        "targetTitle": target_title,
        "url": url,
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


def is_today(value: Any, today: Any) -> bool:
    text = normalize_text(value)
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return text.startswith(today.isoformat())
    return parsed.astimezone(CHINA_TZ).date() == today


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
