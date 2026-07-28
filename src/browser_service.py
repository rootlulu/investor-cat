"""共享的「模拟浏览器抓取」模块。

项目里雪球（被封 IP 时）与游戏榜单都用 Playwright/Chromium 做浏览器模拟抓取。
此前两套实现各自重复了「注入运行库路径 / 异常中文化 / 启动持久化上下文」等样板。
本模块统一这些能力：

- ``apply_browser_library_path``：把 Chromium 运行库路径注入 ``LD_LIBRARY_PATH``。
- ``summarize_browser_error``：把常见 Playwright 异常转成中文可读信息。
- ``launch_browser_context``：上下文管理器，等价于 ``launch_persistent_context``（headless + 真实 UA/locale/时区）。
- ``fetch_html_via_browser`` / ``fetch_json_via_browser``：基于**专用单线程 worker +
  非持久 BrowserContext** 取数，供游戏区域等高频抓取复用。
- ``close_browser_session``：关闭单例会话（已注册 atexit）。

浏览器模拟用于规避 Steam 等对裸 HTTP 的限流/封禁：真实 UA、中文 locale、上海时区。
自动取数不使用持久 profile；需要保存登录态的业务显式使用 ``launch_browser_context``。
"""

from __future__ import annotations

import atexit
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, urlencode, urlparse

