import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src import ai_service as ai_service_module
from src.ai_service import (
    AI_PROJECTS_SCHEMA_VERSION,
    AI_SCHEMA_VERSION,
    GITHUB_PRODUCTIVITY_SEARCHES,
    MAX_GITHUB_PROJECTS,
    MAX_GITHUB_PROJECTS_PER_CATEGORY,
    MAX_NEWS_ITEMS,
    classify_github_project,
    classify_github_productivity_category,
    curated_project_annotation,
    dedupe_ai_news,
    fallback_project_annotation,
    get_ai_projects,
    has_chinese,
    is_low_quality_ai_title,
    load_snapshot_sync,
    parse_google_news_rss,
    save_snapshot_sync,
    select_github_productivity_projects,
    snapshot_is_valid,
)


class AiServiceTests(unittest.TestCase):
    def test_v121_all_failed_searches_do_not_republish_previous_projects_as_fresh(self) -> None:
        expired_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        stored = {
            "schemaVersion": AI_PROJECTS_SCHEMA_VERSION,
            "kind": "ai-projects",
            "generatedAt": expired_at,
            "savedAt": expired_at,
            "expiresAt": expired_at,
            "projects": [
                {
                    "id": 1,
                    "fullName": "demo/ready-tool",
                    "name": "ready-tool",
                    "owner": "demo",
                    "description": "Ready AI tool",
                    "descriptionZh": "可直接使用的 AI 工具",
                    "topics": [],
                    "stars": 100,
                    "forks": 10,
                    "useStage": "ready",
                    "capabilityTags": ["programming"],
                    "deliverySurfaces": ["cli"],
                    "defaultVisible": True,
                    "discoveryScore": 80,
                }
            ]
        }
        with (
            patch.object(
                ai_service_module,
                "GITHUB_SEARCH_SPECS",
                [{"id": "popular", "query": "ai tool", "mode": "popular"}],
            ),
            patch.object(
                ai_service_module,
                "fetch_github_productivity_search",
                new=AsyncMock(side_effect=RuntimeError("search offline")),
            ),
            patch.object(ai_service_module, "select_enrichment_candidates", return_value=[]),
            patch.object(ai_service_module, "record_ai_project_history", new=AsyncMock()),
            patch.object(ai_service_module, "load_ai_project_history", new=AsyncMock(return_value={})),
            patch.object(ai_service_module, "read_memory_cache", new=AsyncMock(return_value=None)),
            patch.object(ai_service_module, "load_snapshot", new=AsyncMock(return_value=stored)),
            patch.object(ai_service_module, "save_snapshot", new=AsyncMock()) as save_snapshot,
            patch.object(ai_service_module, "write_memory_cache", new=AsyncMock()),
        ):
            payload = asyncio.run(get_ai_projects(refresh=True, allow_stale=True, force=True))

        self.assertTrue(payload["projects"])
        self.assertTrue(payload["cached"])
        self.assertTrue(payload["fromStorage"])
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["generatedAt"], expired_at)
        self.assertTrue(any("search offline" in error for error in payload["errors"]))
        save_snapshot.assert_not_awaited()

    def test_github_project_type_classification(self) -> None:
        cases = [
            ({"fullName": "demo/mcp-server", "description": "Model Context Protocol server", "topics": []}, "安装即用"),
            ({"fullName": "demo/skills", "description": "Reusable AI skills", "topics": []}, "安装即用"),
            ({"fullName": "openai/codex", "description": "A coding agent for the terminal", "topics": []}, "直接可用"),
            ({"fullName": "demo/writer", "description": "A writing agent for long-form articles", "topics": []}, "直接可用"),
            ({"fullName": "demo/agent-sdk", "description": "SDK and framework for building AI agents", "topics": ["agent-framework", "sdk"]}, "开发组件"),
        ]
        for project, expected in cases:
            self.assertEqual(classify_github_project(project)[0], expected)

    def test_productivity_categories_include_task_agents_and_exclude_tensorflow(self) -> None:
        cases = [
            ({"fullName": "openai/codex", "description": "A coding agent", "topics": []}, "coding-agents"),
            (
                {
                    "fullName": "demo/article-writer",
                    "description": "An autonomous writing agent that researches and writes long-form articles",
                    "topics": ["writing-assistant"],
                },
                "coding-agents",
            ),
            ({"fullName": "demo/researcher", "description": "AI research agent for deep reports", "topics": []}, "coding-agents"),
            ({"fullName": "anthropics/skills", "description": "Agent skills", "topics": []}, "skills"),
            ({"fullName": "demo/mcp-server", "description": "Model Context Protocol server", "topics": []}, "mcp"),
            ({"fullName": "langchain-ai/deepagents", "description": "Deep agents framework", "topics": []}, "agent-frameworks"),
            ({"fullName": "demo/agent-sdk", "description": "Framework for building AI agents", "topics": ["agent-framework"]}, "agent-frameworks"),
            ({"fullName": "demo/reviewer", "description": "AI code review workflow", "topics": []}, "dev-workflows"),
        ]
        for project, expected in cases:
            category = classify_github_productivity_category(project)
            self.assertIsNotNone(category)
            self.assertEqual(category[0], expected)

        tensorflow = {
            "fullName": "tensorflow/tensorflow",
            "description": "An open source machine learning framework",
            "topics": ["machine-learning", "deep-learning"],
        }
        self.assertIsNone(classify_github_productivity_category(tensorflow))

    def test_github_searches_stay_within_the_anonymous_search_budget(self) -> None:
        self.assertLessEqual(len(GITHUB_PRODUCTIVITY_SEARCHES), 10)

    def test_productivity_selection_uses_discovery_score_not_search_category_fallback(self) -> None:
        category_ids = ["coding-agents", "skills", "mcp", "agent-frameworks", "dev-workflows"]
        projects = []
        project_id = 1
        for category_index, category_id in enumerate(category_ids):
            for item_index in range(MAX_GITHUB_PROJECTS_PER_CATEGORY + 5):
                projects.append(
                    {
                        "id": project_id,
                        "fullName": f"example/tool-{project_id}",
                        "description": "Purpose-built AI developer tool",
                        "topics": [],
                        "matchedCategories": [category_id],
                        "stars": 100_000 - category_index * 1_000 - item_index,
                        "forks": item_index,
                    }
                )
                project_id += 1
        projects.append(
            {
                "id": project_id,
                "fullName": "tensorflow/tensorflow",
                "description": "Machine learning framework",
                "topics": ["machine-learning"],
                "stars": 999_999,
                "forks": 100_000,
            }
        )

        selected = select_github_productivity_projects(projects)

        self.assertEqual(len(selected), MAX_GITHUB_PROJECTS)
        self.assertNotIn("tensorflow/tensorflow", {project["fullName"] for project in selected})
        self.assertEqual({project["productivityCategory"] for project in selected}, {"coding-agents"})
        self.assertEqual([project["categoryRank"] for project in selected], list(range(1, MAX_GITHUB_PROJECTS + 1)))
        self.assertTrue(all(project["useStage"] == "build" for project in selected))
        self.assertTrue(all("discoveryScore" in project for project in selected))

    def test_curated_github_annotation_explains_project_use(self) -> None:
        annotation = curated_project_annotation({"fullName": "AUTOMATIC1111/stable-diffusion-webui"})
        self.assertIn("生成", annotation)
        self.assertIn("AI 图片", annotation)

    def test_github_fallback_annotation_is_chinese(self) -> None:
        annotation = fallback_project_annotation(
            {"language": "Python", "topics": ["large-language-models", "agents"]}
        )
        self.assertTrue(has_chinese(annotation))
        self.assertIn("Python", annotation)

    def test_placeholder_news_titles_are_filtered(self) -> None:
        self.assertTrue(is_low_quality_ai_title("META_TITLE_QUOTE"))
        self.assertFalse(is_low_quality_ai_title("OpenAI releases a new reasoning model"))

    def test_google_news_parser_and_global_deduplication(self) -> None:
        now = datetime.now(UTC)
        category = {"id": "models", "label": "大模型"}
        rss = f"""
        <rss><channel>
          <item>
            <title>New AI model arrives - Example News</title>
            <link>https://example.com/story?tracking=1</link>
            <pubDate>{format_datetime(now)}</pubDate>
            <description><![CDATA[<p>A useful summary.</p>]]></description>
            <source>Example News</source>
          </item>
        </channel></rss>
        """
        parsed = parse_google_news_rss(rss, category)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "New AI model arrives")
        self.assertEqual(parsed[0]["category"], "models")

        duplicate = dict(parsed[0])
        duplicate["url"] = "https://another.example/story"
        duplicate["publishedAt"] = (now - timedelta(minutes=1)).isoformat()
        old = dict(parsed[0])
        old["title"] = "An old AI story"
        old["publishedAt"] = (now - timedelta(days=8)).isoformat()

        result = dedupe_ai_news([parsed[0], duplicate, old], now - timedelta(days=7))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], parsed[0]["url"])

    def test_snapshot_is_overwritten_and_payload_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ai.sqlite"
            now = datetime.now(UTC).isoformat()
            first = {
                "schemaVersion": AI_PROJECTS_SCHEMA_VERSION,
                "kind": "ai-projects",
                "generatedAt": now,
                "savedAt": now,
                "expiresAt": now,
                "projects": [{"id": index} for index in range(MAX_GITHUB_PROJECTS + 10)],
                "cached": False,
            }
            second = {**first, "projects": [{"id": 999}]}

            save_snapshot_sync(db_path, "latest_ai_projects", first)
            with sqlite3.connect(db_path) as connection:
                row_count = connection.execute("SELECT COUNT(*) FROM latest_ai_projects").fetchone()[0]
                stored_payload = json.loads(connection.execute("SELECT payload_json FROM latest_ai_projects WHERE id = 1").fetchone()[0])
            self.assertEqual(row_count, 1)
            self.assertEqual(len(stored_payload["projects"]), MAX_GITHUB_PROJECTS)
            self.assertNotIn("cached", stored_payload)

            save_snapshot_sync(db_path, "latest_ai_projects", second)
            stored = load_snapshot_sync(db_path, "latest_ai_projects")
            self.assertEqual(stored["projects"], [{"id": 999}])

    def test_project_snapshot_uses_its_own_schema_version(self) -> None:
        self.assertTrue(snapshot_is_valid({"schemaVersion": AI_PROJECTS_SCHEMA_VERSION, "kind": "ai-projects"}, "ai-projects"))
        self.assertFalse(snapshot_is_valid({"schemaVersion": AI_SCHEMA_VERSION, "kind": "ai-projects"}, "ai-projects"))

    def test_news_snapshot_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ai.sqlite"
            now = datetime.now(UTC).isoformat()
            payload = {
                "schemaVersion": AI_SCHEMA_VERSION,
                "kind": "ai-news",
                "generatedAt": now,
                "savedAt": now,
                "expiresAt": now,
                "items": [{"id": index} for index in range(MAX_NEWS_ITEMS + 10)],
            }
            save_snapshot_sync(db_path, "latest_ai_news", payload)
            stored = load_snapshot_sync(db_path, "latest_ai_news")
            self.assertEqual(len(stored["items"]), MAX_NEWS_ITEMS)


if __name__ == "__main__":
    unittest.main()
