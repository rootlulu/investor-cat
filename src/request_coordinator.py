from __future__ import annotations

import asyncio
import json
import math
import random
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterator, Mapping, TypeVar
from urllib.parse import urlsplit


CRAWL_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "crawl_policy.json"

_RISK_MARKERS = (
    "aliyun waf",
    "cloudflare ray id",
    "please verify you are human",
    "security verification",
    "sliding verification",
    "访问验证",
    "安全验证",
    "异常访问",
    "请输入验证码",
    "滑块验证",
    "请求过于频繁",
)
_CONTEXTUAL_RISK_MARKERS = ("captcha", "too many requests")

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DomainPolicy:
    max_concurrency: int = 1
    min_interval_seconds: float = 0.75
    jitter_seconds: float = 0.25
    retries: int = 1
    backoff_base_seconds: float = 0.75
    cooldown_seconds: float = 300.0
    group: str = ""


SAFE_DEFAULT_POLICY = DomainPolicy()


class DomainCoolingDown(RuntimeError):
    def __init__(self, hostname: str, retry_after_seconds: float, reason: str) -> None:
        self.hostname = hostname
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        self.reason = reason
        super().__init__(
            f"requests for {hostname} are cooling down for "
            f"{self.retry_after_seconds:.1f}s ({reason})"
        )


