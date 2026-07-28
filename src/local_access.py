from __future__ import annotations

import hmac
import os
from ipaddress import IPv4Address, IPv6Address, ip_address

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
WRITE_TOKEN_ENV = "NEWS_DIGEST_WRITE_TOKEN"
WRITE_TOKEN_HEADER = "X-News-Digest-Write-Token"


def is_request_loopback(peer_host: str, forwarded_for: str = "") -> bool:
    if not _is_loopback_address(peer_host):
        return False
    forwarded_hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    if not forwarded_hops:
        return True
    # The only trusted proxy is the loopback Vite process. With `xfwd: true`,
    # it appends the address it observed, so the final hop cannot be replaced
    # by a header supplied by a remote browser.
    return _is_loopback_address(forwarded_hops[-1])


def is_write_authorized(
    peer_host: str,
    forwarded_for: str,
    configured_token: str,
    presented_token: str,
) -> bool:
    if is_request_loopback(peer_host, forwarded_for):
        return True
    return bool(
        configured_token
        and presented_token
        and hmac.compare_digest(configured_token, presented_token)
    )


class LocalWriteGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method.upper() not in WRITE_METHODS:
            return await call_next(request)

        peer_host = request.client.host if request.client else ""
        forwarded_for = request.headers.get("x-forwarded-for", "")
        configured_token = os.environ.get(WRITE_TOKEN_ENV, "")
        presented_token = request.headers.get(WRITE_TOKEN_HEADER, "")
        if is_write_authorized(peer_host, forwarded_for, configured_token, presented_token):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "远程写操作默认关闭；请在服务端配置 NEWS_DIGEST_WRITE_TOKEN，"
                    "并通过 X-News-Digest-Write-Token 请求头授权"
                )
            },
            headers={"Cache-Control": "no-store"},
        )


def _is_loopback_address(value: str) -> bool:
    candidate = str(value or "").strip().strip("[]")
    if not candidate:
        return False
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        address: IPv4Address | IPv6Address = ip_address(candidate)
    except ValueError:
        return False
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback
