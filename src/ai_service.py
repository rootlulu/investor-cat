from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from .ai_discovery import (
    AI_PROJECT_MIN_30D_STAR_GROWTH,
    AI_PROJECT_MIN_7D_STAR_GROWTH,
    AI_PROJECT_MIN_TOTAL_STARS,
    CAPABILITY_META,
    SURFACE_META,
    USE_STAGE_META,
    apply_project_history,
    build_github_search_specs,
    build_project_signals,
    classify_ai_project,
    enrich_discovery_score,
    extract_readme_signals,
    project_is_default_visible,
    project_meets_star_selection,
    project_star_selection_basis,
    select_enrichment_candidates,
)
from .request_coordinator import coordinate_httpx_client


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_REPOS_API = "https://api.github.com/repos"
TRANSLATE_API = "https://translate.googleapis.com/translate_a/single"
AI_SCHEMA_VERSION = 2
AI_PROJECTS_SCHEMA_VERSION = 7
WINDOW_DAYS = 7
MAX_NEWS_PER_CATEGORY = 40
MAX_NEWS_ITEMS = 200
MAX_GITHUB_PROJECTS_PER_CATEGORY = 30
MAX_GITHUB_PROJECTS = 5 * MAX_GITHUB_PROJECTS_PER_CATEGORY
MIN_GITHUB_STARS = 20

AI_NEWS_CATEGORIES = [
    {
        "id": "models",
        "label": "大模型",
        "description": "基础模型、AI 产品、智能体与模型发布",
        "queries": [
            ("(人工智能 OR 大模型 OR 生成式AI OR ChatGPT OR Claude OR Gemini) when:7d", "zh-CN", "CN", "CN:zh-Hans"),
            ('("artificial intelligence" OR "large language model" OR ChatGPT OR Claude OR Gemini) when:7d', "en-US", "US", "US:en"),
        ],
    },
    {
        "id": "markets",
        "label": "公司与股票",
        "description": "AI 公司、投融资、财报与相关股票",
        "queries": [
            ("(AI股票 OR 人工智能公司 OR 大模型融资 OR AI投资) when:7d", "zh-CN", "CN", "CN:zh-Hans"),
            ('("AI stocks" OR "artificial intelligence company" OR "AI funding" OR Nvidia) when:7d', "en-US", "US", "US:en"),
        ],
    },
    {
        "id": "security",
        "label": "国家安全",
        "description": "监管、封锁、制裁、出口管制与国家安全",
        "queries": [
            ("(人工智能 国家安全 OR AI封锁 OR 芯片出口管制 OR 人工智能监管) when:7d", "zh-CN", "CN", "CN:zh-Hans"),
            ('("artificial intelligence" ("national security" OR ban OR sanctions OR "export controls" OR regulation)) when:7d', "en-US", "US", "US:en"),
        ],
    },
    {
        "id": "chips",
        "label": "芯片算力",
        "description": "AI 芯片、数据中心、云算力与能源基础设施",
        "queries": [
            ("(AI芯片 OR 人工智能算力 OR 数据中心 OR GPU) when:7d", "zh-CN", "CN", "CN:zh-Hans"),
            ('("AI chips" OR GPU OR "AI data center" OR "AI compute") when:7d', "en-US", "US", "US:en"),
        ],
    },
    {
        "id": "research",
        "label": "研究开源",
        "description": "AI 研究、开源模型、论文与开发者生态",
        "queries": [
            ("(AI研究 OR 开源大模型 OR 人工智能论文 OR AI开源) when:7d", "zh-CN", "CN", "CN:zh-Hans"),
            ('("AI research" OR "open source model" OR "machine learning research") when:7d', "en-US", "US", "US:en"),
        ],
    },
]

GITHUB_PRODUCTIVITY_CATEGORIES = [
    {
        # Keep this ID for compatibility with existing API consumers and saved URL hashes.
        "id": "coding-agents",
        "label": "智能体",
        "description": "能够直接替用户完成任务的 AI 智能体，覆盖编程、写作、研究、浏览器操作和个人助理等用途。",
        "queries": ["\"AI agent\"", "\"coding agent\"", "\"writing agent\""],
    },
    {
        "id": "skills",
        "label": "Skills / 插件",
        "description": "面向 Codex、Claude Code 等智能体的可复用技能、命令、Hooks 与扩展包。",
        "queries": ["\"agent skills\"", "\"Claude Code skills\""],
    },
    {
        "id": "mcp",
        "label": "MCP 工具",
        "description": "Model Context Protocol 服务、SDK、目录与调试工具，用来连接外部数据和能力。",
        "queries": ["\"Model Context Protocol\""],
    },
    {
        "id": "agent-frameworks",
        "label": "Agent 框架",
        "description": "用于构建、编排和运行单 Agent 或多 Agent 系统的框架，例如 Deep Agents。",
        "queries": ["\"agent framework\"", "deepagents"],
    },
    {
        "id": "dev-workflows",
        "label": "开发工作流",
        "description": "上下文工程、代码审查、规范驱动开发、记忆与提示词等效率工具。",
        "queries": ["\"context engineering\"", "\"AI code review\""],
    },
]

GITHUB_PRODUCTIVITY_CATEGORY_BY_ID = {
    category["id"]: category for category in GITHUB_PRODUCTIVITY_CATEGORIES
}
GITHUB_SEARCH_SPECS = build_github_search_specs()
GITHUB_PRODUCTIVITY_SEARCHES = [
    (spec["id"], spec["query"])
    for spec in GITHUB_SEARCH_SPECS
]

GITHUB_PROJECT_CATEGORY_OVERRIDES = {
    "aider-ai/aider": "coding-agents",
    "assafelovic/gpt-researcher": "coding-agents",
    "anthropics/claude-code": "coding-agents",
    "anthropics/skills": "skills",
    "browser-use/browser-use": "coding-agents",
    "cline/cline": "coding-agents",
    "crewaiinc/crewai": "agent-frameworks",
    "langchain-ai/deepagents": "agent-frameworks",
    "langchain-ai/langgraph": "agent-frameworks",
    "microsoft/autogen": "agent-frameworks",
    "modelcontextprotocol/python-sdk": "mcp",
    "modelcontextprotocol/servers": "mcp",
    "modelcontextprotocol/typescript-sdk": "mcp",
    "openai/codex": "coding-agents",
    "openmanus/openmanus": "coding-agents",
    "openhands/openhands": "coding-agents",
    "punkpeye/awesome-mcp-servers": "mcp",
    "roocodeinc/roo-code": "coding-agents",
    "significant-gravitas/autogpt": "coding-agents",
    "stanford-oval/storm": "coding-agents",
}

