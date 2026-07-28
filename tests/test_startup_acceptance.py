import copy
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src import app as app_module
from src import background_refresh


class StartupAcceptanceTests(unittest.TestCase):
    def test_service_startup_schedules_every_refresh_once_without_live_network(self) -> None:
        previous_state = copy.deepcopy(background_refresh.REFRESH_STATE)
        for state in background_refresh.REFRESH_STATE.values():
            state.update(
                {
                    "status": "idle",
                    "version": 0,
                    "runId": 0,
                    "startedAt": "",
                    "finishedAt": "",
                    "message": "",
                    "refreshed": False,
                }
            )

        async def completed_payload(kind: str, _reason: str, _force: bool) -> dict:
            return {
                "generatedAt": f"generated-{kind}",
                "cached": False,
                "stale": False,
                "throttled": False,
                "hasData": True,
            }

        execute = AsyncMock(side_effect=completed_payload)
        try:
            with (
                patch.object(app_module, "initialize_research_runtime", new=AsyncMock()),
                patch.object(background_refresh, "execute_refresh", new=execute),
                patch.object(background_refresh, "STARTUP_STAGGER_SECONDS", 0),
                TestClient(app_module.app) as client,
            ):
                deadline = time.monotonic() + 2
                status = client.get("/api/refresh-status").json()
                while any(item["status"] == "running" for item in status.values()):
                    if time.monotonic() >= deadline:
                        self.fail("startup refreshes did not finish within the isolated acceptance window")
                    time.sleep(0.01)
                    status = client.get("/api/refresh-status").json()
        finally:
            background_refresh.REFRESH_STATE.clear()
            background_refresh.REFRESH_STATE.update(previous_state)

        self.assertEqual(set(status), set(background_refresh.STARTUP_REFRESH_KINDS))
        self.assertEqual(execute.await_count, len(background_refresh.STARTUP_REFRESH_KINDS))
        self.assertEqual(
            {(call.args[0], call.args[1], call.args[2]) for call in execute.await_args_list},
            {(kind, "startup", True) for kind in background_refresh.STARTUP_REFRESH_KINDS},
        )
        for item in status.values():
            self.assertEqual(item["runId"], 1)
            self.assertEqual(item["status"], "done")
            self.assertEqual(item["version"], 1)


if __name__ == "__main__":
    unittest.main()
