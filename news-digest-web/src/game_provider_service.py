from __future__ import annotations

import asyncio
import json
import os
import random
import re
import signal
import socket
import subprocess
import threading
import time
from urllib.request import urlopen
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT_DIR / "data" / "game-provider-profiles"
STATE_PATH = ROOT_DIR / "data" / "game-provider-state.json"
RANKINGS_PATH = ROOT_DIR / "data" / "game_rankings.json"
PLAYWRIGHT_LIBRARY_DIR = ROOT_DIR / "data" / "playwright-libs" / "usr" / "lib" / "x86_64-linux-gnu"

MIN_CRAWL_INTERVAL = timedelta(minutes=30)
RISK_COOLDOWN = timedelta(hours=6)
DAILY_JOB_LIMIT = 6
PAGE_TIMEOUT_MS = 30_000
RANK_LIMIT = 100

PROVIDERS: dict[str, dict[str, str]] = {
    "qimai": {
        "name": "七麦数据",
        "loginUrl": "https://www.qimai.cn/account/signin/r/%2Frank%2Findex%2Fbrand%2Ffree%2Fgenre%2F6014%2Fdevice%2Fiphone%2Fcountry%2Fcn",
        "homeUrl": "https://www.qimai.cn/rank",
    },
    "diandian": {
        "name": "点点数据",
        "loginUrl": "https://app.diandian.com/login?link=https%3A%2F%2Fapp.diandian.com%2Frank%2Fios%2F1-2-172-75-0",
        "homeUrl": "https://app.diandian.com/rank/global/ios",
    },
}

# PointDian uses its own storefront ids. Only verified mappings are enabled.
DIANDIAN_COUNTRY_IDS = {"cn": "75", "us": "24", "jp": "26", "tw": "125"}

AUTH_LOCK = threading.RLock()
CRAWL_LOCK = threading.Lock()
AUTH_SESSIONS: dict[str, dict[str, Any]] = {}
SECURE_RANDOM = random.SystemRandom()


class GameProviderError(RuntimeError):
    pass


async def get_game_provider_auth_states() -> dict[str, Any]:
    return await asyncio.to_thread(get_game_provider_auth_states_sync)


async def start_game_provider_login(provider: str) -> dict[str, Any]:
    return await asyncio.to_thread(start_game_provider_login_sync, provider)


async def complete_game_provider_login(provider: str) -> dict[str, Any]:
    return await asyncio.to_thread(complete_game_provider_login_sync, provider)


async def cancel_game_provider_login(provider: str) -> dict[str, Any]:
    return await asyncio.to_thread(cancel_game_provider_login_sync, provider)


async def crawl_game_provider_rankings(provider: str, country_code: str) -> dict[str, Any]:
    return await asyncio.to_thread(crawl_game_provider_rankings_sync, provider, country_code)


