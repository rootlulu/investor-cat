import unittest
from datetime import UTC, datetime

from src.ai_discovery import (
    build_github_search_specs,
    classify_ai_project,
    enrich_discovery_score,
    project_is_default_visible,
)
from src.ai_service import AI_PROJECTS_SCHEMA_VERSION, migrate_ai_projects_snapshot


class AiDiscoveryClassificationTests(unittest.TestCase):
    def test_use_stage_goldens_separate_tools_extensions_frameworks_and_resources(self) -> None:
        cases = [
            (
                {
                    "fullName": "openai/codex",
                    "description": "A coding agent that runs in your terminal",
                    "topics": ["coding-agent", "cli"],
                },
                "ready",
                "programming",
                "cli",
            ),
            (
                {
                    "fullName": "anthropics/skills",
                    "description": "Reusable Agent Skills for Claude Code",
                    "topics": ["agent-skills"],
                },
                "integrate",
                "agent_extensions",
                "skill",
            ),
            (
                {
                    "fullName": "modelcontextprotocol/python-sdk",
                    "description": "The official Python SDK for Model Context Protocol",
                    "topics": ["mcp", "sdk"],
                },
                "build",
                "agent_extensions",
                "sdk",
            ),
            (
                {
                    "fullName": "tensorflow/tensorflow",
                    "description": "An end-to-end machine learning framework for training neural networks",
                    "topics": ["machine-learning-framework", "deep-learning", "tensor"],
                },
                "train_research",
                "programming",
                "library",
            ),
            (
                {
                    "fullName": "microsoft/ai-agents-for-beginners",
                    "description": "A course with lessons and tutorials for learning AI agents",
                    "topics": ["tutorial", "course"],
                },
                "resource",
                "programming",
                "resource",
            ),
        ]

        for project, stage, capability, surface in cases:
            with self.subTest(project=project["fullName"]):
                result = classify_ai_project(project)
                self.assertEqual(result["useStage"], stage)
                self.assertIn(capability, result["capabilityTags"])
                self.assertIn(surface, result["deliverySurfaces"])
                self.assertTrue(result["classificationReasons"])
                self.assertGreaterEqual(result["classificationConfidence"], 0.6)

    def test_mcp_and_skill_are_surfaces_not_primary_use_stage(self) -> None:
        gemini = classify_ai_project(
            {
                "fullName": "google-gemini/gemini-cli",
                "description": "An open-source AI agent that brings Gemini to your terminal and supports MCP",
                "topics": ["coding-agent", "cli", "mcp"],
            }
        )
        server = classify_ai_project(
            {
                "fullName": "demo/calendar-mcp",
                "description": "Installable MCP server for managing your calendar",
                "topics": ["mcp-server"],
            }
        )

        self.assertEqual(gemini["useStage"], "ready")
        self.assertIn("cli", gemini["deliverySurfaces"])
        self.assertIn("mcp_server", gemini["deliverySurfaces"])
        self.assertEqual(server["useStage"], "integrate")
        self.assertIn("mcp_server", server["deliverySurfaces"])

    def test_search_provenance_never_becomes_classification_fallback(self) -> None:
        result = classify_ai_project(
            {
                "fullName": "example/plain-observability",
                "description": "General application monitoring and logs",
                "topics": ["observability"],
                "matchedCategories": ["coding-agents"],
            }
        )

        self.assertEqual(result["useStage"], "build")
        self.assertNotIn("搜索命中类别", " ".join(result["classificationReasons"]))
        self.assertFalse(project_is_default_visible(result))

    def test_discovery_score_prefers_usable_fresh_tool_over_star_only_framework(self) -> None:
        now = datetime(2026, 7, 26, tzinfo=UTC)
        ready = enrich_discovery_score(
            {
                **classify_ai_project(
                    {
                        "fullName": "example/useful-cli",
                        "description": "A CLI assistant that summarizes PDFs and web pages",
                        "topics": ["cli", "research-assistant"],
                    }
                ),
                "fullName": "example/useful-cli",
                "stars": 3_000,
                "forks": 200,
                "license": "MIT",
                "homepage": "https://example.test/demo",
                "pushedAt": "2026-07-25T00:00:00Z",
                "readmeSignals": {"hasInstall": True, "hasQuickstart": True, "hasDemo": True},
                "stars7dDelta": 600,
                "stars30dDelta": 1_400,
                "historyStatus": "ready",
            },
            now=now,
        )
        framework = enrich_discovery_score(
            {
                **classify_ai_project(
                    {
                        "fullName": "example/agent-framework",
                        "description": "SDK and framework for building multi-agent systems",
                        "topics": ["agent-framework", "sdk"],
                    }
                ),
                "fullName": "example/agent-framework",
                "stars": 150_000,
                "forks": 20_000,
                "license": "MIT",
                "pushedAt": "2026-07-25T00:00:00Z",
                "stars7dDelta": 100,
                "stars30dDelta": 500,
                "historyStatus": "ready",
            },
            now=now,
        )

        self.assertGreater(ready["discoveryScore"], framework["discoveryScore"])
        self.assertLessEqual(framework["scoreBreakdown"]["starCredibility"], 10)
        self.assertTrue(ready["whyRecommended"])

    def test_recent_search_is_independent_and_budgeted(self) -> None:
        specs = build_github_search_specs(datetime(2026, 7, 26, tzinfo=UTC))

        self.assertLessEqual(len(specs), 10)
        recent = [spec for spec in specs if spec["mode"] == "recent"]
        self.assertTrue(recent)
        self.assertTrue(any("created:>=2026-01-27" in spec["query"] for spec in recent))
        self.assertTrue(all(spec["sort"] == "updated" for spec in recent))
        self.assertTrue(all(spec["minStars"] <= 5 for spec in recent))

    def test_legacy_snapshot_migrates_locally_with_old_fields_preserved(self) -> None:
        legacy = {
            "schemaVersion": AI_PROJECTS_SCHEMA_VERSION - 1,
            "kind": "ai-projects",
            "generatedAt": "2026-07-25T00:00:00+00:00",
            "savedAt": "2026-07-25T00:00:00+00:00",
            "expiresAt": "2026-07-25T01:00:00+00:00",
            "projects": [
                {
                    "id": 1,
                    "fullName": "openai/codex",
                    "description": "A coding agent for the terminal",
                    "descriptionZh": "终端编程智能体。",
                    "topics": ["coding-agent", "cli"],
                    "stars": 100,
                    "forks": 10,
                }
            ],
        }

        migrated = migrate_ai_projects_snapshot(legacy, now=datetime(2026, 7, 26, tzinfo=UTC))

        self.assertEqual(migrated["schemaVersion"], AI_PROJECTS_SCHEMA_VERSION)
        self.assertEqual(migrated["migratedFromSchemaVersion"], AI_PROJECTS_SCHEMA_VERSION - 1)
        self.assertEqual(migrated["projects"][0]["descriptionZh"], "终端编程智能体。")
        self.assertEqual(migrated["projects"][0]["useStage"], "ready")
        self.assertEqual(migrated["projects"][0]["productivityCategory"], "coding-agents")
        self.assertTrue(migrated["useStages"])


if __name__ == "__main__":
    unittest.main()
