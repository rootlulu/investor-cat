# news-digest-web

本地财经 / 新闻 / 游戏数据看板。后端 FastAPI + Python，前端 React 19 + Vite。

## 目录结构

- `src/*.py` — 后端服务（各业务一个 `service` 文件，路由聚合在 `src/app.py`）
- `frontend/` — React 前端（`frontend/src/App.jsx` 为单文件多页面）
- `config/` — 数据源清单与抓取配置（`game_region_watchlist.json`、`browser_settings.json` 等）
- `tests/` — Python 单测

## 游戏专区

游戏页将数据源分区展示：`Steam 专区` 只承载 Steam 热销榜/在线人数，`Sensor Tower 专区`
承载预估流水与官方/媒体披露，点点/七麦国家榜继续使用独立「榜单」子 tab。各专区独立加载、刷新和显示错误。

`Steam 专区`：

- **热销榜**：所选地区（全球 + 30 个国家/地区，共 31 个）的 Steam 热销榜排名，取自
  `store.steampowered.com/charts/topselling/{cc}`。
- **在线人数趋势**：固定游戏清单的全球并发口径（SteamCharts 月度均值/峰值 + Steam 当前在线 API
  实时并发）。
- 固定清单见 `config/game_region_watchlist.json`（`games[].appId/name/nameZh/publisher/group/platforms`，
  `regions[].code/name`）。
- 手游（原神 / 王者荣耀 / 心动小镇）无 Steam appId，以 `appId: null` 保留为「未披露」行，
  在线/热销显示「—」，不伪造数据。
- 数据按地区缓存于 SQLite `latest_games_region` 表，默认半小时最小刷新间隔；来源失败保留上次
  有效快照并标记 stale。

## 模拟浏览器抓取（重要）

所有对外抓取（Steam / 雪球 / 三方数据）统一走 **`src/browser_service.py` 的模拟浏览器**
（Playwright Chromium 持久化上下文）。**禁止裸 httpx 直连**——此前直连已被 Steam 风控封 IP。

`browser_service` 负责：

- 进程级单例浏览器会话，`fetch_html_via_browser` / `fetch_json_via_browser` 通过
  `asyncio.to_thread` 包装同步调用，失败自动重试并重置会话。
- 浏览器参数来自 `config/browser_settings.json`。
- 错误统一映射为中文可读信息（`summarize_browser_error`）。

各业务服务（`game_region_service` / `xueqiu_service` / `game_provider_service`）只调用
`browser_service`，不直接启动浏览器。

### 环境准备

```bash
# 安装 Playwright Chromium（仅需一次）
playwright install chromium

# 若部署机缺少系统库，在 config/browser_settings.json 设 libraryPath，
# browser_service 会自动注入 LD_LIBRARY_PATH
```

`config/browser_settings.json` 关键字段：

```json
{
  "enabled": true,
  "headless": true,
  "channel": "chromium",
  "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/125.0.0.0 Safari/537.36",
  "locale": "zh-CN",
  "timezoneId": "Asia/Shanghai",
  "viewport": { "width": 1280, "height": 900 },
  "args": ["--no-sandbox", "--disable-dev-shm-usage"],
  "timeoutMs": 20000,
  "waitMs": 1000,
  "profileDir": "data/browser-profile",
  "libraryPath": "data/playwright-libs/usr/lib/x86_64-linux-gnu",
  "proxy": {
    "enabled": true,
    "server": "",
    "autoDetectWslHost": true,
    "port": 7897,
    "hosts": ["store.steampowered.com"]
  }
}
```

代理仅匹配 `proxy.hosts`。`autoDetectWslHost` 只读取 WSL 默认网关，不修改 WSL/Windows 网络配置；
`BROWSER_PROXY_SERVER` 可覆盖自动生成的代理地址。用户名/密码分别通过
`BROWSER_PROXY_USERNAME` / `BROWSER_PROXY_PASSWORD` 提供，禁止写入仓库。

## 雪球大V研究

`/xueqiu` 保留原有近 7 天动态，并新增「大V研究」子 tab。它可以为已导入的大V启动全量、
继续或增量抓取，将该用户本人发布的帖子、转发、评论和回复保存到独立语料库
`data/xueqiu_research.sqlite`。任务按页持久化断点，登录失效或风控时暂停，重新登录后可继续；
删除近 7 天列表中的大V不会自动删除已保存的研究语料。

后端实现位于 `src/xueqiu_research_service.py`，研究 API 以 `/api/xueqiu/research` 为前缀。
启动抓取和取消任务必须携带本机动作头 `X-Xueqiu-Research-Action: 1`，Cookie、浏览器 profile
和凭据不会通过 API、MCP 或日志返回。

Codex 通过项目级 stdio MCP 检索这些语料。MCP 使用独立依赖环境，避免影响主 FastAPI：

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/python -m pip install -r requirements-mcp.txt
```

`.codex/config.toml` 已注册 `xueqiu_research`，默认连接 `http://127.0.0.1:5173`。如后端端口不同，
修改其中的 `NEWS_DIGEST_BASE_URL`；只允许 localhost 地址。分析时应先检查语料覆盖状态，再用
`search_xueqiu_evidence` 和 `read_xueqiu_evidence` 读取证据，并为关键数字保留雪球原文链接；
覆盖不完整或没有直接证据时必须明确说明，不能把“未检索到”解释成“大V没有说过”。

## 运行

```bash
# 后端
uvicorn src.app:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev

# 单测
pytest tests/ -q
```

## 说明

- 股票 / 宏观 / 大宗等页面逻辑见 `src/*_service.py` 与 `SPEC.md`。
- 游戏区域子 tab 的完整规范与任务清单见 `SPEC.md` 的「§G/§C/§I/§V/§T（游戏区域）」与「§Browser」。
