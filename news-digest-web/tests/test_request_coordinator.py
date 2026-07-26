import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src import request_coordinator as coordinator_module
from src.request_coordinator import (
    coordinate_httpx_client,
    coordinate_requests_session,
    DomainCoolingDown,
    DomainCoordinator,
    DomainPolicy,
    PolicyStore,
)


class RequestCoordinatorTests(unittest.TestCase):
    def make_coordinator(
        self,
        policy: DomainPolicy,
        *,
        monotonic=None,
    ) -> DomainCoordinator:
        return DomainCoordinator(
            policy_resolver=lambda _hostname: policy,
            monotonic=monotonic,
            random_uniform=lambda _start, _end: 0.0,
        )

    def test_policy_store_falls_back_to_safe_values_for_invalid_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "crawl_policy.json"
            path.write_text(
                json.dumps(
                    {
                        "default": {
                            "maxConcurrency": 0,
                            "minIntervalSeconds": -3,
                            "retries": 99,
                        },
                        "domains": {
                            "api.example.com": {
                                "maxConcurrency": 2,
                                "minIntervalSeconds": 1.5,
                                "group": "example.com",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = PolicyStore(path)
            default_policy = store.for_hostname("other.example")
            domain_policy = store.for_hostname("api.example.com")

        self.assertEqual(default_policy.max_concurrency, 1)
        self.assertGreater(default_policy.min_interval_seconds, 0)
        self.assertLessEqual(default_policy.retries, 3)
        self.assertEqual(domain_policy.max_concurrency, 2)
        self.assertEqual(domain_policy.min_interval_seconds, 1.5)
        self.assertEqual(domain_policy.group, "example.com")

    def test_sync_slots_share_domain_and_limit_concurrency(self) -> None:
        coordinator = self.make_coordinator(
            DomainPolicy(max_concurrency=1, min_interval_seconds=0, jitter_seconds=0)
        )
        entered = threading.Event()
        release = threading.Event()

        def worker() -> None:
            with coordinator.slot("https://api.example.com/second"):
                entered.set()
                release.wait(timeout=1)

        with coordinator.slot("https://api.example.com/first"):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            self.assertFalse(entered.wait(timeout=0.05))

        self.assertTrue(entered.wait(timeout=1))
        release.set()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(coordinator.snapshot("https://api.example.com")["active"], 0)

    def test_minimum_start_interval_is_shared(self) -> None:
        now = [10.0]
        coordinator = self.make_coordinator(
            DomainPolicy(max_concurrency=1, min_interval_seconds=1.5, jitter_seconds=0),
            monotonic=lambda: now[0],
        )

        first, wait_seconds = coordinator.try_acquire("https://api.example.com/first")
        self.assertIsNotNone(first)
        self.assertEqual(wait_seconds, 0)
        first.close()

        second, wait_seconds = coordinator.try_acquire("https://api.example.com/second")
        self.assertIsNone(second)
        self.assertAlmostEqual(wait_seconds, 1.5)

        now[0] += 1.5
        second, wait_seconds = coordinator.try_acquire("https://api.example.com/second")
        self.assertIsNotNone(second)
        second.close()

    def test_retry_after_opens_domain_circuit_without_exposing_body(self) -> None:
        now = [20.0]
        coordinator = self.make_coordinator(
            DomainPolicy(
                min_interval_seconds=0,
                jitter_seconds=0,
                cooldown_seconds=30,
            ),
            monotonic=lambda: now[0],
        )

        with self.assertRaises(DomainCoolingDown) as raised:
            coordinator.check_response(
                "https://api.example.com/data",
                status_code=429,
                headers={"Retry-After": "7200"},
                body="secret response body",
            )

        self.assertNotIn("secret response body", str(raised.exception))
        self.assertGreaterEqual(raised.exception.retry_after_seconds, 7200)
        with self.assertRaises(DomainCoolingDown):
            coordinator.acquire("https://api.example.com/next")

        now[0] += 7200
        with coordinator.slot("https://api.example.com/next"):
            self.assertEqual(coordinator.snapshot("https://api.example.com")["active"], 1)

    def test_waf_body_opens_circuit_even_for_success_status(self) -> None:
        coordinator = self.make_coordinator(
            DomainPolicy(min_interval_seconds=0, jitter_seconds=0, cooldown_seconds=30)
        )

        with self.assertRaises(DomainCoolingDown):
            coordinator.check_response(
                "https://api.example.com/data",
                status_code=200,
                body="Aliyun WAF: please complete the sliding captcha",
            )

    def test_v122_business_json_mentioning_captcha_does_not_open_circuit(self) -> None:
        coordinator = self.make_coordinator(
            DomainPolicy(min_interval_seconds=0, jitter_seconds=0, cooldown_seconds=30)
        )

        coordinator.check_response(
            "https://api.github.com/search/repositories",
            status_code=200,
            headers={"Content-Type": "application/json"},
            body='{"description":"A library for solving CAPTCHA challenges"}',
        )

        with coordinator.slot("https://api.github.com/next"):
            self.assertEqual(coordinator.snapshot("https://api.github.com")["active"], 1)

    def test_v122_html_captcha_page_still_opens_circuit(self) -> None:
        coordinator = self.make_coordinator(
            DomainPolicy(min_interval_seconds=0, jitter_seconds=0, cooldown_seconds=30)
        )

        with self.assertRaises(DomainCoolingDown):
            coordinator.check_response(
                "https://api.example.com/data",
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                body="<html><title>CAPTCHA</title><body>Please continue</body></html>",
            )

    def test_sync_retry_is_bounded_and_does_not_retry_programming_errors(self) -> None:
        coordinator = self.make_coordinator(
            DomainPolicy(
                min_interval_seconds=0,
                jitter_seconds=0,
                retries=2,
                backoff_base_seconds=0.1,
            )
        )
        attempts = 0
        delays: list[float] = []

        def flaky_operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("temporary network failure")
            return "ok"

        result = coordinator.run_sync(
            "https://api.example.com/data",
            flaky_operation,
            retry_exceptions=(OSError,),
            sleep=delays.append,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 3)
        self.assertEqual(len(delays), 2)
        self.assertLess(delays[0], delays[1])

        programming_attempts = 0

        def programming_error() -> None:
            nonlocal programming_attempts
            programming_attempts += 1
            raise ValueError("bug")

        with self.assertRaises(ValueError):
            coordinator.run_sync(
                "https://other.example/data",
                programming_error,
                retry_exceptions=(OSError,),
                sleep=delays.append,
            )
        self.assertEqual(programming_attempts, 1)

    def test_requests_session_wrapper_routes_get_through_global_coordinator(self) -> None:
        class Response:
            status_code = 200
            headers = {}
            text = "ok"

        class Client:
            def request(self, method: str, url: str, **_kwargs):
                self.last_request = (method, url)
                return Response()

            def get(self, url: str, **kwargs):
                return self.request("GET", url, **kwargs)

        client = Client()

        def run(_url, operation, **_kwargs):
            return operation()

        with patch.object(
            coordinator_module.REQUEST_COORDINATOR,
            "run_sync",
            side_effect=run,
        ) as coordinated:
            coordinate_requests_session(client)
            response = client.get("https://api.example.com/data")

        self.assertEqual(response.text, "ok")
        self.assertEqual(client.last_request, ("GET", "https://api.example.com/data"))
        coordinated.assert_called_once()


class AsyncRequestCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_and_sync_slots_share_domain_state(self) -> None:
        policy = DomainPolicy(max_concurrency=1, min_interval_seconds=0, jitter_seconds=0)
        coordinator = DomainCoordinator(
            policy_resolver=lambda _hostname: policy,
            random_uniform=lambda _start, _end: 0.0,
        )
        sync_lease = coordinator.acquire("https://api.example.com/sync")
        entered = asyncio.Event()

        async def worker() -> None:
            async with coordinator.async_slot("https://api.example.com/async"):
                entered.set()

        task = asyncio.create_task(worker())
        await asyncio.sleep(0.05)
        self.assertFalse(entered.is_set())

        sync_lease.close()
        await asyncio.wait_for(task, timeout=1)
        self.assertTrue(entered.is_set())
        self.assertEqual(coordinator.snapshot("https://api.example.com")["active"], 0)

    async def test_async_cancellation_does_not_leak_an_active_slot(self) -> None:
        policy = DomainPolicy(max_concurrency=1, min_interval_seconds=0, jitter_seconds=0)
        coordinator = DomainCoordinator(
            policy_resolver=lambda _hostname: policy,
            random_uniform=lambda _start, _end: 0.0,
        )
        sync_lease = coordinator.acquire("https://api.example.com/sync")

        task = asyncio.create_task(coordinator.acquire_async("https://api.example.com/async"))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        sync_lease.close()
        self.assertEqual(coordinator.snapshot("https://api.example.com")["active"], 0)

    async def test_httpx_client_wrapper_routes_get_through_global_coordinator(self) -> None:
        class Response:
            status_code = 200
            headers = {}
            text = "ok"

        class Client:
            async def request(self, method: str, url: str, **_kwargs):
                self.last_request = (method, url)
                return Response()

            async def get(self, url: str, **kwargs):
                return await self.request("GET", url, **kwargs)

        async def run(_url, operation, **_kwargs):
            return await operation()

        client = Client()
        with patch.object(
            coordinator_module.REQUEST_COORDINATOR,
            "run_async",
            new=AsyncMock(side_effect=run),
        ) as coordinated:
            coordinate_httpx_client(client)
            response = await client.get("https://api.example.com/data")

        self.assertEqual(response.text, "ok")
        self.assertEqual(client.last_request, ("GET", "https://api.example.com/data"))
        coordinated.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
