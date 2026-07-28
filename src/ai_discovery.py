from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any


AI_PROJECT_MIN_TOTAL_STARS = 1_000
AI_PROJECT_MIN_7D_STAR_GROWTH = 100
AI_PROJECT_MIN_30D_STAR_GROWTH = 500


USE_STAGE_META = {
    "ready": {
        "label": "直接可用",
        "description": "可通过 Web、桌面端、CLI 或编辑器直接完成任务。",
        "defaultVisible": True,
    },
    "integrate": {
        "label": "安装即用",
        "description": "Skills、插件或 MCP Server，完成少量配置后即可使用。",
        "defaultVisible": True,
    },
    "build": {
        "label": "开发组件",
        "description": "SDK、框架、库或基础设施，主要用于二次开发。",
        "defaultVisible": False,
    },
    "train_research": {
        "label": "训练研究",
        "description": "模型训练、微调、张量计算或专业机器学习研究工具。",
        "defaultVisible": False,
    },
    "resource": {
        "label": "教程资料",
        "description": "课程、教程、示例、论文实现或 Awesome 合集。",
        "defaultVisible": False,
    },
}

CAPABILITY_META = {
    "programming": {"label": "编程开发"},
    "research": {"label": "搜索研究"},
    "office": {"label": "办公内容"},
    "automation": {"label": "浏览器 / 自动化"},
    "creative": {"label": "图像音视频"},
    "data": {"label": "数据分析"},
    "local_privacy": {"label": "本地 / 隐私"},
    "agent_extensions": {"label": "AI 扩展"},
    "context_memory": {"label": "上下文 / 记忆"},
}

SURFACE_META = {
    "application": {"label": "应用"},
    "web": {"label": "Web"},
    "desktop": {"label": "桌面端"},
    "cli": {"label": "CLI"},
    "browser_extension": {"label": "浏览器插件"},
    "ide_extension": {"label": "IDE 插件"},
    "plugin": {"label": "插件"},
    "skill": {"label": "Skill"},
    "mcp_server": {"label": "MCP Server"},
    "api": {"label": "API"},
    "sdk": {"label": "SDK"},
    "library": {"label": "库 / 框架"},
    "docker": {"label": "Docker"},
    "resource": {"label": "资料"},
}

PROJECT_STAGE_OVERRIDES = {
    "aider-ai/aider": "ready",
    "anomalyco/opencode": "ready",
    "anthropics/claude-code": "ready",
    "anthropics/skills": "integrate",
    "automatic1111/stable-diffusion-webui": "ready",
    "browser-use/browser-use": "ready",
    "cline/cline": "ready",
    "crewaiinc/crewai": "build",
    "google-gemini/gemini-cli": "ready",
    "huggingface/transformers": "train_research",
    "langchain-ai/deepagents": "build",
    "langchain-ai/langchain": "build",
    "langchain-ai/langgraph": "build",
    "microsoft/ai-agents-for-beginners": "resource",
    "microsoft/autogen": "build",
    "modelcontextprotocol/python-sdk": "build",
    "modelcontextprotocol/servers": "integrate",
    "modelcontextprotocol/typescript-sdk": "build",
    "ollama/ollama": "ready",
    "open-webui/open-webui": "ready",
    "openai/codex": "ready",
    "openhands/openhands": "ready",
    "pytorch/pytorch": "train_research",
    "tensorflow/tensorflow": "train_research",
}

RESOURCE_TOKENS = {
    "awesome",
    "awesome-list",
    "checklist",
    "cookbook",
    "course",
    "courses",
    "for-beginners",
    "from-scratch",
    "guide",
    "learning",
    "lessons",
    "roadmap",
    "tutorial",
    "tutorials",
}

TRAINING_TOPICS = {
    "automatic-differentiation",
    "deep-learning-framework",
    "distributed-training",
    "finetuning",
    "machine-learning-framework",
    "model-training",
    "neural-network",
    "pretraining",
    "scientific-computing",
    "tensor",
}