def get_game_provider_auth_states_sync() -> dict[str, Any]:
    state = load_state()
    return {
        "providers": [provider_state(provider, state) for provider in PROVIDERS],
        "policy": {
            "manualLogin": True,
            "minIntervalMinutes": int(MIN_CRAWL_INTERVAL.total_seconds() // 60),
            "dailyJobLimit": DAILY_JOB_LIMIT,
            "pagesPerJob": 2,
            "automaticRetries": 0,
            "message": "只允许手动登录和手动触发采集；串行访问，遇到验证码、403 或 429 立即停止。",
        },
    }


def provider_state(provider: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    definition = provider_definition(provider)
    state = state or load_state()
    saved = state.get("providers", {}).get(provider, {})
    session = current_auth_session(provider)
    profile_dir = provider_profile_dir(provider)
    profile_saved = bool(saved.get("profileSavedAt")) and profile_dir.exists() and any(profile_dir.iterdir())
    status = clean_text(session.get("status")) if session else ("verified" if saved.get("verifiedAt") else ("saved" if profile_saved else "idle"))
    messages = {
        "starting": "正在打开独立登录窗口...",
        "login_open": "官方登录窗口已打开；请在窗口内使用微信扫码登录。",
        "error": "独立登录窗口启动失败。",
        "verified": "登录态已通过最近一次榜单采集验证。",
        "saved": "已保存浏览器会话；采集时会验证登录是否仍有效。",
        "idle": "尚未建立登录会话。",
    }
    return {
        "id": provider,
        "name": definition["name"],
        "status": status,
        "message": clean_text(session.get("message")) if session else messages.get(status, "登录状态未知。"),
        "qrDataUrl": clean_text(session.get("qrDataUrl")) if session else "",
        "stage": clean_text(session.get("stage")) if session else "",
        "diagnostic": clean_text(session.get("diagnostic")) if session else "",
        "loginUrl": definition["loginUrl"],
        "verifiedAt": saved.get("verifiedAt", ""),
        "lastAttemptAt": saved.get("lastAttemptAt", ""),
        "lastSuccessAt": saved.get("lastSuccessAt", ""),
        "cooldownUntil": saved.get("cooldownUntil", ""),
    }


def start_game_provider_login_sync(provider: str) -> dict[str, Any]:
    provider_definition(provider)
    current = current_auth_session(provider)
    if current and current.get("status") in {"starting", "login_open"}:
        return provider_state(provider)
    if current:
        stop_auth_session(provider)
    with AUTH_LOCK:
        ready = threading.Event()
        stop = threading.Event()
        session: dict[str, Any] = {
            "status": "starting",
            "message": "正在打开独立登录窗口...",
            "qrDataUrl": "",
            "ready": ready,
            "stop": stop,
        }
        thread = threading.Thread(target=game_provider_auth_worker, args=(provider, session), daemon=True)
        session["thread"] = thread
        AUTH_SESSIONS[provider] = session
        thread.start()
    return provider_state(provider)


def complete_game_provider_login_sync(provider: str) -> dict[str, Any]:
    provider_definition(provider)
    return provider_state(provider)


def cancel_game_provider_login_sync(provider: str) -> dict[str, Any]:
    provider_definition(provider)
    stop_auth_session(provider)
    return provider_state(provider)


def crawl_game_provider_rankings_sync(provider: str, country_code: str) -> dict[str, Any]:
    definition = provider_definition(provider)
    country_code = normalize_country_code(country_code)
    if not country_code:
        raise GameProviderError("国家/地区代码无效。")
    if provider == "diandian" and country_code not in DIANDIAN_COUNTRY_IDS:
        raise GameProviderError("点点数据当前只启用了中国、美国、日本和中国台湾四个已验证地区。")
    if current_auth_session(provider):
        raise GameProviderError("请先完成或取消页面内扫码登录。")
    if not CRAWL_LOCK.acquire(blocking=False):
        raise GameProviderError("已有榜单采集任务正在执行，请等待它完成。")

    state = load_state()
    try:
        enforce_crawl_policy(provider, state)
        mark_attempt(provider, state)
        save_state(state)
        rows = crawl_two_charts(provider, country_code)
        merge_ranking_rows(rows)
        saved = state.setdefault("providers", {}).setdefault(provider, {})
        now = datetime.now(UTC).isoformat()
        saved.update({"verifiedAt": now, "lastSuccessAt": now, "cooldownUntil": "", "lastError": ""})
        save_state(state)
        return {
            "provider": provider,
            "providerName": definition["name"],
            "countryCode": country_code,
            "rows": len(rows),
            "freeRows": len([row for row in rows if row.get("chart") == "free"]),
            "grossingRows": len([row for row in rows if row.get("chart") == "grossing"]),
            "message": f"{definition['name']} {country_code.upper()} 榜单采集完成，共保存 {len(rows)} 条。",
        }
    except GameProviderError as error:
        saved = state.setdefault("providers", {}).setdefault(provider, {})
        saved["lastError"] = str(error)
        if is_risk_error(str(error)):
            saved["cooldownUntil"] = (datetime.now(UTC) + RISK_COOLDOWN).isoformat()
        save_state(state)
        raise
    finally:
        CRAWL_LOCK.release()


def crawl_two_charts(provider: str, country_code: str) -> list[dict[str, Any]]:
    apply_browser_library_path()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise GameProviderError("缺少 Playwright，无法打开榜单浏览器。") from error

    profile_dir = provider_profile_dir(provider)
    if not profile_dir.exists():
        raise GameProviderError("尚未保存登录会话，请先点击登录。")

    rows: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            process, browser, context, page = launch_raw_provider_browser(playwright, profile_dir, "about:blank")
            try:
                context.set_default_timeout(PAGE_TIMEOUT_MS)
                for index, chart in enumerate(("free", "grossing")):
                    if index:
                        time.sleep(SECURE_RANDOM.uniform(4.0, 7.0))
                    rows.extend(crawl_chart_page(page, provider, country_code, chart))
            finally:
                close_raw_provider_browser(process, browser)
    except GameProviderError:
        raise
    except Exception as error:
        raise GameProviderError(f"榜单浏览器执行失败：{summarize_browser_error(error)}") from error
    return rows


def crawl_chart_page(page: Any, provider: str, country_code: str, chart: str) -> list[dict[str, Any]]:
    url = provider_rank_url(provider, country_code, chart)
    response = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    status = response.status if response else 0
    if status in {401, 403, 429}:
        raise GameProviderError(f"RISK_STOP：站点返回 HTTP {status}，已停止采集并进入冷却。")
    if status >= 400:
        raise GameProviderError(f"榜单页面返回 HTTP {status}。")

    time.sleep(SECURE_RANDOM.uniform(2.5, 4.5))
    assert_page_is_available(page)
    raw_rows = extract_rows_from_page(page)
    previous_count = len(raw_rows)
    for _ in range(8):
        if len(raw_rows) >= RANK_LIMIT:
            break
        page.mouse.wheel(0, SECURE_RANDOM.randint(650, 1050))
        time.sleep(SECURE_RANDOM.uniform(0.9, 1.5))
        assert_page_is_available(page)
        raw_rows = extract_rows_from_page(page)
        if len(raw_rows) == previous_count and len(raw_rows) >= 20:
            break
        previous_count = len(raw_rows)

    rows = normalize_extracted_rows(raw_rows, provider, country_code, chart, url)
    if len(rows) < 10:
        raise GameProviderError("未识别出有效榜单；可能登录已失效、页面要求验证，或站点结构已经变化。")
    return rows[:RANK_LIMIT]


def extract_rows_from_page(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(
        r"""
        () => {
          const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
          const rankOf = (text) => {
            const lines = String(text || '').split(/\n+/).map(clean).filter(Boolean);
            for (const line of lines.slice(0, 5)) {
              const match = line.match(/^(?:#\s*)?(\d{1,3})(?:\s|$)/);
              if (match) return Number(match[1]);
            }
            return 0;
          };
          const rows = [];
          const seen = new Set();
          const push = (container, anchor) => {
            if (!container || !anchor) return;
            const text = container.innerText || '';
            const rank = rankOf(text);
            if (rank < 1 || rank > 200) return;
            const image = container.querySelector('img');
            const title = clean(anchor.getAttribute('title') || anchor.innerText || image?.alt);
            if (!title || title.length > 180 || /登录|注册|更多|趋势/.test(title)) return;
            const key = `${rank}:${title}`;
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({
              rank,
              title,
              href: anchor.href || '',
              image: image?.currentSrc || image?.src || '',
              lines: String(text).split(/\n+/).map(clean).filter(Boolean).slice(0, 14),
            });
          };

          for (const tr of document.querySelectorAll('tbody tr')) {
            const anchor = tr.querySelector('a[href*="/app/"],a[href*="appid"],a[href*="/detail/"]');
            push(tr, anchor);
          }
          for (const anchor of document.querySelectorAll('a[href*="/app/"],a[href*="appid"],a[href*="/detail/"]')) {
            const container = anchor.closest('li,tr,[class*="rank-item"],[class*="rankItem"],[class*="list-item"],[class*="listItem"]') || anchor.parentElement?.parentElement;
            push(container, anchor);
          }
          return rows.sort((a, b) => a.rank - b.rank);
        }
        """
    )


def normalize_extracted_rows(
    rows: list[dict[str, Any]], provider: str, country_code: str, chart: str, source_url: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_ranks: set[int] = set()
    now = datetime.now(UTC).isoformat()
    for raw in rows:
        rank = safe_int(raw.get("rank"))
        title = clean_text(raw.get("title"))
        if not rank or rank > RANK_LIMIT or rank in seen_ranks or not title:
            continue
        seen_ranks.add(rank)
        lines = [clean_text(line) for line in raw.get("lines", []) if clean_text(line)]
        publisher = next(
            (
                line
                for line in reversed(lines)
                if line != title and not re.fullmatch(r"#?\d{1,3}", line) and line not in {"AD", "免费", "畅销"}
            ),
            "",
        )
        href = clean_text(raw.get("href"))
        app_id_match = re.search(r"(?:appid/|appid=|/app/[^/]+/)([A-Za-z0-9_-]{5,})", href)
        result.append(
            {
                "provider": provider,
                "country_code": country_code,
                "chart": chart,
                "rank": rank,
                "game": title,
                "publisher": publisher,
                "platform": "iOS",
                "app_id": app_id_match.group(1) if app_id_match else "",
                "url": href or source_url,
                "artwork_url": clean_text(raw.get("image")),
                "updated_at": now,
                "note": "用户手动登录后，由低频可见浏览器会话采集；无验证码绕过或自动重试。",
            }
        )
    return result


def provider_rank_url(provider: str, country_code: str, chart: str) -> str:
    provider_definition(provider)
    if chart not in {"free", "grossing"}:
        raise GameProviderError("不支持的榜单类型。")
    country_code = normalize_country_code(country_code)
    if provider == "qimai":
        return f"https://www.qimai.cn/rank/index/brand/{chart}/genre/6014/device/iphone/country/{country_code}"
    country_id = DIANDIAN_COUNTRY_IDS.get(country_code)
    if not country_id:
        raise GameProviderError("点点数据尚未启用这个地区的链接映射。")
    chart_id = "0" if chart == "free" else "4"
    return f"https://app.diandian.com/rank/ios/1-2-172-{country_id}-{chart_id}"


def assert_page_is_available(page: Any) -> None:
    text = clean_text(page.locator("body").inner_text(timeout=PAGE_TIMEOUT_MS))[:12_000]
    risk_markers = ("访问过于频繁", "安全验证", "滑块验证", "captcha", "robot check", "请求太频繁")
    if any(marker.lower() in text.lower() for marker in risk_markers):
        raise GameProviderError("RISK_STOP：页面触发了安全验证，已停止采集并进入冷却；请勿连续重试。")
    login_markers = ("登录/注册后可查看更多数据", "after Login Real Data can be Viewed")
    if any(marker.lower() in text.lower() for marker in login_markers):
        raise GameProviderError("登录态无效，请重新打开登录窗口并手动登录。")


def enforce_crawl_policy(provider: str, state: dict[str, Any]) -> None:
    saved = state.setdefault("providers", {}).setdefault(provider, {})
    now = datetime.now(UTC)
    cooldown = parse_datetime(saved.get("cooldownUntil"))
    if cooldown and cooldown > now:
        raise GameProviderError(f"风控冷却中，请在 {cooldown.astimezone().strftime('%m-%d %H:%M')} 后再试。")
    last_attempt = parse_datetime(saved.get("lastAttemptAt"))
    if last_attempt and now - last_attempt < MIN_CRAWL_INTERVAL:
        next_at = last_attempt + MIN_CRAWL_INTERVAL
        raise GameProviderError(f"低频保护：请在 {next_at.astimezone().strftime('%H:%M')} 后再采集。")
    daily = saved.get("daily") if isinstance(saved.get("daily"), dict) else {}
    if daily.get("date") == date.today().isoformat() and safe_int(daily.get("jobs")) >= DAILY_JOB_LIMIT:
        raise GameProviderError(f"低频保护：今天已达到 {DAILY_JOB_LIMIT} 次手动采集上限。")


def mark_attempt(provider: str, state: dict[str, Any]) -> None:
    saved = state.setdefault("providers", {}).setdefault(provider, {})
    saved["lastAttemptAt"] = datetime.now(UTC).isoformat()
    today = date.today().isoformat()
    daily = saved.get("daily") if isinstance(saved.get("daily"), dict) else {}
    if daily.get("date") != today:
        daily = {"date": today, "jobs": 0}
    daily["jobs"] = safe_int(daily.get("jobs")) + 1
    saved["daily"] = daily


def merge_ranking_rows(new_rows: list[dict[str, Any]], path: Path = RANKINGS_PATH) -> None:
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                existing = [row for row in payload if isinstance(row, dict)]
        except (OSError, json.JSONDecodeError):
            existing = []
    scopes = {(row.get("provider"), row.get("country_code"), row.get("chart")) for row in new_rows}
    merged = [
        row
        for row in existing
        if (row.get("provider"), row.get("country_code") or row.get("countryCode"), row.get("chart")) not in scopes
    ]
    merged.extend(new_rows)
    merged.sort(key=lambda row: (clean_text(row.get("provider")), clean_text(row.get("country_code")), clean_text(row.get("chart")), safe_int(row.get("rank"))))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def provider_definition(provider: str) -> dict[str, str]:
    key = clean_text(provider).lower()
    if key not in PROVIDERS:
        raise GameProviderError("只支持七麦数据和点点数据。")
    return PROVIDERS[key]


def provider_profile_dir(provider: str) -> Path:
    provider_definition(provider)
    return PROFILE_ROOT / provider


def current_auth_session(provider: str) -> dict[str, Any] | None:
    with AUTH_LOCK:
        session = AUTH_SESSIONS.get(provider)
        if not session:
            return None
        thread = session.get("thread")
        status = clean_text(session.get("status"))
        if thread and thread.is_alive():
            return session
        if status == "error":
            return session
        AUTH_SESSIONS.pop(provider, None)
        return None


def stop_auth_session(provider: str) -> None:
    with AUTH_LOCK:
        session = AUTH_SESSIONS.pop(provider, None)
    if not session:
        return
    stop = session.get("stop")
    thread = session.get("thread")
    if stop:
        stop.set()
    if thread and thread is not threading.current_thread():
        thread.join(timeout=8)


def game_provider_auth_worker(provider: str, session: dict[str, Any]) -> None:
    apply_browser_library_path()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        set_auth_session_error(session, "缺少 Playwright，无法打开独立登录窗口。", error)
        return

    process = None
    browser = None
    context = None
    page = None
    try:
        definition = provider_definition(provider)
        profile_dir = provider_profile_dir(provider)
        profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            session["stage"] = "launching_browser"
            process, browser, context, page = launch_raw_provider_browser(
                playwright,
                profile_dir,
                definition["loginUrl"],
                visible=True,
            )
            context.set_default_timeout(PAGE_TIMEOUT_MS)
            session["stage"] = "opening_login_window"
            if page.url != definition["loginUrl"]:
                page.goto(definition["loginUrl"], wait_until="commit", timeout=PAGE_TIMEOUT_MS)
            page.bring_to_front()
            page.wait_for_timeout(1800)
            session["stage"] = "preparing_wechat_login"
            qr_ready = prepare_provider_login_window(page, provider)
            message = f"{definition['name']}官方登录窗口已打开，请在窗口内使用微信扫码登录；成功后会自动保存会话。"
            if not qr_ready:
                message = f"{definition['name']}官方登录窗口已打开，请在窗口内选择微信扫码登录；成功后会自动保存会话。"
            with AUTH_LOCK:
                session.update(
                    {
                        "status": "login_open",
                        "stage": "waiting_for_scan",
                        "message": message,
                        "qrDataUrl": "",
                    }
                )
            session["ready"].set()

            while not session["stop"].wait(2.0):
                if (process and process.poll() is not None) or page.is_closed():
                    set_auth_session_error(session, "登录窗口已关闭，尚未检测到登录成功；请重新打开后登录。")
                    return
                if provider_login_succeeded(page, provider):
                    mark_provider_profile_saved(provider)
                    with AUTH_LOCK:
                        session.update({"status": "authenticated", "message": "登录成功，会话已保存。", "qrDataUrl": ""})
                    return
    except Exception as error:
        if page is not None:
            try:
                session["diagnostic"] = f"URL={page.url}"
                body = clean_text(page.locator("body").inner_text(timeout=3000))[:1200]
                if body:
                    session["diagnostic"] += f"; BODY={body}"
            except Exception:
                pass
        set_auth_session_error(session, f"独立登录窗口启动失败：{summarize_browser_error(error)}", error)
    finally:
        try:
            if process or browser:
                close_raw_provider_browser(process, browser)
        except Exception:
            pass
        session["ready"].set()


def launch_raw_provider_browser(
    playwright: Any,
    profile_dir: Path,
    initial_url: str,
    *,
    visible: bool = False,
) -> tuple[Any, Any, Any, Any]:
    executable = playwright.chromium.executable_path
    if not executable or not Path(executable).exists():
        raise GameProviderError("没有找到 Playwright Chromium。")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = build_provider_browser_command(executable, profile_dir, initial_url, port=port, visible=visible)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise GameProviderError("登录浏览器启动后立即退出。")
        try:
            with urlopen(f"{endpoint}/json/version", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.35)
    else:
        close_raw_provider_browser(process, None)
        raise GameProviderError("连接登录浏览器超时。")

    browser = None
    try:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=PAGE_TIMEOUT_MS)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        restored_pages = list(context.pages)
        page = next((candidate for candidate in restored_pages if candidate.url == initial_url), None)
        if page is None and restored_pages:
            page = restored_pages[0]
        if page is None:
            page = context.new_page()
        for restored_page in restored_pages:
            if restored_page is page:
                continue
            try:
                restored_page.close()
            except Exception:
                pass
        return process, browser, context, page
    except Exception:
        close_raw_provider_browser(process, browser)
        raise


def build_provider_browser_command(
    executable: str,
    profile_dir: Path,
    initial_url: str,
    *,
    port: int,
    visible: bool,
) -> list[str]:
    command = [
        executable,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-http2",
        "--no-sandbox",
        "--lang=zh-CN",
    ]
    if visible:
        command.extend(
            [
                "--window-size=1120,820",
                "--window-position=120,80",
                f"--app={initial_url}",
            ]
        )
    else:
        command.extend(
            [
                "--window-size=1280,900",
                "--window-position=-32000,-32000",
                initial_url,
            ]
        )
    return command


def close_raw_provider_browser(process: Any, browser: Any) -> None:
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    if not process or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def prepare_provider_login_window(page: Any, provider: str) -> bool:
    if provider == "qimai":
        try:
            trigger = page.locator("#qrcode-signin .wx-signin")
            trigger.wait_for(state="visible", timeout=10_000)
            trigger.click(force=True)
            qr_image = page.locator("#qrcode-signin .popup .content .qrcode-img img")
            qr_image.wait_for(state="visible", timeout=10_000)
            return True
        except Exception:
            return False

    if provider == "diandian":
        try:
            qr_image = page.locator("img.qr-img, img[src*='mp.weixin.qq.com/cgi-bin/showqrcode']")
            qr_triggered = False
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if qr_image.count() >= 1 and qr_image.last.is_visible():
                    return True
                if not qr_triggered:
                    for label in ("QR Code", "二维码", "微信扫码登录", "扫码登录"):
                        candidate = page.get_by_text(label, exact=True)
                        if candidate.count() >= 1 and candidate.last.is_visible():
                            candidate.last.click(timeout=3000)
                            qr_triggered = True
                            break
                page.wait_for_timeout(500)
            return False
        except Exception:
            # 点点的二维码节点和生成方式会变化。窗口本身是官方页面，节点变化
            # 不应再导致登录会话失败或关闭；用户仍可直接在窗口中完成操作。
            return False

    for label in ("登录/注册", "Login & Sign up", "登录"):
        candidate = page.get_by_text(label, exact=True)
        if candidate.count() >= 1:
            candidate.first.click()
            page.wait_for_timeout(1500)
            break
    for label in ("微信扫码登录", "微信登录", "扫码登录"):
        candidate = page.get_by_text(label, exact=True)
        if candidate.count() >= 1:
            candidate.last.click()
            page.wait_for_timeout(1200)
            break
    return True


def provider_login_succeeded(page: Any, provider: str) -> bool:
    try:
        body = clean_text(page.locator("body").inner_text(timeout=5000))
        if provider == "qimai":
            has_login_form = page.locator("input[placeholder='请输入手机号/邮箱']:visible").count() > 0
            modal_open = page.locator("#qrcode-signin .popup .content:visible").count() > 0
            return not has_login_form and not modal_open and "登录/注册后可查看更多数据" not in body
        if provider == "diandian":
            qr_open = page.locator("img.qr-img:visible").count() > 0
            login_page = "/login" in page.url
            gate_markers = ("以下为示例图，登录后可查看真实数据", "登录后查看真实数据")
            return not login_page and not qr_open and not any(marker in body for marker in gate_markers) and len(body) > 80
        gate_markers = ("登录后查看真实数据", "after Login Real Data can be Viewed", "Login & Sign up")
        return not any(marker.lower() in body.lower() for marker in gate_markers) and len(body) > 80
    except Exception:
        return False


def mark_provider_profile_saved(provider: str) -> None:
    state = load_state()
    saved = state.setdefault("providers", {}).setdefault(provider, {})
    saved["profileSavedAt"] = datetime.now(UTC).isoformat()
    saved["lastAttemptAt"] = ""
    save_state(state)


def set_auth_session_error(session: dict[str, Any], message: str, error: Exception | None = None) -> None:
    with AUTH_LOCK:
        session.update({"status": "error", "message": message, "qrDataUrl": ""})
        if error:
            session["error"] = clean_text(error)
    session["ready"].set()


def apply_browser_library_path() -> None:
    if not PLAYWRIGHT_LIBRARY_DIR.exists():
        return
    current = [item for item in clean_text(os.getenv("LD_LIBRARY_PATH")).split(":") if item]
    library = str(PLAYWRIGHT_LIBRARY_DIR)
    if library not in current:
        os.environ["LD_LIBRARY_PATH"] = ":".join([library, *current])


def load_state() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"providers": {}}
    except (OSError, json.JSONDecodeError):
        return {"providers": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(f"{STATE_PATH.suffix}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def normalize_country_code(value: Any) -> str:
    text = re.sub(r"[^a-z]", "", clean_text(value).lower())
    return text if len(text) == 2 else ""


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_risk_error(message: str) -> bool:
    text = message.lower()
    return "risk_stop" in text or "http 403" in text or "http 429" in text


def summarize_browser_error(error: Exception) -> str:
    message = clean_text(error)
    if "ProcessSingleton" in message or "SingletonLock" in message:
        return "浏览器 profile 正被登录窗口占用，请先点击登录完成。"
    if "Executable doesn't exist" in message:
        return "没有找到 Playwright Chromium。"
    return f"{message[:220]}..." if len(message) > 220 else message
