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

`Sensor Tower 专区`：

- 默认读取最近一个完整自然月的全球与中国移动游戏流水榜，目标各 100 条；页面同时显示精确美元金额、月份、采用来源、统计口径以及目标/可用/缺失数量。
- 同一游戏、市场和月份存在多来源时，优先级为：官方披露 > 权威媒体披露 > Sensor Tower 正式导出/授权 API > 公开估算转述。较低优先级金额保留为备选证据，不覆盖官方值。
- 授权 API Token 仅从服务端环境变量 `SENSORTOWER_AUTH_TOKEN` 读取；也可导入 `data/game_sensor_tower_revenue.csv/json` 与 `data/game_reported_revenue.csv/json`。公开模板位于 `examples/data/`，复制到本地 `data/` 后使用。
- 无授权数据时使用 GACHAREVENUE 的公开 Sensor Tower 转述兜底。该来源仅覆盖移动端且偏二游/抽卡游戏；中国 Android 按中国 iOS 估算的 `1.75` 倍推算（中国合计为 iOS 的 `2.75` 倍），不含 PC、主机和广告收入。
- 来源不足 100 条时保持真实缺口并显示原因，不用 0 或虚构游戏补榜；因此公开兜底下中国榜可能少于 100 条。

## AI 工具雷达

`/ai#github/recommended` 只纳入 Stars 总数至少 `1,000`，或历史已就绪且 7 天增长至少 `100`，或 30 天
增长至少 `500` 的项目；“采集中”不算增长依据。默认榜按 Stars 总数降序，“近期爆发”按真实 7/30 天
增长数排序；安装、Quickstart、Demo、新鲜度等只做说明，不参与入榜或排序，也不显示综合推荐分。

项目仍拆成“使用门槛、用途、产品形态”三个筛选维度。默认只显示“直接可用”和“安装即用”，开发组件、
训练研究和教程资料须由用户显式放出。固定发现视图包括“高 Stars、新上榜、近期爆发、已关注”；旧
`#github/skills`、`mcp` 等链接会在前端迁移为等价筛选。

项目、作者、用途关注与“不相关 / 这是框架”反馈保存在本机 `localStorage`，不调用 GitHub Star/Watch API。
系统通知必须由用户点击授权；未授权或浏览器不支持时仍保留页内提醒。SQLite 表 `ai_project_history`
每天记录所有有效候选的 Stars、Forks、推送与 Release，用真实历史样本计算 7/30 天增长；样本不足显示
“采集中”。每次刷新还会在有界额度内读取 latest Release 与 README 安装信号：匿名最多 24 个 core
requests，设置 `GITHUB_TOKEN` 后最多 80 个；失败保留上次有效 enrichment，不清空主榜。

## 模拟浏览器抓取（重要）

只有确实依赖网页渲染、Cookie 或交互验证的来源使用 Playwright；官方 API、RSS 和普通网页仍使用
`httpx` / `requests`。两类请求都统一经过 **`src/request_coordinator.py` 的域名级协调器**，避免多个页面
在启动或手工刷新时同时冲击同一来源。

服务每次启动仍会把全部已注册页面（含 Steam 区域全局页）各强制刷新一次，但启动任务最多同时运行
2 个并错峰开始。域名策略位于 `config/crawl_policy.json`：默认同域并发 1，并配置最小间隔、随机抖动、
有界网络/5xx 重试，以及 403、429、WAF、验证码触发的共享冷却；冷却期间不会立即切换 Session 或浏览器重试。

`browser_service` 负责：

- Steam 自动取数使用进程级单例、专用单线程 worker 和非持久 BrowserContext；
  `fetch_html_via_browser` / `fetch_json_via_browser` 通过 `asyncio.to_thread` 包装同步调用。
- 浏览器请求同样执行域名限速、风险响应熔断和有界退避；失败时重置会话。
- 浏览器参数来自 `config/browser_settings.json`。
- 错误统一映射为中文可读信息（`summarize_browser_error`）。

`game_region_service` 复用 `browser_service`；雪球与七麦/点点保留各自需要登录态的持久 profile，
并与普通 HTTP 路径共享同一个域名协调器。

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

`/xueqiu` 保留原有近 7 天动态，并新增「大V研究」子 tab。全量、继续或增量抓取只允许两种触发：
用户在页面二次确认，或 Codex 明确调用带写入审批的 MCP 工具。启动服务、打开页面、搜索语料和发起分析都不会隐式抓取。
抓取会将该用户本人发布的帖子、转发、评论和回复保存到独立语料库
`data/xueqiu_research.sqlite`。任务按页持久化断点，登录失效或风控时暂停，重新登录后可继续；
删除近 7 天列表中的大V不会自动删除已保存的研究语料。

后端实现位于 `src/xueqiu_research_service.py`，研究 API 以 `/api/xueqiu/research` 为前缀。
启动抓取和取消任务必须携带本机动作头 `X-Xueqiu-Research-Action: 1`，Cookie、浏览器 profile
和凭据不会通过 API、MCP 或日志返回。

Codex 通过项目级 stdio MCP 读取整个项目的数据并检索这些语料。MCP 使用独立依赖环境，避免影响主 FastAPI：

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/python -m pip install -r requirements-mcp.txt
```

`.codex/config.toml` 只注册一个 `news_digest` MCP，默认连接 `http://127.0.0.1:5173`。如后端端口不同，
修改其中的 `NEWS_DIGEST_BASE_URL`；只允许 localhost 地址。读工具只访问固定本地 API 路径；财报同步、雪球抓取和取消工具
标记为写动作，由 Codex 的 `writes` 审批策略处理。分析时应先检查语料覆盖状态，再用
`search_xueqiu_evidence` 和 `read_xueqiu_evidence` 读取证据，并为关键数字保留雪球原文链接；
覆盖不完整或没有直接证据时必须明确说明，不能把“未检索到”解释成“大V没有说过”。

