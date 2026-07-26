from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_project_uses_one_unified_mcp_and_no_internal_investment_agent() -> None:
    config = (ROOT_DIR / ".codex" / "config.toml").read_text(encoding="utf-8")
    app_source = (ROOT_DIR / "src" / "app.py").read_text(encoding="utf-8")
    frontend = (ROOT_DIR / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

    assert config.count("[mcp_servers.") == 1
    assert "[mcp_servers.news_digest]" in config
    assert "src.news_digest_mcp_server" in config
    assert 'default_tools_approval_mode = "writes"' in config
    assert "investment_agent" not in app_source
    assert "/api/investment-agent" not in app_source
    assert "/api/investment-agent" not in frontend
    assert "xueqiu_research MCP" not in frontend
    assert "news_digest MCP" in frontend
    assert not (ROOT_DIR / "src" / "investment_agent.py").exists()


def test_xueqiu_page_requires_confirmation_and_does_not_claim_auto_analysis() -> None:
    frontend = (ROOT_DIR / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    start = frontend.index("const startCrawl")
    post = frontend.index("/api/xueqiu/research/influencers/", start)
    confirmation = frontend.index("window.confirm", start)
    rejection_guard = frontend.index("if (!confirmed) return", confirmation)
    busy_state = frontend.index("setBusyIds", confirmation)

    assert confirmation < rejection_guard < busy_state < post
    assert "抓取完成后项目不会自动分析" in frontend
    assert "请再向 Codex 发出分析指令" in frontend


def test_unified_mcp_has_fixed_local_paths_and_no_generic_proxy_tool() -> None:
    server = (ROOT_DIR / "src" / "news_digest_mcp_server.py").read_text(encoding="utf-8")

    assert 'if not path.startswith("/api/") or "://" in path' in server
    assert 'name="start_influencer_crawl"' in server
    assert 'name="sync_company_financials"' in server
    assert "arbitrary_url" not in server
    assert "generic_proxy" not in server
    assert "data_only_codex_analyzes" in server