CURATED_PROJECT_ANNOTATIONS = {
    "openai/codex": "OpenAI 的开源编程智能体，可在终端中读取仓库、修改代码、运行命令并协助完成开发任务。",
    "anthropics/claude-code": "Anthropic 的终端编程智能体，可理解代码库、编辑文件、执行命令并处理开发工作流。",
    "anthropics/skills": "Anthropic 发布的 Agent Skills 示例与规范，用于给 Claude Code 等智能体封装可复用能力。",
    "aider-ai/aider": "面向终端的 AI 结对编程工具，可连接代码仓库并通过对话完成跨文件修改。",
    "cline/cline": "运行在编辑器中的自主编程智能体，可规划任务、修改代码并调用终端与浏览器工具。",
    "langchain-ai/deepagents": "用于构建能够规划、调用工具、管理上下文并执行复杂长期任务的 Agent 框架。",
    "modelcontextprotocol/servers": "Model Context Protocol 参考服务集合，为编码智能体连接文件、数据源和外部系统。",
    "tensorflow/tensorflow": "用于构建、训练和部署机器学习及深度学习模型的通用开源框架。",
    "significant-gravitas/autogpt": "用于创建和运行自主 AI 智能体，让模型能够拆解目标并连续执行任务。",
    "f/prompts.chat": "社区驱动的 AI 提示词库，可搜索、收藏并私有化部署 ChatGPT 等模型的提示词。",
    "automatic1111/stable-diffusion-webui": "Stable Diffusion 的网页操作界面，用于本地生成和编辑 AI 图片。",
    "huggingface/transformers": "提供文本、视觉、音频及多模态预训练模型，支持模型训练、微调和推理。",
    "langflow-ai/langflow": "通过可视化流程搭建和部署大模型应用、AI 智能体及自动化工作流。",
    "langchain-ai/langchain": "用于开发大模型应用和 AI 智能体的工程框架，连接模型、工具、数据与记忆。",
    "pytorch/pytorch": "支持 GPU 加速的深度学习框架，用于研究、训练和部署神经网络模型。",
    "rasbt/llms-from-scratch": "通过 PyTorch 从零实现类 ChatGPT 大模型的逐步教程和配套代码。",
    "opencv/opencv": "提供图像处理、目标识别和视频分析能力的开源计算机视觉库。",
    "hiyouga/llamafactory": "用于统一微调和训练上百种大语言模型、多模态模型的高效工具。",
    "openhands/openhands": "能够阅读代码、修改项目和执行开发任务的开源 AI 编程智能体平台。",
    "scikit-learn/scikit-learn": "Python 经典机器学习库，提供分类、回归、聚类、预处理和模型评估工具。",
    "keras-team/keras": "面向开发者的高级深度学习 API，用于快速构建和训练神经网络。",
    "ultralytics/ultralytics": "YOLO 计算机视觉工具包，用于目标检测、分割、分类、姿态估计和跟踪。",
    "tesseract-ocr/tesseract": "从图片和扫描文档中识别文字的开源 OCR 引擎。",
    "flowiseai/flowise": "通过拖拽式界面构建大模型应用、RAG 流程和 AI 智能体。",
    "openbb-finance/openbb": "面向金融分析师、量化研究和 AI 智能体的开放金融数据平台。",
    "microsoft/qlib": "利用机器学习进行因子研究、策略建模和量化投资实验的平台。",
    "coqui-ai/tts": "用于训练和运行文字转语音、语音合成模型的深度学习工具包。",
    "streamlit/streamlit": "使用 Python 快速制作并分享数据分析、机器学习和 AI Web 应用。",
    "kong/kong": "管理、保护和观测 API 与 AI 模型流量的开源网关。",
}

AI_NEWS_CACHE: dict[str, Any] = {"data": None, "expires_at": datetime.min.replace(tzinfo=UTC)}
AI_PROJECTS_CACHE: dict[str, Any] = {"data": None, "expires_at": datetime.min.replace(tzinfo=UTC)}
AI_NEWS_CACHE_LOCK = asyncio.Lock()
AI_PROJECTS_CACHE_LOCK = asyncio.Lock()
AI_NEWS_FETCH_LOCK = asyncio.Lock()
AI_PROJECTS_FETCH_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()