def build_github_search_specs(now: datetime | None = None) -> list[dict[str, Any]]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    recent_cutoff = (current - timedelta(days=180)).date().isoformat()
    pushed_cutoff = (current - timedelta(days=45)).date().isoformat()
    popular = [
        ("programming", '"AI coding assistant"'),
        ("research", '"AI research assistant"'),
        ("research", '"AI knowledge base"'),
        ("office", '"AI writing assistant"'),
        ("automation", '"AI browser automation"'),
        ("creative", '"AI image generator"'),
        ("data", '"AI data analysis"'),
        ("local_privacy", '"local AI assistant"'),
        ("agent_extensions", '"agent skills" OR "Model Context Protocol"'),
    ]
    specs = [
        {
            "id": source_id,
            "mode": "popular",
            "query": query,
            "sort": "stars",
            "order": "desc",
            "minStars": 20,
        }
        for source_id, query in popular
    ]
    specs.append(
        {
            "id": "recent",
            "mode": "recent",
            "query": f'"AI tool" created:>={recent_cutoff} pushed:>={pushed_cutoff}',
            "sort": "updated",
            "order": "desc",
            "minStars": 5,
        }
    )
    return specs


def classify_ai_project(project: dict[str, Any]) -> dict[str, Any]:
    full_name = str(project.get("fullName") or project.get("full_name") or "").strip()
    full_name_folded = full_name.casefold()
    description = str(project.get("description") or "")
    topics = {str(topic).casefold() for topic in (project.get("topics") or []) if str(topic).strip()}
    combined = " ".join([full_name_folded, description.casefold(), *sorted(topics)])
    name_tokens = {token for token in re.split(r"[^a-z0-9]+", full_name_folded) if token}

    surfaces = _infer_surfaces(combined, topics, name_tokens)
    capabilities = _infer_capabilities(combined, topics)
    reasons: list[str] = []

    override = PROJECT_STAGE_OVERRIDES.get(full_name_folded)
    resource_signal = bool(RESOURCE_TOKENS & (topics | name_tokens)) or any(
        phrase in combined
        for phrase in (
            "for beginners",
            "from scratch",
            "step-by-step tutorial",
            "course with lessons",
            "awesome list",
            "curated list",
            "prompt engineering guide",
        )
    )
    training_signal = bool(TRAINING_TOPICS & topics) or any(
        phrase in combined
        for phrase in (
            "automatic differentiation",
            "deep learning framework",
            "distributed training",
            "framework for training",
            "machine learning framework",
            "model training",
            "pretraining framework",
            "train neural networks",
        )
    )
    build_signal = bool({"agent-framework", "agent-frameworks", "framework", "library", "sdk"} & topics) or any(
        phrase in combined
        for phrase in (
            "agent framework",
            "agent orchestration",
            "developer platform",
            "framework for building",
            "library for",
            "multi-agent framework",
            "observability",
            "sdk for",
        )
    )
    integration_signal = bool({"skill", "mcp_server", "plugin"} & surfaces)
    direct_surface = bool({"application", "web", "desktop", "cli", "browser_extension", "ide_extension"} & surfaces)
    direct_task_signal = any(
        phrase in combined
        for phrase in (
            "ai agent",
            "assistant",
            "browser agent",
            "coding agent",
            "desktop app",
            "image generator",
            "local ai",
            "research agent",
            "terminal agent",
            "web app",
            "writing agent",
        )
    )

    if override:
        stage = override
        reasons.append("已审核项目规则")
        confidence = 0.98
    elif resource_signal:
        stage = "resource"
        reasons.append("教程、课程、清单或合集")
        confidence = 0.9
    elif training_signal and not direct_surface:
        stage = "train_research"
        reasons.append("模型训练或专业机器学习框架")
        confidence = 0.9
    elif integration_signal and "sdk" not in surfaces:
        stage = "integrate"
        reasons.append("可安装的 Skill、插件或 MCP Server")
        confidence = 0.86
    elif direct_surface and direct_task_signal:
        stage = "ready"
        reasons.append("存在面向用户的可运行入口")
        confidence = 0.84
    elif build_signal or "sdk" in surfaces or "library" in surfaces:
        stage = "build"
        reasons.append("主要面向二次开发")
        confidence = 0.78
    elif direct_task_signal:
        stage = "ready"
        reasons.append("描述明确承诺可完成用户任务")
        confidence = 0.68
    else:
        stage = "build"
        reasons.append("未发现可直接使用入口，按开发组件收纳")
        confidence = 0.62

    if stage == "resource":
        surfaces.add("resource")
    elif stage == "train_research" and not surfaces:
        surfaces.add("library")
    elif stage == "build" and not surfaces:
        surfaces.add("library")
    elif stage == "ready" and not surfaces:
        surfaces.add("application")

    if not capabilities:
        if stage in {"build", "train_research", "resource"}:
            capabilities.add("programming")
        else:
            capabilities.add("automation")

    if "cli" in surfaces:
        reasons.append("提供 CLI / 终端入口")
    if "web" in surfaces:
        reasons.append("提供 Web 界面")
    if "mcp_server" in surfaces:
        reasons.append("支持 MCP")
    if "skill" in surfaces:
        reasons.append("提供 Agent Skill")

    legacy_category = _legacy_category(stage, surfaces, capabilities)
    stage_meta = USE_STAGE_META[stage]
    ordered_capabilities = [key for key in CAPABILITY_META if key in capabilities]
    ordered_surfaces = [key for key in SURFACE_META if key in surfaces]
    return {
        "useStage": stage,
        "useStageLabel": stage_meta["label"],
        "useStageDescription": stage_meta["description"],
        "defaultVisible": bool(stage_meta["defaultVisible"]),
        "capabilityTags": ordered_capabilities,
        "capabilityLabels": [CAPABILITY_META[key]["label"] for key in ordered_capabilities],
        "deliverySurfaces": ordered_surfaces,
        "deliverySurfaceLabels": [SURFACE_META[key]["label"] for key in ordered_surfaces],
        "classificationReasons": list(dict.fromkeys(reasons)),
        "classificationConfidence": round(confidence, 2),
        "legacyCategory": legacy_category,
        "projectType": stage_meta["label"],
        "projectTypeDescription": stage_meta["description"],
    }


def project_is_default_visible(project: dict[str, Any]) -> bool:
    stage = str(project.get("useStage") or "")
    return bool(USE_STAGE_META.get(stage, {}).get("defaultVisible"))


def project_star_selection_basis(project: dict[str, Any]) -> list[str]:
    basis: list[str] = []
    if max(0, int(project.get("stars") or 0)) >= AI_PROJECT_MIN_TOTAL_STARS:
        basis.append("total-stars")
    if project.get("historyStatus") != "ready":
        return basis
    if max(0, int(project.get("stars7dDelta") or 0)) >= AI_PROJECT_MIN_7D_STAR_GROWTH:
        basis.append("7d-growth")
    if max(0, int(project.get("stars30dDelta") or 0)) >= AI_PROJECT_MIN_30D_STAR_GROWTH:
        basis.append("30d-growth")
    return basis


def project_meets_star_selection(project: dict[str, Any]) -> bool:
    return bool(project_star_selection_basis(project))


def enrich_discovery_score(project: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    result = dict(project)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    stage = str(result.get("useStage") or "build")
    surfaces = {str(value) for value in (result.get("deliverySurfaces") or [])}
    readme = result.get("readmeSignals") if isinstance(result.get("readmeSignals"), dict) else {}

    usability = {"ready": 60.0, "integrate": 48.0, "build": 18.0, "train_research": 5.0, "resource": 7.0}.get(stage, 10.0)
    if surfaces & {"web", "desktop", "cli", "browser_extension", "ide_extension", "application"}:
        usability += 14
    if surfaces & {"skill", "mcp_server", "plugin"}:
        usability += 10
    if result.get("homepage"):
        usability += 6
    if readme.get("hasInstall"):
        usability += 8
    if readme.get("hasQuickstart"):
        usability += 7
    if readme.get("hasDemo"):
        usability += 5
    usability = min(100.0, usability)

    stars = max(0, int(result.get("stars") or 0))
    star_credibility = min(10.0, math.log1p(stars) / math.log1p(10_000) * 10.0)
    quality = star_credibility
    quality += 18 if result.get("license") else 0
    quality += 12 if result.get("homepage") else 0
    quality += 14 if readme.get("hasInstall") else 0
    quality += 12 if readme.get("hasQuickstart") else 0
    quality += 10 if readme.get("hasDemo") else 0
    quality += 14 if result.get("release", {}).get("publishedAt") else 0
    quality = min(100.0, quality)

    pushed_at = _parse_datetime(result.get("pushedAt"))
    release_at = _parse_datetime((result.get("release") or {}).get("publishedAt"))
    freshness_source = release_at or pushed_at
    if freshness_source:
        age_days = max(0.0, (current - freshness_source).total_seconds() / 86_400)
        half_life = 180.0 if release_at else 120.0
        freshness = 100.0 * (2 ** (-age_days / half_life))
    else:
        freshness = 0.0

    history_ready = result.get("historyStatus") == "ready"
    delta7 = max(0, int(result.get("stars7dDelta") or 0))
    delta30 = max(0, int(result.get("stars30dDelta") or 0))
    if history_ready:
        momentum = min(
            100.0,
            60.0 * math.log1p(delta7) / math.log1p(1_000)
            + 40.0 * math.log1p(delta30) / math.log1p(5_000),
        )
    else:
        momentum = 0.0

    discovery_score = 0.4 * usability + 0.25 * momentum + 0.2 * freshness + 0.15 * quality
    why: list[str] = []
    if stage == "ready":
        why.append("可直接使用")
    elif stage == "integrate":
        why.append("安装配置后即可使用")
    if readme.get("hasQuickstart"):
        why.append("README 提供 Quickstart")
    if release_at:
        why.append(f"最近发布于 {release_at.date().isoformat()}")
    if history_ready and delta7 > 0:
        why.append(f"近 7 天 +{delta7:,} Stars")
    elif history_ready and delta30 > 0:
        why.append(f"近 30 天 +{delta30:,} Stars")
    elif pushed_at:
        why.append(f"最近推送于 {pushed_at.date().isoformat()}")

    result["scoreBreakdown"] = {
        "usability": round(usability, 1),
        "quality": round(quality, 1),
        "freshness": round(freshness, 1),
        "momentum": round(momentum, 1),
        "starCredibility": round(star_credibility, 1),
    }
    result["discoveryScore"] = round(discovery_score, 1)
    result["whyRecommended"] = why[:4]
    return result


def apply_project_history(
    project: dict[str, Any],
    history_rows: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    result = dict(project)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    current_stars = int(result.get("stars") or 0)

    def delta_for(days: int) -> int | None:
        cutoff = current - timedelta(days=days)
        eligible = [
            row
            for row in history_rows
            if (_parse_datetime(row.get("observedAt") or row.get("observedDate")) or datetime.max.replace(tzinfo=UTC))
            <= cutoff
        ]
        if not eligible:
            return None
        baseline = max(
            eligible,
            key=lambda row: _parse_datetime(row.get("observedAt") or row.get("observedDate"))
            or datetime.min.replace(tzinfo=UTC),
        )
        return current_stars - int(baseline.get("stars") or 0)

    delta7 = delta_for(7)
    delta30 = delta_for(30)
    result["stars7dDelta"] = delta7
    result["stars30dDelta"] = delta30
    result["historyStatus"] = "ready" if delta7 is not None and delta30 is not None else "collecting"
    result["historySamples"] = len(history_rows)
    return result


def extract_readme_signals(readme_text: str) -> dict[str, bool]:
    text = str(readme_text or "").casefold()
    return {
        "hasInstall": bool(re.search(r"\b(installation|installing|install|setup)\b", text)),
        "hasQuickstart": bool(re.search(r"\b(quick[ -]?start|getting started|first steps?)\b", text)),
        "hasDemo": bool(
            re.search(r"\b(live demo|demo site|try it|playground|screenshot|video demo)\b", text)
            or re.search(r"https?://[^\s)\]]*(?:demo|playground)[^\s)\]]*", text)
        ),
    }


def select_enrichment_candidates(
    projects: list[dict[str, Any]],
    authenticated: bool,
) -> list[dict[str, Any]]:
    limit = 40 if authenticated else 12
    candidates: dict[str, dict[str, Any]] = {}
    for project in projects:
        full_name = str(project.get("fullName") or "").strip().casefold()
        if full_name and "/" in full_name:
            candidates.setdefault(full_name, project)
    never_checked = datetime.min.replace(tzinfo=UTC)
    return sorted(
        candidates.values(),
        key=lambda project: (
            _parse_datetime(project.get("enrichmentCheckedAt")) or never_checked,
            -int(bool(project.get("defaultVisible"))),
            -int("recent" in (project.get("discoveryModes") or [])),
            -int(project.get("stars") or 0),
            -int(project.get("stars7dDelta") or 0),
            -int(project.get("stars30dDelta") or 0),
        ),
    )[:limit]


def build_project_signals(project: dict[str, Any], now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    full_name = str(project.get("fullName") or "")
    project_key = full_name.strip().casefold()
    usable = project.get("useStage") in {"ready", "integrate"}
    events: list[dict[str, Any]] = []

    def add_event(event_type: str, fingerprint: str, title: str, reason: str, occurred_at: str, url: str = "") -> None:
        digest = hashlib.sha256(f"{full_name}|{event_type}|{fingerprint}".encode("utf-8")).hexdigest()[:20]
        events.append(
            {
                "eventId": f"ai:{event_type}:{digest}",
                "type": event_type,
                "projectKey": project_key,
                "fullName": full_name,
                "title": title,
                "reason": reason,
                "occurredAt": occurred_at,
                "url": url,
            }
        )

    release = project.get("release") if isinstance(project.get("release"), dict) else {}
    release_at = _parse_datetime(release.get("publishedAt"))
    stable_release = bool(
        release_at
        and not release.get("draft")
        and not release.get("prerelease")
        and 0 <= (current - release_at).total_seconds() <= 14 * 86_400
    )
    if stable_release:
        tag = str(release.get("tag") or release_at.date().isoformat())
        add_event(
            "release",
            tag,
            f"{full_name} 发布 {tag}",
            "最近发布了稳定版本",
            release_at.isoformat(),
            str(release.get("url") or project.get("url") or ""),
        )

    created_at = _parse_datetime(project.get("createdAt"))
    if created_at and 0 <= (current - created_at).total_seconds() <= 14 * 86_400 and int(project.get("stars") or 0) >= 50:
        add_event(
            "new-project",
            created_at.date().isoformat(),
            f"发现新项目 {full_name}",
            f"创建不久且已获得 {int(project.get('stars') or 0):,} Stars",
            created_at.isoformat(),
            str(project.get("url") or ""),
        )

    delta7 = int(project.get("stars7dDelta") or 0)
    delta30 = int(project.get("stars30dDelta") or 0)
    if project.get("historyStatus") == "ready" and (
        delta7 >= AI_PROJECT_MIN_7D_STAR_GROWTH
        or delta30 >= AI_PROJECT_MIN_30D_STAR_GROWTH
    ):
        observed = current.date().isoformat()
        add_event(
            "momentum",
            f"{observed}:{delta7}:{delta30}",
            f"{full_name} 热度快速上升",
            f"近 7 天 +{delta7:,}，近 30 天 +{delta30:,} Stars",
            current.isoformat(),
            str(project.get("url") or ""),
        )

    high = [{**event, "level": "high"} for event in events] if usable else []
    digest = [{**event, "level": "digest"} for event in events]
    return {"high": high, "digest": digest}


def _infer_surfaces(combined: str, topics: set[str], name_tokens: set[str]) -> set[str]:
    surfaces: set[str] = set()
    tokens = topics | name_tokens
    if "cli" in tokens or any(phrase in combined for phrase in ("command line", "command-line", "terminal")):
        surfaces.add("cli")
    if "desktop" in tokens or any(phrase in combined for phrase in ("desktop app", "electron app", "macos app", "windows app")):
        surfaces.add("desktop")
    if {"web-ui", "webapp", "web-app", "webui"} & tokens or any(
        phrase in combined for phrase in ("web app", "web interface", "web ui", "web-based")
    ):
        surfaces.add("web")
    if any(phrase in combined for phrase in ("browser extension", "chrome extension", "firefox add-on")):
        surfaces.add("browser_extension")
    if {"vscode-extension", "ide-extension"} & tokens or any(
        phrase in combined for phrase in ("ide extension", "jetbrains plugin", "visual studio code extension", "vscode extension")
    ):
        surfaces.add("ide_extension")
    if {"mcp-server", "mcp-servers"} & tokens or "model context protocol server" in combined or re.search(r"\bmcp server\b", combined):
        surfaces.add("mcp_server")
    elif "model context protocol" in combined or re.search(r"(?:^|[\s/_-])mcp(?:$|[\s/_-])", combined):
        surfaces.add("mcp_server")
    if {"agent-skills", "ai-skills", "claude-code-skills", "codex-skills", "skills"} & tokens or any(
        phrase in combined for phrase in ("agent skill", "claude code skill", "codex skill")
    ):
        surfaces.add("skill")
    if "plugin" in tokens or any(phrase in combined for phrase in ("browser plugin", "editor plugin", "plugin for")):
        surfaces.add("plugin")
    if "sdk" in tokens or re.search(r"\bsdk\b", combined):
        surfaces.add("sdk")
    if "api" in tokens or " api " in f" {combined} ":
        surfaces.add("api")
    if {"framework", "library"} & tokens or any(phrase in combined for phrase in ("framework for", "library for")):
        surfaces.add("library")
    if "docker" in tokens or any(phrase in combined for phrase in ("docker compose", "docker image", "self-hosted")):
        surfaces.add("docker")
    return surfaces


def _infer_capabilities(combined: str, topics: set[str]) -> set[str]:
    capabilities: set[str] = set()
    rules = {
        "programming": (
            {"coding-agent", "code-review", "developer-tools", "software-engineering"},
            ("code review", "coding", "developer", "github", "programming", "software engineering"),
        ),
        "research": (
            {"knowledge-base", "rag", "research-agent", "search-engine"},
            ("knowledge base", "pdf", "rag", "research", "search assistant", "web search"),
        ),
        "office": (
            {"productivity", "translation", "writing-assistant"},
            ("document", "email", "meeting", "office", "presentation", "spreadsheet", "translation", "writing"),
        ),
        "automation": (
            {"agentic-ai", "automation", "browser-agent", "workflow-automation"},
            ("agentic", "automation", "autonomous agent", "browser agent", "desktop automation", "workflow"),
        ),
        "creative": (
            {"image-generation", "speech-to-text", "text-to-speech", "video-generation"},
            ("audio", "design", "image generation", "music", "speech", "video generation", "voice"),
        ),
        "data": (
            {"analytics", "data-analysis", "sql"},
            ("analytics", "data analysis", "database", "finance", "financial", "sql"),
        ),
        "local_privacy": (
            {"local-ai", "offline", "privacy", "self-hosted"},
            ("local ai", "offline", "on-device", "privacy", "private", "self-hosted"),
        ),
        "agent_extensions": (
            {"agent-skills", "mcp", "mcp-server", "plugin"},
            ("agent skill", "model context protocol", "plugin for"),
        ),
        "context_memory": (
            {"agent-memory", "context-engineering", "prompt-engineering"},
            ("agent memory", "context engineering", "memory", "prompt engineering", "prompt library"),
        ),
    }
    for capability, (topic_tokens, phrases) in rules.items():
        if topic_tokens & topics or any(phrase in combined for phrase in phrases):
            capabilities.add(capability)
    return capabilities


def _legacy_category(stage: str, surfaces: set[str], capabilities: set[str]) -> str:
    if "skill" in surfaces:
        return "skills"
    if "mcp_server" in surfaces:
        return "mcp"
    if stage == "build" and "automation" in capabilities:
        return "agent-frameworks"
    if "context_memory" in capabilities:
        return "dev-workflows"
    return "coding-agents"


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