from .request_coordinator import (
    DomainCoolingDown,
    REQUEST_COORDINATOR,
    check_response_risk,
    domain_slot,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
BROWSER_SETTINGS_PATH = ROOT_DIR / "config" / "browser_settings.json"
DEFAULT_BROWSER_LIBRARY_PATH = ROOT_DIR / "data" / "playwright-libs" / "usr" / "lib" / "x86_64-linux-gnu"

DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
DEFAULT_TIMEOUT_MS = 20000
DEFAULT_VIEWPORT = {"width": 1280, "height": 900}

_BROWSER_LOCK = threading.Lock()
_BROWSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-service")
_BROWSER_WORKER_ID: int | None = None
_PLAYWRIGHT = None
_BROWSER = None
_CONTEXT = None
_CONTEXT_PROXY_KEY: str | None = None


def load_browser_settings() -> dict[str, Any]:
    if BROWSER_SETTINGS_PATH.exists():
        try:
            data = json.loads(BROWSER_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _settings() -> dict[str, Any]:
    return load_browser_settings()


def apply_browser_library_path(lib_dir: Any = None) -> None:
    """把 Chromium 运行库路径注入 LD_LIBRARY_PATH（仅当目录存在）。

    ``lib_dir`` 优先；为空时回退到 config/browser_settings.json 的 ``libraryPath``，
    再回退到环境变量 ``PLAYWRIGHT_LIBRARY_PATH``。
    """
    if lib_dir:
        raw = str(lib_dir)
    else:
        settings = _settings()
        raw = settings.get("libraryPath") or os.environ.get("PLAYWRIGHT_LIBRARY_PATH") or ""
    resolved = Path(raw) if raw else DEFAULT_BROWSER_LIBRARY_PATH
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    if not resolved or not resolved.exists():
        return
    library = str(resolved)
    current = [item for item in os.environ.get("LD_LIBRARY_PATH", "").split(":") if item]
    if library in current:
        return
    os.environ["LD_LIBRARY_PATH"] = ":".join([library, *current])


def _wsl_windows_host() -> str:
    """Return the Windows-side default gateway without changing WSL networking."""
    if not (os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME")):
        return ""
    try:
        route_lines = Path("/proc/net/route").read_text(encoding="ascii").splitlines()
    except OSError:
        return ""
    for line in route_lines[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[1] != "00000000":
            continue
        try:
            gateway = int(fields[2], 16)
        except ValueError:
            continue
        return ".".join(str((gateway >> shift) & 0xFF) for shift in (0, 8, 16, 24))
    return ""


def _proxy_host_matches(hostname: str, patterns: list[str]) -> bool:
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip().lower()
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if hostname.endswith(suffix):
                return True
        elif hostname == pattern:
            return True
    return False


def resolve_browser_proxy(url: str) -> dict[str, str] | None:
    """Resolve an opt-in Playwright proxy for matching hosts.

    Explicit ``BROWSER_PROXY_SERVER`` wins. When configured, WSL gateway
    discovery only reads ``/proc/net/route``; it does not change networking.
    """
    settings = _settings()
    proxy_config = settings.get("proxy")
    if not isinstance(proxy_config, dict):
        proxy_config = {}

    explicit_server = str(os.environ.get("BROWSER_PROXY_SERVER") or "").strip()
    if not explicit_server and not bool(proxy_config.get("enabled", False)):
        return None

    hostname = (urlparse(url).hostname or "").lower()
    hosts = proxy_config.get("hosts") or []
    if hosts and not _proxy_host_matches(hostname, [str(item) for item in hosts]):
        return None

    server = explicit_server or str(proxy_config.get("server") or "").strip()
    if not server and bool(proxy_config.get("autoDetectWslHost", False)):
        host = _wsl_windows_host()
        try:
            port = int(proxy_config.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if host and 0 < port <= 65535:
            server = f"http://{host}:{port}"
    if not server:
        return None

    proxy: dict[str, str] = {"server": server}
    bypass = str(proxy_config.get("bypass") or "").strip()
    if bypass:
        proxy["bypass"] = bypass
    username = str(os.environ.get("BROWSER_PROXY_USERNAME") or "").strip()
    password = str(os.environ.get("BROWSER_PROXY_PASSWORD") or "").strip()
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy


def _proxy_key(proxy: dict[str, str] | None) -> str:
    return json.dumps(proxy or {}, sort_keys=True, ensure_ascii=True)


def _with_query_value(url: str, name: str, value: str) -> str:
    parsed = urlparse(url)
    query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key != name]
    query.append((name, value))
    return parsed._replace(query=urlencode(query)).geturl()


def _resolve_profile_path(value: Any) -> Path:
    path = Path(str(value or "data/browser-profile"))
    return path if path.is_absolute() else ROOT_DIR / path


def summarize_browser_error(
    error: Any,
    *,
    interactive_login_hint: str | None = None,
) -> str:
    """把常见 Playwright / 网络异常转成中文可读信息。

    ``interactive_login_hint``：当业务方（如雪球）需要可交互浏览器（headless=false + 手动验证）时，
    传入对应提示文案；命中「需要可交互浏览器 / 已打开浏览器等待」类错误时直接返回该提示，
    这样业务方无需重复实现自己的映射。
    """
    message = str(error)
    lowered = message.lower()
    if interactive_login_hint and ("需要可交互浏览器" in message or "已打开浏览器等待" in message):
        return interactive_login_hint
    if "ProcessSingleton" in message or "SingletonLock" in message:
        return "浏览器 profile 被其他 Chromium 进程占用，请先关闭其它浏览器进程或清理 profile 目录。"
    if "Executable doesn't exist" in message or "executable doesn't exist" in lowered:
        return "未找到 Playwright Chromium，请运行：python -m playwright install chromium"
    if "libnss3" in lowered or "libnspr4" in lowered or "libasound" in lowered or "error while loading shared libraries" in lowered or "cannot open shared object" in lowered:
        return "Chromium 缺少系统运行库（如 libnss3），请在系统中安装对应依赖或配置 browser.libraryPath。"
    if "Target page" in message and "closed" in message:
        return "浏览器页面在取数前被关闭，可能触发了风控或超时。"
    if "ERR_CONNECTION_CLOSED" in message:
        return "目标站点主动断开了浏览器连接，通常需要可用登录态；请配置业务方 auth.cookie 或用非 headless 浏览器手动登录一次。"
    if "Timeout" in message or "timeout" in lowered:
        return f"浏览器取数超时：{message}"
    if len(message) > 220:
        return f"{message[:220]}..."
    return message or "未知浏览器错误"


def is_risk_control_page(
    text: str,
    *,
    tokens: tuple[str, ...] = ("滑动验证", "访问验证", "aliyun_waf", "_waf_"),
) -> bool:
    """检测响应文本是否是风控 / 验证页（HTML 开头或包含 WAF / 滑块特征）。

    业务方（如雪球）可传 ``tokens`` 追加自定义特征；默认 token 覆盖雪球 aliyun WAF 与中文滑块文案。
    """
    if not text:
        return True
    head = text[:5000]
    return text.startswith("<") or any(t in head for t in tokens)


def browser_available() -> bool:
    apply_browser_library_path()
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        settings = _settings()
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": True,
                "channel": settings.get("channel", "chromium"),
                "args": settings.get("args") or DEFAULT_BROWSER_ARGS,
            }
            executable = str(settings.get("executable") or "").strip()
            if executable:
                launch_options["executable_path"] = executable
            browser = playwright.chromium.launch(**launch_options)
            browser.close()
            return True
    except Exception:
        return False


@contextmanager
def launch_browser_context(
    *,
    headless: bool | None = None,
    channel: str = "chromium",
    executable: str = "",
    user_agent: str = DEFAULT_BROWSER_UA,
    locale: str = "zh-CN",
    timezone_id: str = "Asia/Shanghai",
    viewport: dict | None = None,
    args: list[str] | None = None,
    profile_dir: str = "",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    proxy: dict[str, str] | None = None,
) -> Iterator[Any]:
    """启动一个持久化 Chromium 上下文（headless 默认），等价于 xueqiu 原有 launch_persistent_context。

    用法::

        with launch_browser_context(profile_dir=str(p), headless=True) as context:
            context.set_extra_http_headers({...})
            ...
    """
    apply_browser_library_path()
    from playwright.sync_api import sync_playwright

    settings = _settings()
    if headless is None:
        headless = bool(settings.get("headless", True))
    resolved_profile = profile_dir or settings.get("profileDir") or "data/browser-profile"
    resolved_args = args if args is not None else (settings.get("args") or DEFAULT_BROWSER_ARGS)
    resolved_viewport = viewport or settings.get("viewport") or DEFAULT_VIEWPORT

    path = _resolve_profile_path(resolved_profile)
    path.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": headless,
            "channel": channel,
            "viewport": resolved_viewport,
            "locale": locale,
            "timezone_id": timezone_id,
            "user_agent": user_agent,
            "args": resolved_args,
        }
        if executable:
            launch_options["executable_path"] = executable
        if proxy:
            launch_options["proxy"] = proxy
        context = playwright.chromium.launch_persistent_context(str(path), **launch_options)
        try:
            context.set_default_timeout(timeout_ms)
            context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            yield context
        finally:
            context.close()


# ---------------------------------------------------------------------------
# 进程级单例浏览器会话（供游戏区域等高频抓取复用）
# ---------------------------------------------------------------------------
def _run_on_browser_thread(callback: Any) -> Any:
    """Run every sync Playwright operation on one thread for its full lifecycle."""
    global _BROWSER_WORKER_ID
    if threading.get_ident() == _BROWSER_WORKER_ID:
        return callback()

    def invoke() -> Any:
        global _BROWSER_WORKER_ID
        _BROWSER_WORKER_ID = threading.get_ident()
        return callback()

    return _BROWSER_EXECUTOR.submit(invoke).result()


def _safe_reset_session() -> None:
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _CONTEXT_PROXY_KEY
    ctx, browser, pw = _CONTEXT, _BROWSER, _PLAYWRIGHT
    _CONTEXT, _BROWSER, _PLAYWRIGHT = None, None, None
    _CONTEXT_PROXY_KEY = None
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


def _ensure_session(proxy: dict[str, str] | None = None) -> Any:
    """在调用方已持有 _BROWSER_LOCK 时调用。返回单例非持久上下文。"""
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _CONTEXT_PROXY_KEY
    proxy_key = _proxy_key(proxy)
    if _CONTEXT is not None and _CONTEXT_PROXY_KEY == proxy_key:
        return _CONTEXT
    if _CONTEXT is not None or _BROWSER is not None or _PLAYWRIGHT is not None:
        _safe_reset_session()
    apply_browser_library_path()
    from playwright.sync_api import sync_playwright

    settings = _settings()
    playwright = sync_playwright().start()
    launch_options: dict[str, Any] = {
        "headless": bool(settings.get("headless", True)),
        "channel": settings.get("channel", "chromium"),
        "args": settings.get("args") or DEFAULT_BROWSER_ARGS,
    }
    context_options: dict[str, Any] = {
        "viewport": settings.get("viewport") or DEFAULT_VIEWPORT,
        "locale": settings.get("locale", "zh-CN"),
        "timezone_id": settings.get("timezoneId", "Asia/Shanghai"),
        "user_agent": settings.get("userAgent", DEFAULT_BROWSER_UA),
    }
    executable = str(settings.get("executable") or "").strip()
    if executable:
        launch_options["executable_path"] = executable
    if proxy:
        launch_options["proxy"] = proxy
    browser = None
    context = None
    try:
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(**context_options)
        context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    except Exception:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        playwright.stop()
        raise
    _PLAYWRIGHT = playwright
    _BROWSER = browser
    _CONTEXT = context
    _CONTEXT_PROXY_KEY = proxy_key
    return context


def close_browser_session() -> None:
    def close() -> None:
        with _BROWSER_LOCK:
            _safe_reset_session()

    try:
        _run_on_browser_thread(close)
    except RuntimeError:
        # Interpreter shutdown may stop the executor before our atexit hook.
        pass


def _run_browser_fetch(fetch_fn: Any, url: str, retries: int = 1) -> Any:
    def run() -> Any:
        first_error: Exception | None = None
        for attempt in range(retries + 1):
            retryable = False
            with _BROWSER_LOCK:
                try:
                    return fetch_fn()
                except DomainCoolingDown:
                    _safe_reset_session()
                    raise
                except Exception as error:  # noqa: BLE001 - 由调用方决定如何呈现
                    if first_error is None:
                        first_error = error
                    retryable = _browser_error_is_retryable(error)
                    _safe_reset_session()
            if attempt >= retries or not retryable:
                break
            time.sleep(REQUEST_COORDINATOR.retry_delay(url, attempt))
        raise first_error if first_error else RuntimeError("browser fetch failed")

    return _run_on_browser_thread(run)


def _browser_error_is_retryable(error: Exception) -> bool:
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    message = str(error).lower()
    if re.search(r"\bhttp\s+5\d\d\b", message):
        return True
    return any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "net::err_",
            "connection reset",
            "connection closed",
            "target closed",
            "browser has been closed",
            "browser crash",
            "browser crashed",
        )
    )


def fetch_html_via_browser(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """用单例浏览器打开页面并返回渲染后的 HTML（给 Steam 热销榜 / SteamCharts 用）。"""

    def _run() -> str:
        context = _ensure_session(resolve_browser_proxy(url))
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            with domain_slot(url):
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                wait_ms = max(0, int(_settings().get("waitMs") or 0))
                if wait_ms:
                    page.wait_for_timeout(wait_ms)
                html = page.content()
                check_response_risk(
                    url,
                    status_code=_browser_response_status(response),
                    headers=_browser_response_headers(response),
                    body=html,
                )
                return html
        finally:
            try:
                page.close()
            except Exception:
                pass

    return _run_browser_fetch(_run, url)


def fetch_page_json_response_via_browser(
    page_url: str,
    response_url_contains: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    *,
    response_url_predicate: Callable[[str], bool] | None = None,
    response_url_transform: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Open a page and return the JSON response matching ``response_url_contains``.

    Steam service pages request protobuf by default. When the captured response
    is not JSON, replay its exact URL with the official ``format=json`` switch.
    ``response_url_predicate`` can disambiguate multiple calls to the same
    service; ``response_url_transform`` can adjust the captured request (for
    example, increasing an official page size) before the JSON replay.
    """

    def _run() -> dict[str, Any]:
        context = _ensure_session(resolve_browser_proxy(page_url))
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            def matches(response: Any) -> bool:
                response_url = _browser_response_url(response, "")
                if response_url_contains not in response_url:
                    return False
                if response_url_predicate is None:
                    return True
                try:
                    return bool(response_url_predicate(response_url))
                except Exception:
                    return False

            with domain_slot(page_url):
                with page.expect_response(
                    matches,
                    timeout=timeout_ms,
                ) as response_info:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                response = response_info.value
                content_type = str(_browser_response_headers(response).get("content-type") or "").lower()
                check_response_risk(
                    _browser_response_url(response, page_url),
                    status_code=_browser_response_status(response),
                    headers=_browser_response_headers(response),
                    body=_browser_response_text(response) if "json" in content_type else None,
                )
                if not _browser_response_ok(response):
                    raise RuntimeError(f"browser response HTTP {response.status}: {response.url}")
            if response_url_transform is not None or "json" not in content_type:
                response_url = _browser_response_url(response, page_url)
                if response_url_transform is not None:
                    response_url = response_url_transform(response_url)
                json_url = _with_query_value(response_url, "format", "json")
                with domain_slot(json_url):
                    response = context.request.get(json_url, timeout=timeout_ms)
                    check_response_risk(
                        json_url,
                        status_code=_browser_response_status(response),
                        headers=_browser_response_headers(response),
                        body=_browser_response_text(response),
                    )
                    if not _browser_response_ok(response):
                        raise RuntimeError(f"browser JSON response HTTP {response.status}: {response.url}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"browser response is not a JSON object: {response.url}")
            return payload
        finally:
            try:
                page.close()
            except Exception:
                pass

    return _run_browser_fetch(_run, page_url)


def fetch_json_via_browser(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
    """用单例浏览器上下文内的请求取 JSON（给 Steam 当前在线 API 用）。"""

    def _run() -> dict[str, Any]:
        context = _ensure_session(resolve_browser_proxy(url))
        context.set_default_timeout(timeout_ms)
        with domain_slot(url):
            response = context.request.get(url, timeout=timeout_ms)
            check_response_risk(
                url,
                status_code=_browser_response_status(response),
                headers=_browser_response_headers(response),
                body=_browser_response_text(response),
            )
            if not _browser_response_ok(response):
                raise RuntimeError(
                    f"browser response HTTP {_browser_response_status(response)}: "
                    f"{_browser_response_url(response, url)}"
                )
            return response.json()

    return _run_browser_fetch(_run, url)


def _browser_response_status(response: Any) -> int:
    value = getattr(response, "status", 200) if response is not None else 200
    try:
        return int(value)
    except (TypeError, ValueError):
        return 200


def _browser_response_ok(response: Any) -> bool:
    value = getattr(response, "ok", None) if response is not None else None
    if isinstance(value, bool):
        return value
    return 200 <= _browser_response_status(response) < 400


def _browser_response_headers(response: Any) -> dict[str, Any]:
    headers = getattr(response, "headers", None) if response is not None else None
    return headers if isinstance(headers, dict) else {}


def _browser_response_text(response: Any) -> str:
    value = getattr(response, "text", "") if response is not None else ""
    try:
        return str(value() if callable(value) else value or "")
    except Exception:
        return ""


def _browser_response_url(response: Any, fallback: str) -> str:
    value = getattr(response, "url", "") if response is not None else ""
    return str(value or fallback)


atexit.register(close_browser_session)