async def get_ai_news(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    db_path = resolve_sqlite_path(config)
    ttl_seconds = refresh_interval_seconds(config)

    cached = await read_memory_cache(AI_NEWS_CACHE, AI_NEWS_CACHE_LOCK, refresh, force)
    if cached:
        return cached

    stored = await load_snapshot(db_path, "latest_ai_news")
    stored_valid = snapshot_is_valid(stored, "ai-news")
    stored_fresh = bool(stored_valid and snapshot_expires_at(stored, ttl_seconds) > datetime.now(UTC))
    if not force and stored_valid and ((allow_stale and not refresh) or stored_fresh):
        return await use_stored_snapshot(stored, AI_NEWS_CACHE, AI_NEWS_CACHE_LOCK, ttl_seconds, refresh, stored_fresh)

    async with AI_NEWS_FETCH_LOCK:
        if not force:
            cached = await read_memory_cache(AI_NEWS_CACHE, AI_NEWS_CACHE_LOCK, refresh, force)
            if cached:
                return cached
            stored = await load_snapshot(db_path, "latest_ai_news")
            stored_valid = snapshot_is_valid(stored, "ai-news")
            stored_fresh = bool(stored_valid and snapshot_expires_at(stored, ttl_seconds) > datetime.now(UTC))
            if stored_fresh:
                return await use_stored_snapshot(stored, AI_NEWS_CACHE, AI_NEWS_CACHE_LOCK, ttl_seconds, refresh, True)

        data = await fetch_ai_news_snapshot(ttl_seconds, previous=stored if stored_valid else None)
        if not data["items"] and stored_valid:
            fallback = dict(stored)
            fallback.update({"cached": True, "fromStorage": True, "stale": True, "throttled": False})
            fallback["errors"] = list(dict.fromkeys([*(stored.get("errors") or []), *(data.get("errors") or [])]))
            return fallback

        await save_snapshot(db_path, "latest_ai_news", data)
        await write_memory_cache(AI_NEWS_CACHE, AI_NEWS_CACHE_LOCK, data, ttl_seconds)
        return data


async def read_ai_news_snapshot() -> dict[str, Any] | None:
    """Return the latest usable AI-news snapshot without starting external I/O."""

    config = load_config()
    ttl_seconds = refresh_interval_seconds(config)
    cached = AI_NEWS_CACHE.get("data")
    from_storage = False
    if not isinstance(cached, dict) or not cached.get("items"):
        cached = await load_snapshot(resolve_sqlite_path(config), "latest_ai_news")
        from_storage = True
    if not isinstance(cached, dict) or not cached.get("items"):
        return None

    snapshot = dict(cached)
    schema_current = snapshot_is_valid(snapshot, "ai-news")
    snapshot.update(
        {
            "cached": True,
            "fromStorage": from_storage,
            "throttled": False,
            "stale": not schema_current or snapshot_expires_at(snapshot, ttl_seconds) <= datetime.now(UTC),
        }
    )
    return snapshot


async def get_ai_projects(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    db_path = resolve_sqlite_path(config)
    ttl_seconds = refresh_interval_seconds(config)

    cached = await read_memory_cache(AI_PROJECTS_CACHE, AI_PROJECTS_CACHE_LOCK, refresh, force)
    if cached and cached.get("kind") == "ai-projects":
        cached = migrate_ai_projects_snapshot(cached)
    if cached:
        return cached

    stored = await load_snapshot(db_path, "latest_ai_projects")
    if stored and stored.get("kind") == "ai-projects":
        stored = migrate_ai_projects_snapshot(stored)
    stored_compatible = bool(stored and stored.get("kind") == "ai-projects")
    stored_valid = snapshot_is_valid(stored, "ai-projects")
    stored_fresh = bool(stored_valid and snapshot_expires_at(stored, ttl_seconds) > datetime.now(UTC))
    if not force and stored_valid and ((allow_stale and not refresh) or stored_fresh):
        return await use_stored_snapshot(stored, AI_PROJECTS_CACHE, AI_PROJECTS_CACHE_LOCK, ttl_seconds, refresh, stored_fresh)

    async with AI_PROJECTS_FETCH_LOCK:
        if not force:
            cached = await read_memory_cache(AI_PROJECTS_CACHE, AI_PROJECTS_CACHE_LOCK, refresh, force)
            if cached and cached.get("kind") == "ai-projects":
                cached = migrate_ai_projects_snapshot(cached)
            if cached:
                return cached
            stored = await load_snapshot(db_path, "latest_ai_projects")
            if stored and stored.get("kind") == "ai-projects":
                stored = migrate_ai_projects_snapshot(stored)
            stored_compatible = bool(stored and stored.get("kind") == "ai-projects")
            stored_valid = snapshot_is_valid(stored, "ai-projects")
            stored_fresh = bool(stored_valid and snapshot_expires_at(stored, ttl_seconds) > datetime.now(UTC))
            if stored_fresh:
                return await use_stored_snapshot(stored, AI_PROJECTS_CACHE, AI_PROJECTS_CACHE_LOCK, ttl_seconds, refresh, True)

        data = await fetch_ai_projects_snapshot(ttl_seconds, previous=stored if stored_compatible else None)
        if not data["projects"] and stored_valid:
            fallback = dict(stored)
            fallback.update({"cached": True, "fromStorage": True, "stale": True, "throttled": False})
            fallback["errors"] = list(dict.fromkeys([*(stored.get("errors") or []), *(data.get("errors") or [])]))
            return fallback

        await save_snapshot(db_path, "latest_ai_projects", data)
        await write_memory_cache(AI_PROJECTS_CACHE, AI_PROJECTS_CACHE_LOCK, data, ttl_seconds)
        return data


async def fetch_ai_news_snapshot(ttl_seconds: int, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    requests: list[tuple[dict[str, Any], tuple[str, str, str, str]]] = []
    for category in AI_NEWS_CATEGORIES:
        for query in category["queries"]:
            requests.append((category, query))

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsDigestAI/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=httpx.Timeout(15.0)) as client:
        coordinate_httpx_client(client)
        results = await asyncio.gather(
            *(fetch_google_news_query(client, category, query) for category, query in requests),
            return_exceptions=True,
        )

    raw_items: list[dict[str, Any]] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            errors.append(short_error(result))
        else:
            raw_items.extend(result)

    items = dedupe_ai_news(raw_items, cutoff)
    counts: dict[str, int] = {category["id"]: 0 for category in AI_NEWS_CATEGORIES}
    selected: list[dict[str, Any]] = []
    for item in items:
        category_id = item["category"]
        if counts.get(category_id, 0) >= MAX_NEWS_PER_CATEGORY:
            continue
        selected.append(item)
        counts[category_id] = counts.get(category_id, 0) + 1
        if len(selected) >= MAX_NEWS_ITEMS:
            break

    previous_items = {str(item.get("id")): item for item in (previous or {}).get("items", []) if item.get("id")}
    titles_to_translate = []
    for item in selected:
        source_title = clean_text(item.get("title", ""))
        item["originalTitle"] = source_title
        previous_item = previous_items.get(str(item.get("id")))
        previous_title = clean_text((previous_item or {}).get("title", ""))
        generated_fallback_title = f"{item.get('categoryLabel') or 'AI'}最新动态"
        previous_is_fallback = bool(
            previous_item
            and (
                previous_item.get("translationStatus") == "fallback"
                or previous_title == generated_fallback_title
            )
        )
        if previous_item and has_chinese(previous_title) and not previous_is_fallback:
            item["title"] = previous_title
            item["summary"] = previous_item.get("summary", "") if has_chinese(previous_item.get("summary", "")) else ""
            item["translationStatus"] = "cached"
        elif source_title and not has_chinese(source_title):
            titles_to_translate.append(source_title)

    translations = await translate_many_to_chinese(titles_to_translate, max_output_chars=120)
    untranslated_count = 0
    for item in selected:
        if not has_chinese(item.get("title", "")):
            original_title = clean_text(item.get("originalTitle", ""))
            translated = translations.get(original_title, "")
            if translated:
                item["title"] = translated
                item["translationStatus"] = "translated"
            else:
                item["title"] = original_title
                item["translationStatus"] = "original"
                untranslated_count += 1
        elif not item.get("translationStatus"):
            item["translationStatus"] = "original"
        if item.get("summary") and not has_chinese(item["summary"]):
            item["summary"] = ""

    generated_at = datetime.now(UTC)
    categories = [
        {
            "id": category["id"],
            "label": category["label"],
            "description": category["description"],
            "count": counts.get(category["id"], 0),
        }
        for category in AI_NEWS_CATEGORIES
    ]
    return {
        "schemaVersion": AI_SCHEMA_VERSION,
        "kind": "ai-news",
        "generatedAt": generated_at.isoformat(),
        "savedAt": generated_at.isoformat(),
        "expiresAt": (generated_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "window": "最近7天",
        "windowDays": WINDOW_DAYS,
        "windowStart": cutoff.isoformat(),
        "cached": False,
        "fromStorage": False,
        "stale": False,
        "throttled": False,
        "source": "Google News RSS",
        "categories": categories,
        "summary": {"itemCount": len(selected), "categoryCount": sum(1 for value in counts.values() if value)},
        "errors": list(dict.fromkeys([*errors, *( [f"{untranslated_count}条标题未完成翻译，已保留原文"] if untranslated_count else [])]))[:20],
        "items": selected,
        "hasData": bool(selected),
    }


async def fetch_google_news_query(
    client: httpx.AsyncClient,
    category: dict[str, Any],
    query_settings: tuple[str, str, str, str],
) -> list[dict[str, Any]]:
    query, language, country, edition = query_settings
    url = f"{GOOGLE_NEWS_RSS}?{urlencode({'q': query, 'hl': language, 'gl': country, 'ceid': edition})}"
    response = await client.get(url)
    response.raise_for_status()
    return parse_google_news_rss(response.text, category)


def parse_google_news_rss(xml_text: str, category: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for node in root.findall(".//item"):
        raw_title = clean_text(node.findtext("title") or "")
        source_node = node.find("source")
        source = clean_text(source_node.text if source_node is not None and source_node.text else "") or "Google News"
        title = strip_source_suffix(raw_title, source)
        url = clean_text(node.findtext("link") or "")
        published_at = parse_rss_datetime(node.findtext("pubDate") or "")
        description = clean_text(node.findtext("description") or "")
        normalized_description = normalize_title(description)
        normalized_title = normalize_title(raw_title)
        summary = description if description and normalized_title not in normalized_description else ""
        if not title or not url or not published_at or is_low_quality_ai_title(title):
            continue
        identity = hashlib.sha256(f"{normalize_title(title)}|{canonical_url(url)}".encode("utf-8")).hexdigest()[:20]
        items.append(
            {
                "id": identity,
                "title": title,
                "originalTitle": raw_title if raw_title != title else "",
                "url": url,
                "source": source,
                "publishedAt": published_at.isoformat(),
                "category": category["id"],
                "categoryLabel": category["label"],
                "topic": category["label"],
                "summary": summary[:500],
            }
        )
    return items


def dedupe_ai_news(items: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        published_at = parse_datetime(item.get("publishedAt"))
        if published_at < cutoff or published_at > datetime.now(UTC) + timedelta(hours=2):
            continue
        key = normalize_title(item.get("title")) or canonical_url(item.get("url", ""))
        if not key:
            continue
        current = deduped.get(key)
        if not current or parse_datetime(current.get("publishedAt")) < published_at:
            deduped[key] = item
    return sorted(deduped.values(), key=lambda item: parse_datetime(item.get("publishedAt")), reverse=True)


async def fetch_ai_projects_snapshot(ttl_seconds: int, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "news-digest-web",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=httpx.Timeout(45.0)) as client:
        coordinate_httpx_client(client)
        results = await asyncio.gather(
            *(
                fetch_github_productivity_search(client, search_spec)
                for search_spec in GITHUB_SEARCH_SPECS
            ),
            return_exceptions=True,
        )

    repositories: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    rate_remaining: list[int] = []
    rate_resets: list[str] = []
    successful_searches = 0
    for result in results:
        if isinstance(result, Exception):
            errors.append(short_error(result))
            continue
        successful_searches += 1
        search_id, _query, discovery_mode, rows, remaining, reset = result
        if remaining is not None:
            rate_remaining.append(remaining)
        if reset:
            rate_resets.append(reset)
        for row in rows:
            repo_id = int(row.get("id") or 0)
            if not repo_id or row.get("fork") or row.get("archived"):
                continue
            existing = repositories.get(repo_id)
            if existing:
                matched_searches = existing.setdefault("matchedSearches", [])
                if search_id not in matched_searches:
                    matched_searches.append(search_id)
                discovery_modes = existing.setdefault("discoveryModes", [])
                if discovery_mode not in discovery_modes:
                    discovery_modes.append(discovery_mode)
            else:
                row["matchedSearches"] = [search_id]
                row["discoveryModes"] = [discovery_mode]
                repositories[repo_id] = row

    generated_at = datetime.now(UTC)
    projects = [normalize_github_project(row, 0) for row in repositories.values()]
    current_project_keys = {github_project_key(project) for project in projects if github_project_key(project)}
    previous_projects_by_key = {
        github_project_key(project): project
        for project in (previous or {}).get("projects", [])
        if github_project_key(project)
    }
    for project in projects:
        previous_project = previous_projects_by_key.get(github_project_key(project))
        if not previous_project:
            continue
        for field in ("release", "readmeSignals", "enrichmentStatus", "enrichmentCheckedAt"):
            if previous_project.get(field) is not None:
                project[field] = previous_project[field]
    if errors and previous and successful_searches:
        merged_projects = {
            github_project_key(project): project
            for project in projects
            if github_project_key(project)
        }
        for previous_project in previous.get("projects", []):
            project_key = github_project_key(previous_project)
            if project_key and project_key not in merged_projects:
                merged_projects[project_key] = dict(previous_project)
        projects = list(merged_projects.values())

    enrichment_targets = select_enrichment_candidates(projects, authenticated=bool(token))
    enrichment_request_count = len(enrichment_targets) * 2
    if enrichment_targets:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=httpx.Timeout(30.0)) as client:
            coordinate_httpx_client(client)
            enrichment_results = await asyncio.gather(
                *(
                    fetch_github_project_enrichment(
                        client,
                        project,
                        previous_projects_by_key.get(github_project_key(project)),
                    )
                    for project in enrichment_targets
                ),
                return_exceptions=True,
            )
        projects_by_key = {github_project_key(project): project for project in projects if github_project_key(project)}
        for result in enrichment_results:
            if isinstance(result, Exception):
                errors.append(short_error(result))
                continue
            project_key, enrichment, enrichment_errors = result
            if project_key in projects_by_key:
                projects_by_key[project_key].update(enrichment)
            errors.extend(enrichment_errors)

    db_path = resolve_sqlite_path(load_config())
    history_candidates = [project for project in projects if github_project_key(project) in current_project_keys]
    await record_ai_project_history(db_path, history_candidates, observed_at=generated_at)
    history_by_key = await load_ai_project_history(
        db_path,
        [github_project_key(project) for project in projects if github_project_key(project)],
        now=generated_at,
    )
    for index, project in enumerate(projects):
        project_key = github_project_key(project)
        enriched = apply_project_history(project, history_by_key.get(project_key, []), now=generated_at)
        enriched["signals"] = build_project_signals(enriched, now=generated_at)
        projects[index] = enrich_discovery_score(enriched, now=generated_at)

    projects = select_github_productivity_projects(projects)
    previous_projects = {int(item.get("id") or 0): item for item in (previous or {}).get("projects", []) if item.get("id")}
    descriptions_to_translate = []
    for project in projects:
        previous_project = previous_projects.get(project["id"])
        curated = curated_project_annotation(project)
        if curated:
            project["descriptionZh"] = curated
        elif has_chinese(project.get("description", "")):
            project["descriptionZh"] = project["description"]
        elif (
            previous_project
            and previous_project.get("description") == project.get("description")
            and has_chinese(previous_project.get("descriptionZh", ""))
        ):
            project["descriptionZh"] = previous_project["descriptionZh"]
        elif project.get("description"):
            descriptions_to_translate.append(project["description"])

    translated_descriptions = await translate_many_to_chinese(descriptions_to_translate, max_output_chars=180)
    translated_count = 0
    for project in projects:
        if not project.get("descriptionZh"):
            project["descriptionZh"] = translated_descriptions.get(project.get("description", ""), "")
        if not project.get("descriptionZh"):
            project["descriptionZh"] = fallback_project_annotation(project)
        else:
            translated_count += 1
        project["descriptionZh"] = concise_project_annotation(project["descriptionZh"])
    signal_payload = {
        "high": [signal for project in projects for signal in (project.get("signals") or {}).get("high", [])],
        "digest": [signal for project in projects for signal in (project.get("signals") or {}).get("digest", [])],
    }
    rate_limit = {
        "remaining": min(rate_remaining) if rate_remaining else None,
        "resetAt": max(rate_resets) if rate_resets else "",
        "authenticated": bool(token),
    }
    facets = build_ai_project_facets(projects)
    return {
        "schemaVersion": AI_PROJECTS_SCHEMA_VERSION,
        "kind": "ai-projects",
        "generatedAt": generated_at.isoformat(),
        "savedAt": generated_at.isoformat(),
        "expiresAt": (generated_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "stale": False,
        "throttled": False,
        "source": "GitHub Search API",
        "sort": "total-stars-then-growth",
        "limit": MAX_GITHUB_PROJECTS,
        "perCategoryLimit": MAX_GITHUB_PROJECTS_PER_CATEGORY,
        "selectionCriteria": {
            "minTotalStars": AI_PROJECT_MIN_TOTAL_STARS,
            "min7dStarGrowth": AI_PROJECT_MIN_7D_STAR_GROWTH,
            "min30dStarGrowth": AI_PROJECT_MIN_30D_STAR_GROWTH,
            "requiresReadyHistoryForGrowth": True,
        },
        **facets,
        "searches": [spec["query"] for spec in GITHUB_SEARCH_SPECS],
        "searchSpecs": [dict(spec) for spec in GITHUB_SEARCH_SPECS],
        "summary": {
            "projectCount": len(projects),
            "candidateCount": len(repositories),
            "defaultVisibleCount": sum(1 for project in projects if project_is_default_visible(project)),
            "hiddenByDefaultCount": sum(1 for project in projects if not project_is_default_visible(project)),
            "translatedCount": translated_count,
            "historyRecordedCount": len(history_candidates),
            "enrichmentRequestCount": enrichment_request_count,
            "highSignalCount": len(signal_payload["high"]),
            "digestSignalCount": len(signal_payload["digest"]),
        },
        "rateLimit": rate_limit,
        "errors": list(dict.fromkeys(errors))[:20],
        "signals": signal_payload,
        "projects": projects,
        "hasData": bool(projects),
    }


async def fetch_github_productivity_search(
    client: httpx.AsyncClient,
    search_spec: dict[str, Any] | str,
    query: str = "",
) -> tuple[str, str, str, list[dict[str, Any]], int | None, str]:
    if isinstance(search_spec, dict):
        spec = search_spec
    else:
        spec = {
            "id": search_spec,
            "mode": "popular",
            "query": query,
            "sort": "stars",
            "order": "desc",
            "minStars": MIN_GITHUB_STARS,
        }
    search_id = str(spec.get("id") or "general")
    search_query = str(spec.get("query") or "")
    discovery_mode = str(spec.get("mode") or "popular")
    params = {
        "q": f"{search_query} in:name,description,topics stars:>={int(spec.get('minStars') or MIN_GITHUB_STARS)} archived:false fork:false",
        "sort": str(spec.get("sort") or "stars"),
        "order": str(spec.get("order") or "desc"),
        "per_page": 100,
        "page": 1,
    }
    try:
        response = await client.get(GITHUB_SEARCH_API, params=params)
        response.raise_for_status()
    except Exception as error:
        raise RuntimeError(f"GitHub {search_id} search: {short_error(error)}") from error
    payload = response.json()
    remaining = safe_int(response.headers.get("x-ratelimit-remaining"))
    reset_at = epoch_to_iso(response.headers.get("x-ratelimit-reset"))
    return search_id, search_query, discovery_mode, payload.get("items") or [], remaining, reset_at


async def fetch_github_project_enrichment(
    client: httpx.AsyncClient,
    project: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    project_key = github_project_key(project)
    full_name = str(project.get("fullName") or "").strip()
    encoded_name = "/".join(quote(part, safe="") for part in full_name.split("/", 1))
    release_url = f"{GITHUB_REPOS_API}/{encoded_name}/releases/latest"
    readme_url = f"{GITHUB_REPOS_API}/{encoded_name}/readme"
    responses = await asyncio.gather(client.get(release_url), client.get(readme_url), return_exceptions=True)
    errors: list[str] = []
    enrichment = {
        "release": dict((previous or {}).get("release") or {}),
        "readmeSignals": dict((previous or {}).get("readmeSignals") or {}),
        "enrichmentStatus": "stale" if previous else "missing",
        "enrichmentCheckedAt": datetime.now(UTC).isoformat(),
    }

    release_response = responses[0]
    if isinstance(release_response, Exception):
        errors.append(f"GitHub {full_name} release: {short_error(release_response)}")
    elif release_response.status_code == 404:
        enrichment["release"] = {}
    else:
        try:
            release_response.raise_for_status()
            release_payload = release_response.json()
            enrichment["release"] = {
                "tag": str(release_payload.get("tag_name") or ""),
                "name": clean_text(release_payload.get("name") or "")[:160],
                "url": str(release_payload.get("html_url") or ""),
                "publishedAt": str(release_payload.get("published_at") or ""),
                "createdAt": str(release_payload.get("created_at") or ""),
                "prerelease": bool(release_payload.get("prerelease")),
                "draft": bool(release_payload.get("draft")),
            }
            enrichment["enrichmentStatus"] = "fresh"
        except Exception as error:
            errors.append(f"GitHub {full_name} release: {short_error(error)}")

    readme_response = responses[1]
    if isinstance(readme_response, Exception):
        errors.append(f"GitHub {full_name} README: {short_error(readme_response)}")
    elif readme_response.status_code == 404:
        enrichment["readmeSignals"] = {"hasInstall": False, "hasQuickstart": False, "hasDemo": False}
    else:
        try:
            readme_response.raise_for_status()
            readme_payload = readme_response.json()
            encoded_content = str(readme_payload.get("content") or "").replace("\n", "")
            readme_text = base64.b64decode(encoded_content, validate=False).decode("utf-8", errors="ignore")
            enrichment["readmeSignals"] = extract_readme_signals(readme_text)
            enrichment["enrichmentStatus"] = "fresh"
        except Exception as error:
            errors.append(f"GitHub {full_name} README: {short_error(error)}")

    return project_key, enrichment, errors


def normalize_github_project(row: dict[str, Any], rank: int) -> dict[str, Any]:
    license_data = row.get("license") or {}
    owner = row.get("owner") or {}
    license_name = license_data.get("spdx_id") or license_data.get("name") or ""
    all_topics = list(dict.fromkeys(row.get("topics") or []))
    if license_name == "NOASSERTION":
        license_name = ""
    project = {
        "id": int(row.get("id") or 0),
        "rank": rank,
        "name": row.get("name") or "",
        "fullName": row.get("full_name") or "",
        "url": row.get("html_url") or "",
        "description": clean_text(row.get("description") or "")[:500],
        "descriptionZh": "",
        "stars": int(row.get("stargazers_count") or 0),
        "forks": int(row.get("forks_count") or 0),
        "openIssues": int(row.get("open_issues_count") or 0),
        "language": row.get("language") or "",
        "license": license_name,
        "topics": all_topics[:12],
        "matchedCategories": list(dict.fromkeys(row.get("matchedCategories") or [])),
        "matchedSearches": list(dict.fromkeys(row.get("matchedSearches") or [])),
        "discoveryModes": list(dict.fromkeys(row.get("discoveryModes") or [])),
        "owner": owner.get("login") or "",
        "ownerAvatar": owner.get("avatar_url") or "",
        "homepage": row.get("homepage") or "",
        "createdAt": row.get("created_at") or "",
        "updatedAt": row.get("updated_at") or "",
        "pushedAt": row.get("pushed_at") or "",
    }
    classification_source = {**project, "topics": all_topics}
    classification = classify_ai_project(classification_source)
    classification["legacyCategory"] = github_legacy_category_id(classification_source, classification)
    project.update(classification)
    category = GITHUB_PRODUCTIVITY_CATEGORY_BY_ID[classification["legacyCategory"]]
    project["productivityCategory"] = category["id"]
    project["productivityCategoryLabel"] = category["label"]
    project["productivityCategoryDescription"] = category["description"]
    return enrich_discovery_score(project)


def github_project_key(project: dict[str, Any]) -> str:
    project_id = int(project.get("id") or 0)
    if project_id:
        return f"id:{project_id}"
    full_name = str(project.get("fullName") or project.get("full_name") or "").strip().casefold()
    return f"name:{full_name}" if full_name else ""


def github_legacy_category_id(project: dict[str, Any], classification: dict[str, Any]) -> str:
    full_name = str(project.get("fullName") or project.get("full_name") or "").casefold()
    combined = " ".join(
        [
            full_name,
            str(project.get("description") or "").casefold(),
            *(str(topic).casefold() for topic in (project.get("topics") or [])),
        ]
    )
    override = GITHUB_PROJECT_CATEGORY_OVERRIDES.get(full_name)
    if override:
        return override
    if any(phrase in combined for phrase in ("code review", "context engineering", "prompt engineering", "spec-driven")):
        return "dev-workflows"
    if classification.get("useStage") == "build" and any(
        phrase in combined
        for phrase in ("agent framework", "agent orchestration", "framework for building ai agents", "multi-agent framework")
    ):
        return "agent-frameworks"
    return str(classification.get("legacyCategory") or "coding-agents")


def classify_github_productivity_category(project: dict[str, Any]) -> tuple[str, str, str] | None:
    classification = classify_ai_project(project)
    if classification["useStage"] == "train_research":
        return None
    category_id = github_legacy_category_id(project, classification)
    category = GITHUB_PRODUCTIVITY_CATEGORY_BY_ID.get(category_id)
    if not category:
        return None
    return category["id"], category["label"], category["description"]


def select_github_productivity_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates_by_key: dict[str, dict[str, Any]] = {}
    for source_project in projects:
        project = dict(source_project)
        project_key = github_project_key(project)
        if not project_key:
            continue
        classification = classify_ai_project(project)
        classification["legacyCategory"] = github_legacy_category_id(project, classification)
        project.update(classification)
        category = GITHUB_PRODUCTIVITY_CATEGORY_BY_ID[classification["legacyCategory"]]
        project["productivityCategory"] = category["id"]
        project["productivityCategoryLabel"] = category["label"]
        project["productivityCategoryDescription"] = category["description"]
        project = enrich_discovery_score(project)
        if not project_meets_star_selection(project):
            continue
        project["selectionBasis"] = project_star_selection_basis(project)
        existing = candidates_by_key.get(project_key)
        if not existing or (
            int(project.get("stars") or 0),
            int(project.get("stars7dDelta") or 0),
            int(project.get("stars30dDelta") or 0),
        ) > (
            int(existing.get("stars") or 0),
            int(existing.get("stars7dDelta") or 0),
            int(existing.get("stars30dDelta") or 0),
        ):
            candidates_by_key[project_key] = project

    sort_key = lambda project: (
        int(project.get("stars") or 0),
        int(project.get("stars7dDelta") or 0) if project.get("historyStatus") == "ready" else 0,
        int(project.get("stars30dDelta") or 0) if project.get("historyStatus") == "ready" else 0,
        int(project.get("forks") or 0),
    )
    category_ids = [category["id"] for category in GITHUB_PRODUCTIVITY_CATEGORIES]
    candidates = list(candidates_by_key.values())
    default_projects = sorted((project for project in candidates if project_is_default_visible(project)), key=sort_key, reverse=True)
    hidden_projects = sorted((project for project in candidates if not project_is_default_visible(project)), key=sort_key, reverse=True)
    default_limit = min(len(default_projects), 110)
    hidden_limit = min(len(hidden_projects), MAX_GITHUB_PROJECTS - default_limit)
    ranked = sorted(
        [*default_projects[:default_limit], *hidden_projects[:hidden_limit]],
        key=sort_key,
        reverse=True,
    )[:MAX_GITHUB_PROJECTS]
    category_ranks = {category_id: 0 for category_id in category_ids}
    for rank, project in enumerate(ranked, start=1):
        project["rank"] = rank
        category_id = str(project.get("productivityCategory") or "")
        category_ranks[category_id] = category_ranks.get(category_id, 0) + 1
        project["categoryRank"] = category_ranks[category_id]
    return ranked


def build_ai_project_facets(projects: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts = {
        category["id"]: sum(1 for project in projects if project.get("productivityCategory") == category["id"])
        for category in GITHUB_PRODUCTIVITY_CATEGORIES
    }
    stage_counts = {
        stage_id: sum(1 for project in projects if project.get("useStage") == stage_id)
        for stage_id in USE_STAGE_META
    }
    capability_counts = {
        capability_id: sum(1 for project in projects if capability_id in (project.get("capabilityTags") or []))
        for capability_id in CAPABILITY_META
    }
    surface_counts = {
        surface_id: sum(1 for project in projects if surface_id in (project.get("deliverySurfaces") or []))
        for surface_id in SURFACE_META
    }
    return {
        "categories": [
            {
                "id": category["id"],
                "label": category["label"],
                "description": category["description"],
                "count": category_counts[category["id"]],
            }
            for category in GITHUB_PRODUCTIVITY_CATEGORIES
        ],
        "useStages": [
            {
                "id": stage_id,
                **stage_meta,
                "count": stage_counts[stage_id],
            }
            for stage_id, stage_meta in USE_STAGE_META.items()
        ],
        "capabilities": [
            {"id": capability_id, **meta, "count": capability_counts[capability_id]}
            for capability_id, meta in CAPABILITY_META.items()
        ],
        "deliverySurfaces": [
            {"id": surface_id, **meta, "count": surface_counts[surface_id]}
            for surface_id, meta in SURFACE_META.items()
        ],
        "discoveryViews": [
            {
                "id": "recommended",
                "label": "推荐",
                "count": sum(1 for project in projects if project_is_default_visible(project)),
            },
            {
                "id": "new",
                "label": "新项目",
                "count": sum(1 for project in projects if "recent" in (project.get("discoveryModes") or [])),
            },
            {
                "id": "rising",
                "label": "上升最快",
                "count": sum(1 for project in projects if int(project.get("stars7dDelta") or 0) > 0),
            },
            {"id": "followed", "label": "我的关注", "count": 0},
        ],
    }


def migrate_ai_projects_snapshot(
    data: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    if data.get("kind") != "ai-projects":
        return data
    source_version = int(data.get("schemaVersion") or 0)
    if source_version == AI_PROJECTS_SCHEMA_VERSION:
        return data
    if source_version > AI_PROJECTS_SCHEMA_VERSION:
        return data

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    migrated_projects: list[dict[str, Any]] = []
    for source_project in data.get("projects") or []:
        project = dict(source_project)
        classification = classify_ai_project(project)
        classification["legacyCategory"] = github_legacy_category_id(project, classification)
        project.update(classification)
        category = GITHUB_PRODUCTIVITY_CATEGORY_BY_ID[project["legacyCategory"]]
        project["productivityCategory"] = category["id"]
        project["productivityCategoryLabel"] = category["label"]
        project["productivityCategoryDescription"] = category["description"]
        migrated_projects.append(enrich_discovery_score(project, now=current))

    projects = select_github_productivity_projects(migrated_projects)
    summary = dict(data.get("summary") or {})
    summary.update(
        {
            "projectCount": len(projects),
            "defaultVisibleCount": sum(1 for project in projects if project_is_default_visible(project)),
            "hiddenByDefaultCount": sum(1 for project in projects if not project_is_default_visible(project)),
        }
    )
    return {
        **data,
        "schemaVersion": AI_PROJECTS_SCHEMA_VERSION,
        "migratedFromSchemaVersion": source_version,
        "sort": "total-stars-then-growth",
        "selectionCriteria": {
            "minTotalStars": AI_PROJECT_MIN_TOTAL_STARS,
            "min7dStarGrowth": AI_PROJECT_MIN_7D_STAR_GROWTH,
            "min30dStarGrowth": AI_PROJECT_MIN_30D_STAR_GROWTH,
            "requiresReadyHistoryForGrowth": True,
        },
        **build_ai_project_facets(projects),
        "summary": summary,
        "projects": projects,
        "hasData": bool(projects),
    }


def classify_github_project(project: dict[str, Any]) -> tuple[str, str]:
    classification = classify_ai_project(project)
    return classification["projectType"], classification["projectTypeDescription"]


async def read_memory_cache(
    cache: dict[str, Any],
    lock: asyncio.Lock,
    refresh: bool,
    force: bool,
) -> dict[str, Any] | None:
    async with lock:
        if not force and cache["data"] and datetime.now(UTC) < cache["expires_at"]:
            data = dict(cache["data"])
            data.update({"cached": True, "fromStorage": False, "throttled": refresh, "stale": False})
            return data
    return None


async def write_memory_cache(cache: dict[str, Any], lock: asyncio.Lock, data: dict[str, Any], ttl_seconds: int) -> None:
    async with lock:
        cache["data"] = dict(data)
        cache["expires_at"] = datetime.now(UTC) + timedelta(seconds=ttl_seconds)


async def use_stored_snapshot(
    stored: dict[str, Any],
    cache: dict[str, Any],
    lock: asyncio.Lock,
    ttl_seconds: int,
    refresh: bool,
    fresh: bool,
) -> dict[str, Any]:
    data = dict(stored)
    data.update({"cached": True, "fromStorage": True, "throttled": refresh, "stale": not fresh})
    async with lock:
        cache["data"] = dict(data)
        cache["expires_at"] = snapshot_expires_at(data, ttl_seconds)
    return data


async def load_snapshot(db_path: Path, table: str) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_snapshot_sync, db_path, table)


async def save_snapshot(db_path: Path, table: str, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_snapshot_sync, db_path, table, data)


async def record_ai_project_history(
    db_path: Path,
    projects: list[dict[str, Any]],
    observed_at: datetime | None = None,
) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(record_ai_project_history_sync, db_path, projects, observed_at)


async def load_ai_project_history(
    db_path: Path,
    project_keys: list[str],
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    async with DB_LOCK:
        return await asyncio.to_thread(load_ai_project_history_sync, db_path, project_keys, now)


def ensure_ai_project_history_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_project_history (
                project_key TEXT NOT NULL,
                observed_date TEXT NOT NULL,
                stars INTEGER NOT NULL,
                forks INTEGER NOT NULL,
                pushed_at TEXT NOT NULL,
                release_at TEXT NOT NULL,
                release_tag TEXT NOT NULL,
                PRIMARY KEY (project_key, observed_date)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_project_history_date ON ai_project_history(observed_date)"
        )


def record_ai_project_history_sync(
    db_path: Path,
    projects: list[dict[str, Any]],
    observed_at: datetime | None = None,
) -> None:
    observed = observed_at or datetime.now(UTC)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    observed = observed.astimezone(UTC)
    observed_date = observed.date().isoformat()
    retention_cutoff = (observed.date() - timedelta(days=120)).isoformat()
    rows = []
    for project in projects:
        project_key = github_project_key(project)
        if not project_key:
            continue
        release = project.get("release") if isinstance(project.get("release"), dict) else {}
        rows.append(
            (
                project_key,
                observed_date,
                int(project.get("stars") or 0),
                int(project.get("forks") or 0),
                str(project.get("pushedAt") or ""),
                str(release.get("publishedAt") or ""),
                str(release.get("tag") or ""),
            )
        )
    ensure_ai_project_history_table(db_path)
    with sqlite3.connect(db_path) as connection:
        if rows:
            connection.executemany(
                """
                INSERT INTO ai_project_history (
                    project_key, observed_date, stars, forks, pushed_at, release_at, release_tag
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_key, observed_date) DO UPDATE SET
                    stars = excluded.stars,
                    forks = excluded.forks,
                    pushed_at = excluded.pushed_at,
                    release_at = excluded.release_at,
                    release_tag = excluded.release_tag
                """,
                rows,
            )
        connection.execute("DELETE FROM ai_project_history WHERE observed_date < ?", (retention_cutoff,))


def load_ai_project_history_sync(
    db_path: Path,
    project_keys: list[str],
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    unique_keys = list(dict.fromkeys(key for key in project_keys if key))
    result = {key: [] for key in unique_keys}
    if not unique_keys or not db_path.exists():
        return result
    ensure_ai_project_history_table(db_path)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    cutoff = (current.astimezone(UTC).date() - timedelta(days=120)).isoformat()
    with sqlite3.connect(db_path) as connection:
        for offset in range(0, len(unique_keys), 500):
            chunk = unique_keys[offset : offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT project_key, observed_date, stars, forks, pushed_at, release_at, release_tag
                FROM ai_project_history
                WHERE observed_date >= ? AND project_key IN ({placeholders})
                ORDER BY observed_date ASC
                """,
                (cutoff, *chunk),
            ).fetchall()
            for project_key, observed_date, stars, forks, pushed_at, release_at, release_tag in rows:
                result[project_key].append(
                    {
                        "observedDate": observed_date,
                        "stars": stars,
                        "forks": forks,
                        "pushedAt": pushed_at,
                        "releaseAt": release_at,
                        "releaseTag": release_tag,
                    }
                )
    return result


def load_snapshot_sync(db_path: Path, table: str) -> dict[str, Any] | None:
    validate_table_name(table)
    if not db_path.exists():
        return None
    ensure_snapshot_table(db_path, table)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(f"SELECT payload_json FROM {table} WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


def save_snapshot_sync(db_path: Path, table: str, data: dict[str, Any]) -> None:
    validate_table_name(table)
    ensure_snapshot_table(db_path, table)
    payload = prune_snapshot(data)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DELETE FROM {table} WHERE id <> 1")
        conn.execute(
            f"""
            INSERT INTO {table} (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (
                payload.get("generatedAt", ""),
                payload.get("savedAt", ""),
                payload.get("expiresAt", ""),
                encoded,
            ),
        )


def ensure_snapshot_table(db_path: Path, table: str) -> None:
    validate_table_name(table)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def prune_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    payload.pop("cached", None)
    payload.pop("fromStorage", None)
    payload.pop("stale", None)
    payload.pop("throttled", None)
    if payload.get("kind") == "ai-news":
        payload["items"] = list(payload.get("items") or [])[:MAX_NEWS_ITEMS]
    elif payload.get("kind") == "ai-projects":
        payload["projects"] = list(payload.get("projects") or [])[:MAX_GITHUB_PROJECTS]
    return payload


def validate_table_name(table: str) -> None:
    if table not in {"latest_ai_news", "latest_ai_projects"}:
        raise ValueError(f"unsupported AI snapshot table: {table}")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_sqlite_path(config: dict[str, Any]) -> Path:
    path = Path(config.get("storage", {}).get("sqlite_path", "data/news.sqlite"))
    return path if path.is_absolute() else ROOT_DIR / path


def refresh_interval_seconds(config: dict[str, Any]) -> int:
    fetch = config.get("fetch", {})
    return max(600, int(fetch.get("min_refresh_interval_seconds", fetch.get("cache_ttl_seconds", 1800))))


def snapshot_is_valid(data: dict[str, Any] | None, kind: str) -> bool:
    expected_version = AI_PROJECTS_SCHEMA_VERSION if kind == "ai-projects" else AI_SCHEMA_VERSION
    return bool(data and data.get("schemaVersion") == expected_version and data.get("kind") == kind)


def snapshot_expires_at(data: dict[str, Any], ttl_seconds: int) -> datetime:
    saved_at = parse_datetime(data.get("savedAt"))
    expires_at = parse_datetime(data.get("expiresAt"))
    return max(expires_at, saved_at + timedelta(seconds=ttl_seconds))


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def parse_rss_datetime(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_source_suffix(title: str, source: str) -> str:
    suffix = f" - {source}" if source else ""
    if suffix and title.lower().endswith(suffix.lower()):
        return title[: -len(suffix)].strip()
    return title


def normalize_title(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def has_chinese(value: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


async def translate_many_to_chinese(texts: list[str], max_output_chars: int = 160) -> dict[str, str]:
    unique_texts = list(dict.fromkeys(clean_text(text)[:600] for text in texts if clean_text(text) and not has_chinese(text)))
    translated: dict[str, str] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsDigestAI/1.0)",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": "https://translate.google.com/",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=httpx.Timeout(12.0)) as client:
        coordinate_httpx_client(client)
        for index in range(0, len(unique_texts), 6):
            batch = unique_texts[index : index + 6]
            try:
                batch_result = await translate_text_batch(client, batch, max_output_chars)
            except Exception:
                batch_result = {}
            for text in batch:
                value = batch_result.get(text, "")
                if not has_chinese(value):
                    try:
                        value = (await translate_text_batch(client, [text], max_output_chars)).get(text, "")
                    except Exception:
                        value = ""
                if has_chinese(value):
                    translated[text] = value
    return translated


async def translate_text_batch(client: httpx.AsyncClient, texts: list[str], max_output_chars: int) -> dict[str, str]:
    if not texts:
        return {}
    response = await client.get(
        TRANSLATE_API,
        params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": "\n".join(texts)},
    )
    response.raise_for_status()
    payload = response.json()
    pieces = payload[0] if payload and isinstance(payload[0], list) else []
    joined = "".join(str(piece[0]) for piece in pieces if piece and piece[0])
    lines = [clean_text(line) for line in joined.splitlines() if clean_text(line)]
    if len(lines) != len(texts):
        if len(texts) == 1 and clean_text(joined):
            lines = [clean_text(joined)]
        else:
            raise RuntimeError("translation batch line mismatch")
    return {text: line[:max_output_chars] for text, line in zip(texts, lines, strict=False) if has_chinese(line)}


def fallback_project_annotation(project: dict[str, Any]) -> str:
    language = project.get("language") or "多种语言"
    topics = [topic_label(topic) for topic in (project.get("topics") or [])[:3]]
    category = project.get("productivityCategoryLabel") or "AI 开发效率"
    focus = "、".join(dict.fromkeys(topic for topic in topics if topic)) or category
    return f"这是一个使用{language}开发的{category}开源项目，主要聚焦{focus}。"


def curated_project_annotation(project: dict[str, Any]) -> str:
    return CURATED_PROJECT_ANNOTATIONS.get(str(project.get("fullName") or "").casefold(), "")


def concise_project_annotation(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    first_sentence = re.split(r"(?<=[。！？!?])\s*", text, maxsplit=1)[0]
    concise = first_sentence[:110].rstrip("，,；;：: -")
    if concise and concise[-1] not in "。！？!?":
        concise += "。"
    return concise


def topic_label(topic: str) -> str:
    labels = {
        "artificial-intelligence": "人工智能",
        "machine-learning": "机器学习",
        "deep-learning": "深度学习",
        "large-language-models": "大语言模型",
        "generative-ai": "生成式 AI",
        "computer-vision": "计算机视觉",
        "natural-language-processing": "自然语言处理",
        "reinforcement-learning": "强化学习",
        "agents": "智能体",
        "chatgpt": "ChatGPT 应用",
    }
    return labels.get(str(topic).casefold(), "")


def is_low_quality_ai_title(value: str) -> bool:
    title = value.strip()
    if len(normalize_title(title)) < 8:
        return True
    if re.fullmatch(r"[A-Z0-9_\- ]{8,}", title):
        return True
    lowered = title.casefold()
    return any(marker in lowered for marker in ("meta_title", "page_title", "untitled document"))


def canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def epoch_to_iso(value: Any) -> str:
    epoch = safe_int(value)
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def short_error(error: BaseException) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        detail = ""
        try:
            detail = str(response.json().get("message") or "")
        except (json.JSONDecodeError, AttributeError, TypeError):
            detail = ""
        return f"{response.request.url.host} {response.status_code}{f': {detail}' if detail else ''}"
    message = str(error).strip()
    return message[:300] if message else type(error).__name__
