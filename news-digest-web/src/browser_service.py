"""共享的「模拟浏览器抓取」模块。

项目里雪球（被封 IP 时）与游戏榜单都用 Playwright/Chromium 做浏览器模拟抓取。
此前两套实现各自重复了「注入运行库路径 / 异常中文化 / 启动持久化上下文」等样板。
本模块统一这些能力：

- ``apply_browser_library_path``：把 Chromium 运行库路径注入 ``LD_LIBRARY_PATH``。
- ``summarize_browser_error``：把常见 Playwright 异常转成中文可读信息。
- ``launch_browser_context``：上下文管理器，等价于 ``launch_persistent_context``（headless + 真实 UA/locale/时区）。
- ``fetch_html_via_browser`` / ``fetch_json_via_browser``：基于**进程级单例浏览器会话**取数，
  供游戏区域等高频抓取复用，避免每个请求都重启浏览器。
- ``close_browser_session``：关闭单例会话（已注册 atexit）。

浏览器模拟用于规避 Steam 等对裸 HTTP 的限流/封禁：真实 UA、中文 locale、上海时区、
持久化 profile，使其看起来更像正常用户浏览器。
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

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
_PLAYWRIGHT = None
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
def _safe_reset_session() -> None:
    global _PLAYWRIGHT, _CONTEXT, _CONTEXT_PROXY_KEY
    ctx, pw = _CONTEXT, _PLAYWRIGHT
    _CONTEXT, _PLAYWRIGHT = None, None
    _CONTEXT_PROXY_KEY = None
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass


def _ensure_session(proxy: dict[str, str] | None = None) -> Any:
    """在调用方已持有 _BROWSER_LOCK 时调用。返回单例持久化上下文。"""
    global _PLAYWRIGHT, _CONTEXT, _CONTEXT_PROXY_KEY
    proxy_key = _proxy_key(proxy)
    if _CONTEXT is not None and _CONTEXT_PROXY_KEY == proxy_key:
        return _CONTEXT
    if _CONTEXT is not None:
        _safe_reset_session()
    apply_browser_library_path()
    from playwright.sync_api import sync_playwright

    settings = _settings()
    profile_dir = _resolve_profile_path(settings.get("profileDir") or "data/browser-profile")
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    launch_options: dict[str, Any] = {
        "headless": bool(settings.get("headless", True)),
        "channel": settings.get("channel", "chromium"),
        "viewport": settings.get("viewport") or DEFAULT_VIEWPORT,
        "locale": settings.get("locale", "zh-CN"),
        "timezone_id": settings.get("timezoneId", "Asia/Shanghai"),
        "user_agent": settings.get("userAgent", DEFAULT_BROWSER_UA),
        "args": settings.get("args") or DEFAULT_BROWSER_ARGS,
    }
    executable = str(settings.get("executable") or "").strip()
    if executable:
        launch_options["executable_path"] = executable
    if proxy:
        launch_options["proxy"] = proxy
    try:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_options)
    except Exception:
        playwright.stop()
        raise
    context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    _PLAYWRIGHT = playwright
    _CONTEXT = context
    _CONTEXT_PROXY_KEY = proxy_key
    return context


def close_browser_session() -> None:
    with _BROWSER_LOCK:
        _safe_reset_session()


def _run_browser_fetch(fetch_fn: Any, retries: int = 2) -> Any:
    first_error: Exception | None = None
    for attempt in range(retries + 1):
        with _BROWSER_LOCK:
            try:
                return fetch_fn()
            except Exception as error:  # noqa: BLE001 - 由调用方决定如何呈现
                if first_error is None:
                    first_error = error
                _safe_reset_session()
        if attempt >= retries:
            break
    raise first_error if first_error else RuntimeError("browser fetch failed")


def fetch_html_via_browser(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """用单例浏览器打开页面并返回渲染后的 HTML（给 Steam 热销榜 / SteamCharts 用）。"""

    def _run() -> str:
        context = _ensure_session(resolve_browser_proxy(url))
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            wait_ms = max(0, int(_settings().get("waitMs") or 0))
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            try:
                page.close()
            except Exception:
                pass

    return _run_browser_fetch(_run)


def fetch_page_json_response_via_browser(
    page_url: str,
    response_url_contains: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Open a page and return the JSON response matching ``response_url_contains``."""

    def _run() -> dict[str, Any]:
        context = _ensure_session(resolve_browser_proxy(page_url))
        context.set_default_timeout(timeout_ms)
        page = context.new_page()
        try:
            with page.expect_response(
                lambda response: response_url_contains in response.url,
                timeout=timeout_ms,
            ) as response_info:
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
            response = response_info.value
            if not response.ok:
                raise RuntimeError(f"browser response HTTP {response.status}: {response.url}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"browser response is not a JSON object: {response.url}")
            return payload
        finally:
            try:
                page.close()
            except Exception:
                pass

    return _run_browser_fetch(_run)


def fetch_json_via_browser(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
    """用单例浏览器上下文内的请求取 JSON（给 Steam 当前在线 API 用）。"""

    def _run() -> dict[str, Any]:
        context = _ensure_session(resolve_browser_proxy(url))
        context.set_default_timeout(timeout_ms)
        response = context.request.get(url, timeout=timeout_ms)
        return response.json()

    return _run_browser_fetch(_run)


atexit.register(close_browser_session)
