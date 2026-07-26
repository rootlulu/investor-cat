from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.local_access import WRITE_TOKEN_ENV, LocalWriteGuardMiddleware, is_request_loopback, is_write_authorized


def test_loopback_write_is_allowed_without_token() -> None:
    assert is_write_authorized("127.0.0.1", "", "", "")
    assert is_write_authorized("::1", "", "", "")
    assert is_write_authorized("::ffff:127.0.0.1", "", "", "")


def test_remote_peer_cannot_spoof_loopback_with_forwarded_header() -> None:
    assert not is_request_loopback("192.0.2.10", "127.0.0.1")
    assert not is_write_authorized("192.0.2.10", "127.0.0.1", "", "")


def test_loopback_proxy_uses_last_forwarded_hop() -> None:
    assert not is_request_loopback("127.0.0.1", "127.0.0.1, 192.0.2.25")
    assert is_request_loopback("127.0.0.1", "192.0.2.25, 127.0.0.1")


def test_remote_write_requires_matching_configured_token() -> None:
    assert not is_write_authorized("192.0.2.10", "", "", "")
    assert not is_write_authorized("192.0.2.10", "", "secret", "wrong")
    assert is_write_authorized("192.0.2.10", "", "secret", "secret")


def test_malformed_client_address_is_not_treated_as_local() -> None:
    assert not is_request_loopback("not-an-ip", "")


def test_application_installs_write_guard() -> None:
    from src.app import app

    assert any(middleware.cls is LocalWriteGuardMiddleware for middleware in app.user_middleware)


def test_middleware_keeps_remote_reads_open_but_blocks_unauthorized_writes(monkeypatch) -> None:
    monkeypatch.delenv(WRITE_TOKEN_ENV, raising=False)
    app = _guarded_test_app()
    client = TestClient(app, client=("192.0.2.10", 50000))

    assert client.get("/api/value").status_code == 200
    response = client.post("/api/value")
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_middleware_accepts_remote_write_with_server_configured_token(monkeypatch) -> None:
    monkeypatch.setenv(WRITE_TOKEN_ENV, "correct-secret")
    app = _guarded_test_app()
    client = TestClient(app, client=("192.0.2.10", 50000))

    denied = client.post("/api/value", headers={"X-News-Digest-Write-Token": "wrong"})
    allowed = client.post("/api/value", headers={"X-News-Digest-Write-Token": "correct-secret"})

    assert denied.status_code == 403
    assert allowed.status_code == 200


def _guarded_test_app() -> FastAPI:
    guarded = FastAPI()
    guarded.add_middleware(LocalWriteGuardMiddleware)

    @guarded.get("/api/value")
    async def read_value() -> dict[str, bool]:
        return {"ok": True}

    @guarded.post("/api/value")
    async def write_value() -> dict[str, bool]:
        return {"ok": True}

    return guarded