class PolicyStore:
    def __init__(self, path: Path = CRAWL_POLICY_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._default = SAFE_DEFAULT_POLICY
        self._domains: dict[str, DomainPolicy] = {}

    def for_hostname(self, hostname: str) -> DomainPolicy:
        self._reload_if_needed()
        normalized = _normalize_hostname(hostname)
        with self._lock:
            exact = self._domains.get(normalized)
            if exact is not None:
                return exact
            wildcard_matches = (
                (pattern, policy)
                for pattern, policy in self._domains.items()
                if pattern.startswith("*.")
                and (normalized == pattern[2:] or normalized.endswith(pattern[1:]))
            )
            match = max(wildcard_matches, key=lambda item: len(item[0]), default=None)
            return match[1] if match else self._default

    def _reload_if_needed(self) -> None:
        try:
            stat = self.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = (-1, -1)

        with self._lock:
            if stamp == self._stamp:
                return
            default_policy = SAFE_DEFAULT_POLICY
            domains: dict[str, DomainPolicy] = {}
            if stamp != (-1, -1):
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        default_policy = _parse_policy(raw.get("default"), SAFE_DEFAULT_POLICY)
                        raw_domains = raw.get("domains")
                        if isinstance(raw_domains, dict):
                            for pattern, values in raw_domains.items():
                                normalized_pattern = _normalize_pattern(pattern)
                                if normalized_pattern:
                                    domains[normalized_pattern] = _parse_policy(
                                        values,
                                        default_policy,
                                    )
                except (OSError, UnicodeError, json.JSONDecodeError):
                    default_policy = SAFE_DEFAULT_POLICY
                    domains = {}
            self._default = default_policy
            self._domains = domains
            self._stamp = stamp


@dataclass(slots=True)
class _DomainState:
    active: int = 0
    next_start_at: float = 0.0
    cooldown_until: float = 0.0
    cooldown_reason: str = ""


class DomainLease:
    def __init__(self, coordinator: DomainCoordinator, key: str) -> None:
        self._coordinator = coordinator
        self._key = key
        self._closed = False
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._coordinator._release(self._key)

    def __enter__(self) -> DomainLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class DomainCoordinator:
    def __init__(
        self,
        policy_resolver: Callable[[str], DomainPolicy] | None = None,
        *,
        monotonic: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        random_uniform: Callable[[float, float], float] | None = None,
    ) -> None:
        store = PolicyStore()
        self._policy_resolver = policy_resolver or store.for_hostname
        self._monotonic = monotonic or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._random_uniform = random_uniform or random.uniform
        self._condition = threading.Condition()
        self._states: dict[str, _DomainState] = {}

    def try_acquire(self, url: str) -> tuple[DomainLease | None, float]:
        hostname, policy, key = self._resolve(url)
        with self._condition:
            now = self._monotonic()
            state = self._states.setdefault(key, _DomainState())
            remaining_cooldown = state.cooldown_until - now
            if remaining_cooldown > 0:
                raise DomainCoolingDown(
                    hostname,
                    remaining_cooldown,
                    state.cooldown_reason or "risk response",
                )
            if state.cooldown_until:
                state.cooldown_until = 0.0
                state.cooldown_reason = ""

            interval_wait = max(0.0, state.next_start_at - now)
            if state.active >= policy.max_concurrency:
                return None, max(0.01, min(interval_wait or 0.05, 0.25))
            if interval_wait > 0:
                return None, interval_wait

            state.active += 1
            jitter = (
                self._random_uniform(0.0, policy.jitter_seconds)
                if policy.jitter_seconds > 0
                else 0.0
            )
            state.next_start_at = now + policy.min_interval_seconds + max(0.0, jitter)
            return DomainLease(self, key), 0.0

    def acquire(self, url: str) -> DomainLease:
        while True:
            lease, wait_seconds = self.try_acquire(url)
            if lease is not None:
                return lease
            with self._condition:
                self._condition.wait(timeout=max(0.01, min(wait_seconds, 0.25)))

    async def acquire_async(self, url: str) -> DomainLease:
        while True:
            lease, wait_seconds = self.try_acquire(url)
            if lease is not None:
                return lease
            await asyncio.sleep(max(0.01, min(wait_seconds, 0.1)))

    @contextmanager
    def slot(self, url: str) -> Iterator[DomainLease]:
        lease = self.acquire(url)
        try:
            yield lease
        finally:
            lease.close()

    @asynccontextmanager
    async def async_slot(self, url: str) -> AsyncIterator[DomainLease]:
        lease = await self.acquire_async(url)
        try:
            yield lease
        finally:
            lease.close()

    def check_response(
        self,
        url: str,
        *,
        status_code: int | None,
        headers: Mapping[str, Any] | None = None,
        body: str | None = None,
    ) -> None:
        risk_reason = ""
        if status_code in {403, 429}:
            risk_reason = f"HTTP {status_code}"
        elif _contains_risk_marker(body, headers=headers):
            risk_reason = "risk verification page"
        if not risk_reason:
            return

        retry_after = _parse_retry_after(
            _header_value(headers, "Retry-After"),
            now_epoch=self._wall_clock(),
        )
        raise self.open_circuit(url, retry_after_seconds=retry_after, reason=risk_reason)

    def open_circuit(
        self,
        url: str,
        *,
        retry_after_seconds: float | None = None,
        reason: str = "risk response",
    ) -> DomainCoolingDown:
        hostname, policy, key = self._resolve(url)
        bounded_retry_after = 0.0
        if (
            retry_after_seconds is not None
            and math.isfinite(retry_after_seconds)
            and retry_after_seconds >= 0
        ):
            bounded_retry_after = retry_after_seconds
        cooldown = max(policy.cooldown_seconds, bounded_retry_after)
        with self._condition:
            now = self._monotonic()
            state = self._states.setdefault(key, _DomainState())
            state.cooldown_until = max(state.cooldown_until, now + cooldown)
            state.cooldown_reason = reason
            remaining = state.cooldown_until - now
            self._condition.notify_all()
        return DomainCoolingDown(hostname, remaining, reason)

    def retry_delay(self, url: str, attempt: int) -> float:
        hostname = _hostname_from_url(url)
        policy = _sanitize_policy(self._policy_resolver(hostname))
        base = policy.backoff_base_seconds * (2 ** max(0, attempt))
        jitter_limit = min(policy.jitter_seconds, base * 0.25)
        jitter = self._random_uniform(0.0, jitter_limit) if jitter_limit > 0 else 0.0
        return base + max(0.0, jitter)

    def run_sync(
        self,
        url: str,
        operation: Callable[[], T],
        *,
        retry_exceptions: tuple[type[BaseException], ...],
        sleep: Callable[[float], None] = time.sleep,
        body_getter: Callable[[T], str | None] | None = None,
    ) -> T:
        policy = _sanitize_policy(self._policy_resolver(_hostname_from_url(url)))
        attempt = 0
        while True:
            try:
                with self.slot(url):
                    result = operation()
                status_code = _response_status(result)
                self.check_response(
                    url,
                    status_code=status_code,
                    headers=_response_headers(result),
                    body=body_getter(result) if body_getter else None,
                )
                if status_code is not None and 500 <= status_code < 600 and attempt < policy.retries:
                    sleep(self.retry_delay(url, attempt))
                    attempt += 1
                    continue
                return result
            except DomainCoolingDown:
                raise
            except retry_exceptions:
                if attempt >= policy.retries:
                    raise
                sleep(self.retry_delay(url, attempt))
                attempt += 1

    def run_sync_once(
        self,
        url: str,
        operation: Callable[[], T],
        *,
        body_getter: Callable[[T], str | None] | None = None,
    ) -> T:
        with self.slot(url):
            result = operation()
        self.check_response(
            url,
            status_code=_response_status(result),
            headers=_response_headers(result),
            body=body_getter(result) if body_getter else None,
        )
        return result

    async def run_async(
        self,
        url: str,
        operation: Callable[[], Any],
        *,
        retry_exceptions: tuple[type[BaseException], ...],
        sleep: Callable[[float], Any] = asyncio.sleep,
        body_getter: Callable[[T], str | None] | None = None,
    ) -> T:
        policy = _sanitize_policy(self._policy_resolver(_hostname_from_url(url)))
        attempt = 0
        while True:
            try:
                async with self.async_slot(url):
                    result = await operation()
                status_code = _response_status(result)
                self.check_response(
                    url,
                    status_code=status_code,
                    headers=_response_headers(result),
                    body=body_getter(result) if body_getter else None,
                )
                if status_code is not None and 500 <= status_code < 600 and attempt < policy.retries:
                    await sleep(self.retry_delay(url, attempt))
                    attempt += 1
                    continue
                return result
            except DomainCoolingDown:
                raise
            except retry_exceptions:
                if attempt >= policy.retries:
                    raise
                await sleep(self.retry_delay(url, attempt))
                attempt += 1

    async def run_async_once(
        self,
        url: str,
        operation: Callable[[], Any],
        *,
        body_getter: Callable[[T], str | None] | None = None,
    ) -> T:
        async with self.async_slot(url):
            result = await operation()
        self.check_response(
            url,
            status_code=_response_status(result),
            headers=_response_headers(result),
            body=body_getter(result) if body_getter else None,
        )
        return result

    def snapshot(self, url: str) -> dict[str, Any]:
        hostname, policy, key = self._resolve(url)
        with self._condition:
            state = self._states.setdefault(key, _DomainState())
            now = self._monotonic()
            return {
                "hostname": hostname,
                "group": key,
                "active": state.active,
                "maxConcurrency": policy.max_concurrency,
                "nextStartInSeconds": max(0.0, state.next_start_at - now),
                "cooldownRemainingSeconds": max(0.0, state.cooldown_until - now),
                "cooldownReason": state.cooldown_reason,
            }

    def _resolve(self, url: str) -> tuple[str, DomainPolicy, str]:
        hostname = _hostname_from_url(url)
        policy = _sanitize_policy(self._policy_resolver(hostname))
        key = _normalize_hostname(policy.group) if policy.group else hostname
        return hostname, policy, key

    def _release(self, key: str) -> None:
        with self._condition:
            state = self._states.get(key)
            if state is None or state.active <= 0:
                return
            state.active -= 1
            self._condition.notify_all()


def _sanitize_policy(policy: DomainPolicy) -> DomainPolicy:
    return DomainPolicy(
        max_concurrency=_bounded_int(policy.max_concurrency, 1, 1, 4),
        min_interval_seconds=_bounded_float(policy.min_interval_seconds, 0.75, 0.0, 60.0),
        jitter_seconds=_bounded_float(policy.jitter_seconds, 0.25, 0.0, 30.0),
        retries=_bounded_int(policy.retries, 1, 0, 3),
        backoff_base_seconds=_bounded_float(policy.backoff_base_seconds, 0.75, 0.05, 60.0),
        cooldown_seconds=_bounded_float(policy.cooldown_seconds, 300.0, 1.0, 86_400.0),
        group=_normalize_hostname(policy.group) if policy.group else "",
    )


def _parse_policy(raw: object, base: DomainPolicy) -> DomainPolicy:
    values = raw if isinstance(raw, dict) else {}
    return DomainPolicy(
        max_concurrency=_bounded_int(values.get("maxConcurrency"), base.max_concurrency, 1, 4),
        min_interval_seconds=_bounded_float(
            values.get("minIntervalSeconds"),
            base.min_interval_seconds,
            0.0,
            60.0,
        ),
        jitter_seconds=_bounded_float(
            values.get("jitterSeconds"),
            base.jitter_seconds,
            0.0,
            30.0,
        ),
        retries=_bounded_int(values.get("retries"), base.retries, 0, 3),
        backoff_base_seconds=_bounded_float(
            values.get("backoffBaseSeconds"),
            base.backoff_base_seconds,
            0.05,
            60.0,
        ),
        cooldown_seconds=_bounded_float(
            values.get("cooldownSeconds"),
            base.cooldown_seconds,
            1.0,
            86_400.0,
        ),
        group=(
            _normalize_hostname(values.get("group"))
            if isinstance(values.get("group"), str) and values.get("group").strip()
            else base.group
        ),
    )


def _bounded_int(value: object, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value if minimum <= value <= maximum else fallback


def _bounded_float(value: object, fallback: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    parsed = float(value)
    return parsed if minimum <= parsed <= maximum else fallback


def _normalize_pattern(value: object) -> str:
    if not isinstance(value, str):
        return ""
    pattern = value.strip().lower().rstrip(".")
    if pattern.startswith("*."):
        suffix = _normalize_hostname(pattern[2:])
        return f"*.{suffix}" if suffix else ""
    return _normalize_hostname(pattern)


def _normalize_hostname(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().strip(".")


def _hostname_from_url(url: str) -> str:
    value = str(url).strip()
    parsed = urlsplit(value if "://" in value else f"//{value}")
    hostname = _normalize_hostname(parsed.hostname)
    if not hostname:
        raise ValueError("request URL must contain a hostname")
    return hostname


def _header_value(headers: Mapping[str, Any] | None, name: str) -> str:
    if not headers:
        return ""
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value).strip()
    return ""


def _parse_retry_after(value: str, *, now_epoch: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, parsed.timestamp() - now_epoch)
    except (TypeError, ValueError, OverflowError):
        return None


def _contains_risk_marker(
    body: str | None,
    *,
    headers: Mapping[str, Any] | None = None,
) -> bool:
    if not body:
        return False
    sample = body[:8192].lower()
    if any(marker in sample for marker in _RISK_MARKERS):
        return True
    if not any(marker in sample for marker in _CONTEXTUAL_RISK_MARKERS):
        return False
    content_type = str(_header_value(headers, "Content-Type") or "").lower()
    prefix = sample.lstrip()[:256]
    return "html" in content_type or prefix.startswith("<!doctype html") or "<html" in prefix


def _response_status(response: object) -> int | None:
    for attribute in ("status_code", "status"):
        value = getattr(response, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _response_headers(response: object) -> Mapping[str, Any] | None:
    headers = getattr(response, "headers", None)
    return headers if isinstance(headers, Mapping) else None


POLICY_STORE = PolicyStore()
REQUEST_COORDINATOR = DomainCoordinator(policy_resolver=POLICY_STORE.for_hostname)


@contextmanager
def domain_slot(url: str) -> Iterator[DomainLease]:
    with REQUEST_COORDINATOR.slot(url) as lease:
        yield lease


@asynccontextmanager
async def async_domain_slot(url: str) -> AsyncIterator[DomainLease]:
    async with REQUEST_COORDINATOR.async_slot(url) as lease:
        yield lease


def check_response_risk(
    url: str,
    *,
    status_code: int | None,
    headers: Mapping[str, Any] | None = None,
    body: str | None = None,
) -> None:
    REQUEST_COORDINATOR.check_response(
        url,
        status_code=status_code,
        headers=headers,
        body=body,
    )


def coordinated_requests_request(
    client: Any,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    import requests

    return REQUEST_COORDINATOR.run_sync(
        url,
        lambda: client.request(method, url, **kwargs),
        retry_exceptions=(requests.RequestException,),
        body_getter=lambda response: response.text,
    )


def coordinated_requests_request_once(
    client: Any,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    return REQUEST_COORDINATOR.run_sync_once(
        url,
        lambda: client.request(method, url, **kwargs),
        body_getter=lambda response: response.text,
    )


async def coordinated_httpx_request(
    client: Any,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    import httpx

    return await REQUEST_COORDINATOR.run_async(
        url,
        lambda: client.request(method, url, **kwargs),
        retry_exceptions=(httpx.RequestError,),
        body_getter=lambda response: response.text,
    )


async def coordinated_httpx_request_once(
    client: Any,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    return await REQUEST_COORDINATOR.run_async_once(
        url,
        lambda: client.request(method, url, **kwargs),
        body_getter=lambda response: response.text,
    )


def coordinate_requests_session(client: Any, *, retries: bool = True) -> Any:
    if getattr(client, "_domain_coordinator_wrapped", False):
        return client
    original_request = client.request

    def coordinated_request(method: str, url: str, **kwargs: Any) -> Any:
        operation = lambda: original_request(method, url, **kwargs)
        if retries:
            import requests

            return REQUEST_COORDINATOR.run_sync(
                url,
                operation,
                retry_exceptions=(requests.RequestException,),
                body_getter=lambda response: response.text,
            )
        return REQUEST_COORDINATOR.run_sync_once(
            url,
            operation,
            body_getter=lambda response: response.text,
        )

    client.request = coordinated_request
    client._domain_coordinator_wrapped = True
    return client


def coordinate_httpx_client(client: Any, *, retries: bool = True) -> Any:
    if getattr(client, "_domain_coordinator_wrapped", False):
        return client
    original_request = client.request

    async def coordinated_request(method: str, url: str, **kwargs: Any) -> Any:
        operation = lambda: original_request(method, url, **kwargs)
        if retries:
            import httpx

            return await REQUEST_COORDINATOR.run_async(
                url,
                operation,
                retry_exceptions=(httpx.RequestError,),
                body_getter=lambda response: response.text,
            )
        return await REQUEST_COORDINATOR.run_async_once(
            url,
            operation,
            body_getter=lambda response: response.text,
        )

    client.request = coordinated_request
    client._domain_coordinator_wrapped = True
    return client
