import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.ai_discovery import (
    apply_project_history,
    build_project_signals,
    extract_readme_signals,
    select_enrichment_candidates,
)
from src.ai_service import (
    fetch_github_project_enrichment,
    load_ai_project_history_sync,
    record_ai_project_history_sync,
)


class AiProjectHistoryTests(unittest.TestCase):
    def test_daily_history_computes_real_deltas_and_prunes_retention(self) -> None:
        now = datetime(2026, 7, 26, 8, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ai.sqlite"
            record_ai_project_history_sync(
                db_path,
                [{"id": 1, "fullName": "demo/tool", "stars": 100, "forks": 10}],
                observed_at=now - timedelta(days=31),
            )
            record_ai_project_history_sync(
                db_path,
                [{"id": 1, "fullName": "demo/tool", "stars": 130, "forks": 12}],
                observed_at=now - timedelta(days=8),
            )
            record_ai_project_history_sync(
                db_path,
                [
                    {"id": 1, "fullName": "demo/tool", "stars": 160, "forks": 15},
                    {"id": 2, "fullName": "demo/new", "stars": 20, "forks": 1},
                ],
                observed_at=now,
            )
            record_ai_project_history_sync(
                db_path,
                [{"id": 3, "fullName": "demo/retention", "stars": 1, "forks": 0}],
                observed_at=now - timedelta(days=130),
            )
            record_ai_project_history_sync(db_path, [], observed_at=now)

            history = load_ai_project_history_sync(db_path, ["id:1", "id:2"], now=now)
            tool = apply_project_history({"id": 1, "stars": 160}, history["id:1"], now=now)
            new = apply_project_history({"id": 2, "stars": 20}, history["id:2"], now=now)

            self.assertEqual(tool["stars7dDelta"], 30)
            self.assertEqual(tool["stars30dDelta"], 60)
            self.assertEqual(tool["historyStatus"], "ready")
            self.assertIsNone(new["stars7dDelta"])
            self.assertEqual(new["historyStatus"], "collecting")
            with sqlite3.connect(db_path) as connection:
                retained = connection.execute(
                    "SELECT COUNT(*) FROM ai_project_history WHERE project_key = ?",
                    ("id:3",),
                ).fetchone()[0]
            self.assertEqual(retained, 0)

    def test_readme_signals_are_compact_booleans_not_readme_content(self) -> None:
        signals = extract_readme_signals(
            """
            # Useful AI Tool
            ## Installation
            Run `pip install useful-ai`.
            ## Quick start
            Try the example in five minutes.
            [Live demo](https://demo.example.test)
            """
        )

        self.assertEqual(
            signals,
            {"hasInstall": True, "hasQuickstart": True, "hasDemo": True},
        )

    def test_enrichment_budget_is_bounded_by_authentication(self) -> None:
        projects = [
            {
                "id": index,
                "fullName": f"demo/tool-{index}",
                "useStage": "ready" if index % 2 else "build",
                "defaultVisible": bool(index % 2),
                "discoveryScore": 100 - index / 10,
                "discoveryModes": ["recent"] if index % 5 == 0 else ["popular"],
            }
            for index in range(100)
        ]

        anonymous = select_enrichment_candidates(projects, authenticated=False)
        authenticated = select_enrichment_candidates(projects, authenticated=True)

        self.assertLessEqual(len(anonymous), 12)
        self.assertLessEqual(len(authenticated), 40)
        self.assertEqual(len({project["id"] for project in anonymous}), len(anonymous))
        self.assertTrue(all(project["fullName"] for project in authenticated))

    def test_high_signals_require_usable_stage_and_stable_event_ids(self) -> None:
        now = datetime(2026, 7, 26, tzinfo=UTC)
        usable = {
            "id": 1,
            "fullName": "demo/useful",
            "useStage": "ready",
            "stars": 2_000,
            "stars7dDelta": 300,
            "stars30dDelta": 500,
            "historyStatus": "ready",
            "createdAt": "2026-07-20T00:00:00Z",
            "release": {
                "tag": "v1.2.0",
                "url": "https://github.com/demo/useful/releases/tag/v1.2.0",
                "publishedAt": "2026-07-25T00:00:00Z",
                "prerelease": False,
                "draft": False,
            },
        }
        framework = {**usable, "id": 2, "fullName": "demo/framework", "useStage": "build"}

        first = build_project_signals(usable, now=now)
        second = build_project_signals(usable, now=now)
        hidden = build_project_signals(framework, now=now)

        self.assertTrue(first["high"])
        self.assertEqual(first["high"], second["high"])
        self.assertTrue(all(signal["eventId"] for signal in first["high"]))
        self.assertFalse(hidden["high"])
        self.assertTrue(hidden["digest"])


class AiProjectEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_enrichment_failure_keeps_last_known_good_metadata(self) -> None:
        class FailingClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            async def get(self, url: str):
                self.urls.append(url)
                raise RuntimeError("offline")

        client = FailingClient()
        previous = {
            "release": {"tag": "v1.0.0", "publishedAt": "2026-07-20T00:00:00Z"},
            "readmeSignals": {"hasInstall": True, "hasQuickstart": True, "hasDemo": False},
        }

        project_key, enrichment, errors = await fetch_github_project_enrichment(
            client,
            {"id": 7, "fullName": "demo/useful"},
            previous,
        )

        self.assertEqual(project_key, "id:7")
        self.assertEqual(enrichment["release"], previous["release"])
        self.assertEqual(enrichment["readmeSignals"], previous["readmeSignals"])
        self.assertEqual(enrichment["enrichmentStatus"], "stale")
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