项目本身不调用 LLM，也不生成观点、评级、买卖或仓位建议。页面触发抓取后只显示数据覆盖和任务状态；必须由用户再向 Codex
发出分析指令，Codex 才通过 MCP 读取证据并在 Codex 侧完成分析。

## 投资研究工作台与数据口径

- `/today` 只聚合已经保存的股票、大宗、能源与 AI 新闻快照；每个领域读取都有超时上限，单一来源卡住时
  首屏会降级显示健康与风险，不会同步等待完整外部刷新。
- 今日健康把失败来源放在 `errors`，成功切换备用源的提示放在 `warnings`，并在 `health[].diagnostics`
  保留明细。缺少完整可比元数据的可选基差仍会置空并进入风险区，但不会把整个大宗快照误判为失败。
- 股票个股详情新增七域研究清单：基本面、估值、预期、事件、股权、资金流和流动性。每域都返回
  `status/method/asOf/sourceUrls/evidence/missingMetricIds/nextAction`。当前尚未接入有审计许可的完整财报和
  一致预期历史，因此这些缺口明确显示为 `unavailable` 或 `partial`，不会用行情、新闻或单篇研报补造。
- 自选清单不是投资组合。没有持仓数量或权重、成本、基准币种和现金仓位时，API 的
  `portfolioExposure.status` 固定为 `unavailable`；页面只展示各市场的自选只数，不计算等权比例。
- 腾讯行情按市场解析：A/H/US 总市值字段与流通市值字段独立，PB 仅在已核验的 A 股/港股字段可用；
  美股 Tencent PB 保持空值。旧错误估值缓存会因详情缓存版本不匹配而失效。
- 大宗商品使用 canonical series ID、多标签产业链、库存类型与关系类型；基差只有在单位、币种、品级、
  地点、合约以及税运费可比时才计算。能源把实测与估算点分开，估算点不生成伪 OHLC、环比或交易信号。
  宏观序列附来源链接、截止日、质量状态与发布日历。
- 通用指标质量结构由 `src/investment_quality.py` 生成；个股清单逻辑位于 `src/stock_research.py`。
  方法口径为 `observed/derived/estimated/proxy`，异常状态包括 `stale/partial/unavailable/error` 等。
- 财报数据边界位于 `src/financial_service.py`：`GET /api/financials/sources` 查看官方源和授权状态，
  `GET /api/financials` 只读已缓存事实，`POST /api/financials/sync` 才执行显式同步。美国市场使用 SEC EDGAR
  `companyfacts` 标准 XBRL；同步前必须设置可识别的 `NEWS_DIGEST_SEC_USER_AGENT`，项目节流到每秒不超过 2 次请求。
  HKEX 批量年报/发行人 feed 属于官方数据产品，A 股结构化服务走交易所/巨潮官方或明确许可来源；未配置授权时返回
  `license_required` 和官方披露入口，不抓取未文档化网页内部接口，也不从 PDF 猜数字。
- `src/news_digest_mcp_server.py` 是唯一对 Codex 暴露的 MCP：覆盖今日、新闻、AI 资讯、股票、财报、大宗、能源、消费、
  宏观、游戏和雪球语料。这里的 “AI 资讯” 只是主题数据，不表示项目运行模型。

## 运行

```bash
# 推荐：同时启动后端 5173 与前端 5174
./scripts/start-dev.sh

# 或分别启动（两端默认只监听 loopback）
.venv/bin/python -m uvicorn src.app:app --host 127.0.0.1 --port 5173 --reload --reload-dir src
VITE_API_TARGET=http://127.0.0.1:5173 npm run dev -- --host 127.0.0.1 --port 5174

# 单测
pytest tests/ -q
```

### 本地访问与 LAN 写保护

`scripts/start-dev.sh`、Vite dev server 和 `npm run preview` 默认仅监听 `127.0.0.1`。确需在局域网提供只读页面时，
可以显式执行 `HOST=0.0.0.0 ./scripts/start-dev.sh`。Vite 会把实际客户端地址转发给后端；远程 `POST`、`PUT`、
`PATCH`、`DELETE` 默认返回 403，不影响远程读取。

若确需通过 API 执行获准的远程写操作，只在服务端环境配置高熵 `NEWS_DIGEST_WRITE_TOKEN`，并在请求中
携带 `X-News-Digest-Write-Token`。令牌不会写入配置文件或前端包；因此远程浏览器 UI 保持只读，避免把
共享密钥暴露给所有 LAN 访问者。

### 运行产物治理

`.gitignore` 已覆盖 SQLite、用户自选快照、浏览器 profile/运行库、Python 缓存、Vite 构建产物和环境变量。
`tests/test_repo_hygiene.py` 会验证这些边界，同时保证源码与 `.example` 模板仍可跟踪。检查历史上已经被
Git 跟踪、但现在应忽略的产物可运行：

```bash
git ls-files -ci --exclude-standard
```

历史跟踪项不会被脚本自动删除或取消跟踪；应先逐项确认数据可恢复、构建方式和团队协作影响，再单独清理。

## 说明

- 股票 / 宏观 / 大宗等页面逻辑见 `src/*_service.py` 与 `SPEC.md`。
- 游戏区域子 tab 的完整规范与任务清单见 `SPEC.md` 的「§G/§C/§I/§V/§T（游戏区域）」与「§Browser」。
