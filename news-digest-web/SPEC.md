# SPEC

## §G

G1: `/stocks` 大盘页 → A股/港股/美股看板置顶；机构持仓+融资统一图表/表格；边际变化置底；申万一级/二级全行业可查。

## §C

C1: 保留“大盘/个股”子 Tab、现有 URL、刷新流程、市场卡片内容。
C2: 持仓口径 = 各类资金已披露样本内行业占比；不同资金类别不可横向求和。
C3: 融资累计净买入窗口固定近 3 年；融资余额取最新完整交易日。
C4: 申万一级 31 行业；二级行业按一级分组。
C5: 缺失二级披露 → `— 未披露`；禁止估算、按比例拆分、伪造 0。
C6: 各指标独立截止日+来源；禁止伪装同一期数据。
C7: 图加载全部行业；图例控制图内显隐；表格数据不受图例影响。
C8: 桌面+移动端可用；表格可横向滚动；行业列冻结。
C9: 不添加第三方依赖；不改无关用户修改、数据库快照、缓存产物。
C10: 来源分页硬上限 500 行；二级融资三年明细按一级分组加载+持久缓存，禁止主刷新百页级全量抓取。

## §I

ui: `/stocks` 大盘 → `market cards` → `institution holdings + financing` → `marginal signals`。
api: `GET /api/stocks` → 保留现有字段；扩展机构行业层级、融资余额、一级/二级融资序列。
api.detail: `GET /api/stocks/industry-financing/{industry}` → 该申万一级下二级近 3 年累计净买入+最新融资余额；缓存可复用。
classification: 申万一级 → 申万二级；一级汇总值与可披露二级值可核对。
source.holdings: 东方财富机构/国家队/ETF 持仓；百亿私募公开统计。
source.financing: 东方财富 Choice 行业融资融券 `FIN_NETBUY_AMT` + `FIN_BALANCE`。

## §V

V1: 大盘默认顺序 ! 三张区域看板最上 → 机构持仓与融资 → 边际变化最下。
V2: 主图默认公募基金；七类机构+累计融资净买入+融资余额可切换。
V3: 持仓/融资余额 → 横向条形图；累计融资净买入 → 近 3 年时间折线图。
V4: 默认展示全部申万一级；展开一级 → 对应二级替换该一级；父子不得重复展示。
V5: 一级图例分组可折叠；一级控制整组；二级可独立显隐；显隐仅作用图。
V6: 表格始终保留全部一级；一级行可展开二级；缺失值按 C5 显示。
V7: 表头分组 = 机构持仓 7 列 + 融资 2 列；融资列 = 近 3 年累计净买入、最新融资余额，单位亿元。
V8: 每列/图标题显示自身截止日；来源+覆盖+口径说明可见。
V9: ∀ 有完整二级数据一级：一级值 = 子级合计；未分类差额显式展示，禁止静默丢失。
V10: `GET /api/stocks` 旧字段兼容；新增层级/融资字段缺失时旧市场总览仍可渲染。
V11: 融资历史窗口有界 3 年；缓存增量刷新；来源失败保留上次有效快照并标记 stale。
V12: `npm run build` + 相关 Python 单测通过；桌面/移动视图无溢出阻断、无控制台错误。
V13: 任务差异仅含 `SPEC.md`、股票数据服务/测试、股票前端/样式及必要文档；用户其他修改保持原样。
V14: 一级数据随主接口返回；二级融资仅在一级展开时按组读取；重复读取命中缓存，来源失败保留该组上次有效快照。

## §T

id|status|task|cites
T1|x|扩展行业层级+融资数据模型/缓存/API|V4,V6-V11,V14,I.api,I.api.detail,I.classification,I.source.financing
T2|x|补行业层级、父子核对、融资余额、缺失披露回归测试|V4,V6-V11
T3|x|重排大盘并实现统一可切换主图+分组图例+层级表格|V1-V8,V10,I.ui
T4|x|完善桌面/移动样式、滚动、冻结列、可访问交互|V5-V8,V12
T5|x|运行单测/构建/API核对/桌面与移动浏览器验收|V1-V14

## §B

id|date|cause|fix
B1|2026-07-25|切换到无二级披露指标时复用了旧展开态，按钮文案与实际内容不一致|V5,V6

## §G（游戏区域子tab）

G2: 游戏页新增「区域」子 tab（排在第一个），展示所选地区（全球 + 30 个国家/地区，共 31 个）的 Steam 实时热销榜、周热销榜、月度最热新品，以及固定游戏清单的在线人数趋势（全球并发口径）。
G3: 固定游戏清单来自 `config/game_region_watchlist.json`；缺失 steamAppId 或取数失败的游戏，在线人数显示「—」，禁止伪造。
G4: 其余子 tab（流水总览 / 榜单 / 数据导入）本阶段先留空壳占位，现有 Top100 流水与点点/七麦国家榜保留在「流水总览」「榜单」中，不丢失现有能力。

## §C（游戏区域）

C11: 实时榜取 Steam 当前热销榜；周榜取 Steam 指定地区最近完整周热销榜；月榜取 Steam 最近发布的月度最热新品并保留官方金/银/铜档位。三种口径独立，未进入所选榜单显示「—」。
C12: 在线人数趋势 = Steam Charts 月度均值/峰值 + Steam 当前在线 API 实时并发；均为全球口径，随地区切换不变化，但在区域视图内呈现。
C13: 数据来源失败（风控/超时）时保留上次有效快照并标记 stale，前端展示警告，禁止报错中断页面。
C14: 缓存复用 SQLite `latest_games_region` 表，按地区 id 单行覆盖；默认半小时最小刷新间隔。

## §I（游戏区域）

ui: 游戏页子 tab 栏 → 区域（热销榜表 + 在线人数趋势折线图）/ 流水总览 / 榜单 / 数据导入。
api: `GET /api/games/region?cc=global`（支持 `?refresh=true`）。
data: 固定清单 `config/game_region_watchlist.json`（`games[].appId/name/nameZh/publisher/group`，`regions[].code/name`）。
source.hot.live: Steam 全球实时热销榜 `store.steampowered.com/charts/topselling/global` → `IStoreQueryService/Query`（`SteamCharts Live Top Sellers`）。
source.hot.weekly: Steam 全球/地区周热销榜 `store.steampowered.com/charts/topsellers/{cc}/{week}` → `IStoreTopSellersService/GetWeeklyTopSellers`。
source.hot.monthly: Steam 月度最热新品 `store.steampowered.com/charts/topnewreleases/{month}_{year}`；官方只给金/银/铜档且档内随机，禁止伪造成精确月排名。
source.players: SteamCharts `steamcharts.com/app/{appId}` + Steam 当前在线 API `GetNumberOfCurrentPlayers`。

## §V（游戏区域）

V15: 默认进入「区域」子 tab；地区选择器为可横向滚动的胶囊按钮，全球排首位。
V16: 热销榜表格可切换实时榜 / 周榜 / 月榜（新品）；实时/周榜列为排名，月榜列为官方档位；游戏（中+英）/厂商/实时在线/峰值/近月均值保持不变，未进入所选榜单者列末。
V17: 在线人数趋势为 SVG 多序列折线图，X 为月份、Y 为月度均值；图例单选聚焦：默认全部，点击任一项 → 仅显示对应序列，点击当前项 → 恢复全部，点击其他项 → 切换聚焦。
V18: 缺失/失败数据按 C12/C13 显示「—」或 stale 提示，不中断页面。
V19: 桌面双栏（热销榜 + 趋势），窄屏（≤900px）单栏堆叠。

## §T（游戏区域）

id|status|task|cites
T6|x|新增 config/game_region_watchlist.json 固定清单与地区|G2,G3,C11
T7|x|新增 game_region_service（Steam 热销榜 + CCU 趋势 + 缓存/stale）|G2,G3,C11-C14,V15-V19,I.api,I.data,I.source.*
T8|x|app.py 注册 /api/games/region|I.api
T9|x|前端游戏页子 tab 栏 + GameRegionTab（热销榜表 + SVG 趋势图）|V15-V19,G4
T10|x|SPEC/README 文档与单测|G2-G4,C11-C14
T11|x|抽出共享模拟浏览器模块 browser_service（单例会话 + 重试 + 错误映射），game_region/xueqiu/game_provider 统一委派|B1*规避,§Browser
T12|x|手游（心动小镇/原神/王者荣耀）等无 Steam appId 游戏以 null 保留为「未披露」行，在线/热销显示「—」|G3,C11-C12
T24|x|趋势图图例单选聚焦 + 再点恢复全部；构建/浏览器交互验收|V17,V35,V36,I.ui

## §Browser（模拟浏览器抓取）

B-m1: 所有对外 Steam / 雪球 / 三方数据抓取统一走 `src/browser_service.py` 的模拟浏览器（Playwright Chromium 持久化上下文），禁止裸 httpx 直连——此前直连已被 Steam 风控封 IP。
B-m2: `browser_service` 自动抓取会话 → 专用单线程 worker + 非持久 `BrowserContext`；`fetch_html_via_browser` / `fetch_json_via_browser` 失败自动重试（默认 2 次，失败时同线程重置会话）。
B-m3: 浏览器参数来自 `config/browser_settings.json`（`enabled` / `headless` / `channel` / `userAgent` / `locale` / `timezoneId` / `viewport` / `args` / `timeoutMs` / `waitMs` / `profileDir` / `libraryPath`）；`libraryPath` 用于注入 `LD_LIBRARY_PATH` 解决部署机缺失系统库。
B-m4: 错误统一经 `summarize_browser_error(error, *, interactive_login_hint=None)` 映射为中文可读信息；雪球只需传 `interactive_login_hint`（命中「需要可交互浏览器 / 已打开浏览器等待」时返回业务方提示），其余映射（含 WAF/超时/库缺失/Singleton/可执行文件缺失/连接断开/长消息截断）全部在 `browser_service`。雪球的风控页判定走 `browser_service.is_risk_control_page(text, tokens=...)`（默认 token 覆盖 aliyun WAF 与中文滑块文案）。
B-m5: 当前先不加代理；如后续需要，`browser_service` 预留 `args` / 启动参数扩展位，不改动各业务调用方。
B-m6: 手游（原神 / 王者荣耀 / 心动小镇）无 Steam appId，`load_region_games` 将其 `appId` 记为 `null` 并保留 `platforms` 字段；`build_region_payload` 对 null appId 跳过浏览器抓取，前端渲染为「— 未披露」。

## §V（Steam 抓取修复）

V20: `store.steampowered.com` ∈ proxy hosts → Playwright 使用配置 HTTP proxy；其余 hosts ⊥ 强制代理。
V21: Chromium 部分启动失败 → retry 前停止 Playwright driver；最终错误保留首个根因。
V22: Steam 热销榜读取官方 weekly top-sellers response `appid`；响应无 appId → 显式错误。
V23: 区域刷新全部来源 unavailable → ⊥ 覆盖最新有效快照；有快照 → `stale=true` + 本次 warnings。
V24: 区域 API 失败 → UI 显示错误；⊥ 静默 `0/0`。
V25: Steam 专区与 Sensor Tower 专区独立加载/状态/刷新；Sensor Tower error ⊥ 出现在 Steam 专区。
V37: `fetch_*_via_browser` ∀ Playwright lifecycle → 同一专用 worker thread；调用方 `asyncio.to_thread` 线程变化 ⊥ 转移 session owner。
V38: 自动抓取 singleton → 非持久 `Browser` + `BrowserContext`；⊥ 使用 `profileDir` / `SingletonLock`；`launch_browser_context` 登录流程保持持久 profile。
V39: dev Uvicorn reload → watch `src/` only；`.venv/` / `data/browser-profile/` 变化 ⊥ restart API worker。
V40: Steam service `application/octet-stream` response → replay same URL + `format=json`；⊥ UTF-8 decode protobuf；top-sellers success → ordered `appid` ranks。
V41: SteamCharts monthly `avg` decimal → numeric round-half-up once；series month ascending → UI last point = latest month；⊥ strip decimal separator as digit。
V50: 全球实时榜 → `IStoreQueryService/Query` 且 query = `SteamCharts Live Top Sellers`；排名 = `response.ids` 官方顺序（1-based）；⊥ `GetWeeklyTopSellers` 代替实时榜。
V51: 全球/地区周榜 → 最近完整周页面 + `GetWeeklyTopSellers`；排名 = upstream `rank`，即使有缺口也 ⊥ enumerate appids 重编号。
V52: 月榜 → Steam 最近已发布「月度最热新品」；值 ∈ {黄金级,白银级,青铜级}，档内顺序无排名含义；⊥ 展示伪造整数名次。
V53: 实时/周/月三套结果独立字段+状态+错误+缓存版本；UI 单选切换只改变热销榜口径，在线人数不变；旧 schema 快照 ⊥ 复用。
V54: Steam 排名页 timeout ≥30s 且与玩家/历史接口 timeout 独立；≤30s 的正常慢响应 ⊥ 误标 unavailable。

## §T（Steam 抓取修复）

id|status|task|cites
T13|x|修复 Steam proxy/browser/top-sellers/cache/UI error path + Steam/Sensor Tower 分区|V20-V25,I.api,I.source.*
T18|x|修复 Playwright 跨线程复用 + 持久 profile 锁 + reload 范围 + Steam protobuf 榜单 + SteamCharts 小数/月序；补防复发测试|V37-V41,B-m2
T25|x|拆分 Steam 全球实时榜/周榜/月度新品榜，原始名次或档位透传，前端切换，旧缓存失效，真实页面验收|V50-V54,C11,I.source.hot.*

## §B（Steam 抓取修复）

id|date|cause|fix
B2|2026-07-26|runtime route stale + Chromium libs missing + Steam Store direct timeout + DOM no appId + error hidden/source status mixed|V20-V25
B3|2026-07-26|全量验证误用系统 Python；pytest 测试模块无法导入|改用项目环境或隔离测试依赖；非产品代码缺陷
B4|2026-07-26|Sync Playwright singleton 跨 `asyncio.to_thread` 线程复用；close 失败遗留 profile lock；全项目 reload 受 `.venv/` 变化干扰|V37-V39
B5|2026-07-26|`GetWeeklyTopSellers` 返回 gzip `application/octet-stream` protobuf；`response.json()` UTF-8 decode 失败 → ranks 全空|V40
B6|2026-07-26|SteamCharts `avg` 含小数；通用 `parse_int` 删除小数点 → 10×；源序 newest-first + UI 取 last → “近月”取最老月|V41
B10|2026-07-26|`GetWeeklyTopSellers` 周榜被标成全球实时榜，且只抽 appid 后重新 enumerate，导致火炬之光周榜名次冒充实时名次|V50,V51,V53
B11|2026-07-26|Steam 排名页与玩家接口共用 10s timeout；真实实时/周榜需约 15–25s，成功响应被误标 unavailable|V54

## §G（前端改版）

G5: `news-digest-web` → 清晰、专业情报看板；数据行为不变。

## §C（前端改版）

C15: 保留 routes、API request/response、刷新、链接、持久化数据。
C16: 保留 7 天有界 feed + latest snapshot；渐进披露仅影响展示。
C17: ⊥ 新 runtime dependency。
C18: 1440px desktop + 390px mobile 可用。
C19: 中文 UI；semantic HTML；keyboard focus 可见。

## §I（前端改版）

routes: `/news`, `/ai`, `/stocks`, `/commodities`, `/energy`, `/consumption`, `/macro`, `/games`, `/xueqiu`
entry: `frontend/src/App.jsx`
styles: `frontend/src/styles.css`
build: `npm run build`
tests: `python3 -m unittest discover -s tests -v`

## §V（前端改版）

V26: 390px shell → non-sticky tall header + 单行横向 page nav + ⊥ document overflow。
V27: mobile actions/tabs/jump links → min 44px target + `:focus-visible`；reduced-motion honored。
V28: status → 默认 compact；failure/partial anomaly 可见；完整 source/error 可访问。
V29: news → 每列初始 ≤12 cards；首项强调；其余 compact；load-more 保留 full snapshot。
V30: AI news → 每 tab 初始 ≤24 cards；load-more 保留 full snapshot。
V31: stocks 保留大盘/个股 tab；大盘 → market overview → institution/industry → marginal signals；jump nav 暴露层级。
V32: macro @390px → card rows；7 fields 保留；⊥ horizontal table scroll。
V33: surfaces/colors → 每页单 accent；red/green 仅 semantic。
V34: ∀ routes @1440px + representative routes @390px → render；zero console errors；⊥ document overflow。
V35: `npm run build` + Python unittest → exit 0。
V36: hrefs、active state、external links、tabs、refresh actions → behavior preserved。

## §T（前端改版）

id|status|task|cites
T14|x|redesign shell/nav/status/tokens/focus|V26-V28,V33,V36
T15|x|add progressive disclosure + feed hierarchy|V29,V30
T16|x|integrate stock hierarchy + macro mobile cards|V31,V32
T17|x|build/tests/desktop-mobile QA|V34,V35

## §G（抓取防封与启动预热）

G6: 服务每次启动 → 所有注册数据页刷新各自动执行 1 次；用户切页时 ⊥ 需要手工补刷新。
G7: 对外抓取 → 共享域名级限速/重试/熔断；风控响应 ⊥ 被并发、分页或重试放大。

## §C（抓取防封与启动预热）

C20: 启动刷新保留 `force=True`；∀ `STARTUP_REFRESH_KINDS` 各调度 1 次，含 Steam 区域默认 `global`。
C21: 启动任务有界并行+错峰；刷新中仍优先返回最近有效快照/静态兜底，完成后现有轮询自动更新。
C22: 同域同步/异步请求共享协调状态；默认并发 ≤1；最小请求间隔+抖动可按域配置。
C23: `403`/`429`/WAF/验证码 → 域熔断；尊重 `Retry-After`；冷却期 ⊥ 自动重试。
C24: 仅网络错误/`5xx` 可重试；次数有界；指数退避+jitter；取消/超时必释放许可。
C25: `GET /api/*`、`POST /api/refresh/{kind}`、响应字段、前端刷新/轮询行为兼容；同 kind single-flight。
C26: ⊥ 新第三方依赖；⊥ 代理轮换/指纹绕过；官方 API/RSS 保持 HTTP 客户端。
C27: 保留现有 SQLite 快照、缓存、登录 profile、用户并发修改；日志 ⊥ Cookie/Token/响应敏感正文。

## §I（抓取防封与启动预热）

module: `src/request_coordinator.py` → sync+async 域名许可、节奏、风险熔断、`Retry-After`。
config: `config/crawl_policy.json` → default/domain policy；缺失/非法 → 安全默认值。
startup: `startup_refresh` → ∀ 注册 kind 各 1 次；`games-region` → `get_region_games(cc="global", refresh=True, force=True)`。
api: 现有 `/api/refresh/{kind}` + `/api/refresh-status` shape 兼容；允许新增 `games-region` 状态项。

## §V（抓取防封与启动预热）

V40: ∀ `STARTUP_REFRESH_KINDS` → 每次进程启动恰调度 1 次且 `force=True`；含 `news`/`ai-news`/`ai-projects`/`stocks`/`commodities`/`energy`/`consumption`/`macro`/`games`/`games-region`/`xueqiu`。
V41: 启动刷新 active jobs ≤2；每项有错峰；1 项失败/超时 ⊥ 阻止其余项执行或状态落盘。
V42: 同域 sync+async 请求 → 共享并发计数+开始时间；active ≤ policy；相邻开始间隔 ≥ policy 下限（允许测试禁用 jitter）。
V43: `403`/`429`/WAF/验证码 → 记录域冷却并停止该请求链；`Retry-After` 有效值决定不短于该值的冷却；⊥ 立即换 Session/浏览器重试。
V44: 网络错误/`5xx` 重试 ≤ policy；退避单调增加+jitter；异常/取消/超时后 active 归零。
V45: 启动刷新排队/运行期间，各页面读取最近有效 SQLite/内存快照；后台完成 → `version` 增加且现有前端轮询自动重载。
V46: 雪球普通抓取在允许条件下可达 Playwright fallback；二维码状态远端探针间隔 ≥15s；普通刷新/搜索/研究/自选雪球共用域协调器；研究 active jobs ≤1。
V47: 股票/自选、商品、能源、新闻/AI、Steam 高请求路径全部经过域协调器；分页保留硬上限；分页间隔 ⊥ 低于域策略。
V48: 现有 API payload/7 天雪球窗口/最新快照/stale fallback 不回归；Cookie/Token ⊥ 日志与错误响应。
V49: request-coordinator/启动/Xueqiu/高请求路径单测 + 全量 Python tests + `npm run build` + 本地启动/refresh-status 验收 exit 0。

## §T（抓取防封与启动预热）

id|status|task|cites
T19|x|新增共享域协调器+策略配置+同步/异步回归测试|V42-V44,V48,I.module,I.config
T20|x|启动刷新全覆盖+有界错峰+`games-region`+状态测试|V40,V41,V45,C20-C25,I.startup,I.api
T21|x|修复雪球 fallback/二维码探针/研究全局 single-flight；接入共享协调器|V43,V46,V48
T22|x|股票/自选、商品、能源、新闻/AI、Steam 接入协调器并收紧分页节奏|V42-V44,V47,V48
T23|x|全量 tests/build/本地启动与页面预热验收|V40-V49

## §B（抓取防封与启动预热）

id|date|root cause|caught by
B5|2026-07-26|T19 red-phase test imported the promised coordinator before its module existed|V42-V44
B6|2026-07-26|Steam risk guard assumed every browser response exposed `ok`; existing test response only guaranteed status/json|V48
B7|2026-07-26|process-global Xueqiu search lock retained an event-loop binding across isolated loops|V46,V48
B8|2026-07-26|transient browser-process crash text was omitted from the bounded retry classifier|V44,V47
B9|2026-07-26|frontend build invoked Windows PowerShell `npm`; project npm available inside WSL only|use WSL project command；非产品缺陷

## §G（投资可信度改造）

G8: `news-digest-web` → 可审计投资研究工作台；首屏先给变化/风险/影响/证据，⊥ 用代理、估算、不可比数据制造确定性。
G9: `news-digest-web` → 确定性取数/标准化/缓存/MCP 数据服务；Codex Host → 唯一分析层。项目 ⊥ 调 LLM、生成观点/评级/建议；分析 ! 由用户向 Codex 发指令。

## §C（投资可信度改造）

C28: 现有 routes/API 旧字段兼容；新增质量元数据；旧快照缺字段仍可渲染。
C29: ⊥ 新 runtime dependency；优先标准库+现有依赖。
C30: ∀ 来源失败 → 分组件 last-known-good + stale/error；⊥ 用空数组覆盖有效快照。
C31: ∀ estimated/proxy/derived → 显式 method+公式/说明；⊥ 冒充 observed。
C32: 历史窗口有界；刷新按来源频率/发布日历；⊥ 月/季数据统一 30min 强刷。
C33: 默认服务仅 loopback；写接口 ⊥ 未授权 LAN 暴露；MCP 读工具只读已有快照，动作工具 ! 显式调用+审批；⊥ 任意 URL/任意本地路由代理。
C34: 保留用户现有未提交修改；⊥ 改无关缓存/数据库/构建产物；⊥ commit/push。
C35: 个股财务源 ! SEC/HKEX/上交所/深交所/巨潮官方披露或明确许可商业源；无公开机器接口/授权/必要身份 → `unavailable|configuration_required`，⊥ 私有网页接口冒充正式 API、⊥ fallback 伪造。
C36: 项目 runtime ⊥ LLM SDK/provider/model/API key/prompt/memo 执行；“AI”栏目仅资讯主题。Codex 通过 MCP 读证据并自行分析，项目只返回事实、来源、质量、缺口。

## §R（财报与 MCP 边界，2026-07-26）

R1: SEC EDGAR 官方 REST JSON 无需 key；`submissions`+XBRL `companyfacts` 实时更新。https://www.sec.gov/search-filings/edgar-application-programming-interfaces
R2: SEC 自动访问 ! 可识别 User-Agent+节流；官方上限 10 req/s，本项目目标 ≤2 req/s+缓存。https://www.sec.gov/about/developer-resources
R3: HKEX 年报/中报批量文件=订阅数据产品；IIS=发行人公告实时 feed+认证测试。免费网页可作原文入口，⊥ 推断成无授权结构化 API。https://www.hkex.com.hk/eng/ods/historicalData.aspx https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29
R4: 巨潮=深交所法定披露平台；官方另设登录型 CNINFO Data Service/API 文档。未配置该服务授权前只暴露官方披露入口+`license_required`。https://www.cninfo.com.cn/ https://webapi.cninfo.com.cn/
R5: 上交所/深交所已采用 XBRL 披露；公开存在≠稳定开放 API。适配器只消费官方明示接口/下载文件或已授权服务。https://www.sse.com.cn/services/information/xbrl/ssexbrl/index.shtml https://www.szse.cn/aboutus/trends/news/t20090213_517801.html

## §I（投资可信度改造）

metric.quality: `{value,unit,currency?,asOf,publishedAt?,fetchedAt?,derivedAt?,sourceUrl,definition,method,status,coverage?,qualityFlags[],revision?}`。
metric.method: `observed|derived|estimated|proxy`。
metric.status: `ok|stale|partial|empty|unsupported|error|unavailable|invalid`。
commodity.relation: `same_product_global|upstream_driver|substitute|downstream_demand`；basis 另含 `comparable/reasons/normalizedInputs`。
commodity.inventory: `exchange_receipt|deliverable_stock|port_stock|social_stock|mill_stock|plant_stock|sample_stock`。
energy.point: `{period,value,method,source,asOf}`；月产量 → bar/line，⊥ synthetic OHLC。
stock.capitalFlow: observed `mainNet*` 与 proxy `pricePressureProxy` 分离。
stock.futures: ∀ IF/IH/IC/IM → contract-level `notionalExposure/annualizedBasis`；⊥ 四品种手数/基差简单聚合。
ui.health: 页面首屏 → source freshness/failure/coverage/method badge + 今日变化/风险。
financial.source: `{id,market,access,authorization,structured,sourceUrl,documentationUrl,status,note}`。
financial.snapshot: `{schemaVersion,market,symbol,entity,status,asOf,fetchedAt,source,facts[],derived[],qualityWarnings[]}`；facts ! filing URL/accession/period/unit/form。
financial.api: `GET /api/financials/sources` + `GET /api/financials?market&symbol&cik?` 只读；`POST /api/financials/sync` 显式联网+持久化。
mcp.server: 单一 `news_digest` stdio server；固定工具白名单；读工具=快照，动作工具=审批写操作。
xueqiu.trigger: 全量/增量抓取仅 `start_influencer_crawl` 或页面二次确认 POST；启动/开页/搜索/分析 ⊥ 隐式抓取。
analysis.boundary: MCP 只给证据/来源/质量；Codex 根据用户分析指令产出结论，项目页面/后端 ⊥ 自动分析。

## §V（投资可信度改造）

V55: ∀ 首屏投资指标 → `unit/asOf/sourceUrl/definition/method/status` 可访问；缺关键元数据 → ⊥ 主卡/Agent事实。
V56: proxy/estimated → 标题+样式+说明显式；⊥ 写入 observed 字段；unavailable > 伪精确。
V57: basis/cross-market spread → 单位+币种+品级+地点+合约+税运费可比才 `comparable=true`；否则 value=`null` + reasons。
V58: 能源 estimated/interpolated/extrapolated 点 → ⊥ OHLC、环比、信号、首屏 KPI；UI 虚线/标记；actual 月度序列用 bar/line。
V59: 库存按 type 独立序列；来源合并 ⊥ 跨 type 覆盖。
V60: global 同品种/上游/替代/下游关系独立；⊥ 非同品种计算内外盘差。
V61: ∀ 股票子组件刷新失败 → 保留该组件 last-known-good + stale/error；empty≠unsupported≠error。
V62: 腾讯行情时间先按市场 timezone 解释再转 UTC；UI 同显 quote asOf + page fetchedAt。
V63: 股指期货按合约乘数/点位算名义敞口、按到期日算年化基差；⊥ sum contracts / mean raw basis 作为总信号。
V64: 港股价格压力 proxy → 独立 schema/UI；⊥ “主力净流入/主力占比”。
V65: 今日/股票/大宗/能源首屏 → 数据健康+显著变化+风险+影响；覆盖计数移入健康详情。
V66: 390px 关键判断 ⊥ 依赖 >viewport 横向表；卡片/优先列+详情抽屉可完成主流程。
V67: 单一 `news_digest` MCP → 暴露项目确定性快照/证据；分析执行 ∈ Codex Host；项目源码/页面/API ⊥ LLM runtime/Agent readiness/自动结论。
V68: 服务默认 `127.0.0.1`；LAN 模式显式 opt-in；未认证写接口 ⊥ 默认 LAN 可达。
V69: ∀ P0 bug → 针对性回归测试；全量 Python tests + `npm run build` + 1440/390 browser QA exit 0。
V70: API 旧字段/现有 routes/7日雪球窗口/latest snapshot 不回归；任务 diff ⊥ 无关用户文件。
V71: 运行 SQLite/PYC/本地 watchlist/构建产物 ⊥ 新增跟踪；清理既有跟踪需独立确认。
V72: 今日页 source health 非 ok → qualitySummary 同步计入；⊥ 健康告警与“状态完整”并存。
V73: `GET /api/today` → 仅读取已有快照且每领域等待有界；启动刷新/单源卡住 ⊥ 拖死首屏，超时域进入 health/risk。
V74: 投资快照仅加字段的 schema 升级 → 旧快照惰性迁移后立即可读；⊥ 仅因版本号不等而同步等待实时抓取。
V75: 抓取协调器可先检查响应正文；GBK 等来源解析 → 从 `response.content` 显式解码，⊥ 读取 `.text` 后再改 `response.encoding`。
V76: Tencent quote schema 按市场映射并用带索引 fixture 锁定；A/H/US 总市值=`45`、流通=`44`，PB=A:`46`/HK:`58`/US:`unavailable`；⊥ 共用任意尾字段。
V77: 个股详情 → 估值/流动性/基本面/预期/事件/股权/资金流七域研究清单；每域显式 `status/method/asOf/sourceUrls/evidence/missingMetricIds/nextAction`；未接入审计财报时基本面=`unavailable`，⊥ 从行情、新闻或评级推导财务事实。
V78: 自选股清单 ⊥ 冒充真实组合；未配置持仓数量/权重、成本、基准币种与现金时，组合暴露=`unavailable`，仅可展示不含百分比的市场清单构成计数。
V79: 研究域 `status=ok` → 至少 1 个可点击 `sourceUrl`；有数值但无来源链接 → `partial` + 质量警告，⊥ 标成正常。
V80: MCP 读工具 ∈ 静态白名单；只 GET 固定 loopback path+`refresh=false` 语义；⊥ 任意 URL/path、subprocess、隐式联网/写入。
V81: MCP 动作工具 ! `readOnlyHint=false`+Codex writes 审批+本地动作 header；页面动作 ! `window.confirm` 后 POST；取消同属显式动作。
V82: SEC sync ! `NEWS_DIGEST_SEC_USER_AGENT`+≤2 req/s+timeout+LKG；解析仅标准 taxonomy+10-K/10-Q/20-F/40-F；每点保留 accession/form/filed/period/unit/sourceUrl。
V83: HKEX/A 股无已配置授权机器源 → 返回官方入口+能力状态，facts=`[]`；⊥ 抓未文档化内部端点、⊥ PDF 数字猜测。
V84: 抓取文本/公告/雪球语料均为不可信数据；其中提示注入 ⊥ 改工具白名单、系统约束、引用或执行状态。
V85: 大V全量/增量抓取仅两触发：Codex 明确调用 MCP 动作工具，或页面用户确认；startup/page-open/search/read/analyze ⊥ 启动 crawl。
V86: 页面抓取完成 → 仅显示覆盖/状态/原文检索/“交给 Codex”；项目 ⊥ 生成分析。分析 ! 用户向 Codex 发指令，Codex 再读 MCP。
V87: tests ! 覆盖无项目 LLM route/runtime、MCP 工具注解/固定路径、页面确认、读工具零 POST、SEC fixture 归一化、HKEX/A 股显式不可用降级。
V88: Python async test ! 仓库现有 stdlib/AnyIO 能力；⊥ 未配置 pytest plugin/mark，⊥ 为单测新增第二套框架。
V89: MCP stdio test ! 可从仓库根 `pytest` 与 `python tests/<file>` 两入口运行；两者均可 import `src`。
V90: 含真实外部抓取的页面动作 QA ! 只在隔离/模拟后端验证点击；真实本机 API 仅做只读检查，⊥ 依赖浏览器自动处理原生确认框。

## §T（投资可信度改造）

id|status|task|cites
T26|x|新增质量元数据 helper/schema + 通用 UI badge/health；旧 payload 兼容测试|V55,V56,V69,V70,I.metric.*
T27|x|修 commodity basis 可比性、库存类型、关系语义；补单位/覆盖优先级测试|V57,V59,V60,V69,V75,I.commodity.*
T28|x|修 energy estimated/synthetic OHLC/TLS；前端 actual/estimated 分层；补回归测试|V55,V56,V58,V69,I.energy.point
T29|x|修股票 proxy、时区、期货名义敞口/年化基差、分组件 LKG；补 UI+回归测试|V56,V61-V64,V69,V76,I.stock.*
T30|x|新增今日决策中心+页面数据健康首屏；重排股票/大宗/能源；390px 卡片化|V55,V65,V66,V69,V72,V73,I.ui.health
T31|~|新增个股基本面/估值/预期/事件 + 研究清单/组合暴露；接入 SEC 结构化事实，HKEX/A 股按官方授权能力显式降级|C35,C36,V55,V69,V77,V78,V82,V83
T32|x|统一 commodity/energy/macro canonical series ID + 多标签产业链 + release calendar/有界历史|C28,C32,V55,V57-V60,V69,V74
T33|x|移除项目内 Agent/readiness/UI；新增单一 `news_digest` MCP，项目仅供数据，Codex 唯一分析层|C33,C35,C36,V67,V69,V80-V87,I.mcp.server,I.analysis.boundary
T34|x|默认 loopback + 写接口保护；按领域拆分前后端；仓库运行产物治理|C29,C33,C34,V68,V70,V71
T35|x|全量 tests/build/API/schema/桌面移动浏览器/数据质量验收|V55-V71
T36|x|财报 source catalog+SEC sync/cache/标准 facts；HKEX/CNINFO/交易所授权状态与官方入口|R1-R5,V82,V83,I.financial.*
T37|x|统一 MCP 覆盖 today/stocks/financials/commodities/energy/macro/news/games/Xueqiu；固定白名单+有界输出|V67,V80,V81
T38|x|页面大V抓取二次确认；抓取完成只提示交给 Codex；分析零自动触发|V85,V86,I.xueqiu.trigger,I.analysis.boundary
T39|x|定向/全量 tests+build+MCP stdio smoke+页面触发边界 QA|V69,V87,V90

## §B（投资可信度改造）

id|date|cause|fix
B12|2026-07-26|港股成交额×涨跌幅 proxy 写入 `mainNet*` 且 UI 标为主力资金|V56,V64
B13|2026-07-26|commodity spot/future 未校验单位/品级/地点/合约即计算 basis|V57
B14|2026-07-26|energy 插值/外推点被构造成 OHLC 并参与普通展示|V58
B15|2026-07-26|IF/IH/IC/IM 手数相加、raw basis 简单平均忽略乘数/到期|V63
B16|2026-07-26|T26 red test 在 helper 创建前导入 `src.investment_quality`|V69；预期 TDD 红灯，⊥ 新 invariant
B17|2026-07-26|T27 red test 在库存类型合并 helper 创建前导入接口|V59,V69；预期 TDD 红灯，⊥ 新 invariant
B18|2026-07-26|energy fallback 无 method、估算点参与 MoM/人工 OHLC、client `verify=False`、摘要计伪K线|V58,V69
B19|2026-07-26|T29 red test 在股票分组件 LKG helper 创建前导入接口|V61,V69；预期 TDD 红灯，⊥ 新 invariant
B20|2026-07-26|旧期货测试固定断言 raw basis 图值/metric 位置，与 V63 年化+名义口径冲突|V63；更新验收语义
B21|2026-07-26|T30 red test 在今日聚合服务创建前导入接口|V55,V65,V69；预期 TDD 红灯，⊥ 新 invariant
B22|2026-07-26|T30 red test 在 `/api/today` 与 `/today` 注册前断言路由|V65,V69,V70；预期 TDD 红灯，⊥ 新 invariant
B23|2026-07-26|T30 red test 在股票组件健康摘要 helper 创建前导入接口|V61,V65,V69；预期 TDD 红灯，⊥ 新 invariant
B24|2026-07-26|今日页来源健康 2/4 时质量条仍显示“状态完整”，聚合仅统计显著变化/AI 条目|V72；source health 加入 qualitySummary，补矛盾回归测试
B25|2026-07-26|V72 回归测试把 stale 精确计为 1，忽略信号本身也可 stale|V72；改验 problemCount 覆盖关系与 partial/error 下界，⊥ 新 invariant
B26|2026-07-26|T32 red test 在统一指标目录模块创建前导入接口|C32,V55,V69；预期 TDD 红灯，⊥ 新 invariant
B27|2026-07-26|T32 目录模块已建立但 commodity/energy/macro 服务尚未挂接元数据，集成测试缺 canonical ID|C32,V55,V69；预期分阶段 TDD 红灯，⊥ 新 invariant
B28|2026-07-26|T32 验收命令误引用不存在的 `tests/test_macro_service.py`，pytest 在收集前退出|改用目录中实际测试清单；非产品缺陷，⊥ 新 invariant
B29|2026-07-26|T34 red test 在本地写访问守卫模块与 loopback 配置实现前导入接口|C33,V70；预期 TDD 红灯，⊥ 新 invariant
B30|2026-07-26|冷启动浏览器验收中 `/api/today` 等待并发 startup refresh/来源锁，30s 无首屏|V73；改为有界快照读取，超时域显式降级进 health/risk
B31|2026-07-26|V73 red test 在今日快照 timeout 与四域 snapshot reader 接口实现前断言降级行为|V73；预期 TDD 红灯，⊥ 新 invariant
B32|2026-07-26|投资 UI 拆分后 `MetricQualityMeta` 仍引用未导入的 `qualityBadgeClass`，构建通过但浏览器运行时报错白屏|V69；导出并显式导入共享 helper，浏览器复验
B33|2026-07-26|commodity/energy/macro additive schema bump 拒绝旧 SQLite 快照，冷启动页面转入实时抓取并长时间停在加载态|C28,V45,V74；新增惰性迁移与旧快照即时读取回归测试
B34|2026-07-26|V74 red tests 在三域 additive snapshot migrator 实现前导入接口|V74；预期 TDD 红灯，⊥ 新 invariant
B35|2026-07-26|协调器已读取 Sina 响应 `.text` 后 commodity fetch 再设置 `response.encoding='gbk'`，httpx 拒绝并导致期货刷新失败|V75；改为从原始 bytes 显式 GBK 解码并补回归测试
B36|2026-07-26|V75 red test 在显式 Sina bytes decoder helper 实现前导入接口|V75；预期 TDD 红灯，⊥ 新 invariant
B37|2026-07-26|V74 股票页 red test 在 stock additive snapshot migrator 实现前导入接口|V74；预期 TDD 红灯，⊥ 新 invariant
B38|2026-07-26|T35 API schema 验收发现 macro 106 个 canonical series 已齐，但缺行级 quality/sourceUrl 与顶层 qualitySummary|V55；补宏观来源映射、显式 stale 质量与页面健康摘要，⊥ 新 invariant
B39|2026-07-26|V55 macro quality red tests 在行级质量装配与摘要实现前缺 `quality`|V55；预期 TDD 红灯，⊥ 新 invariant
B40|2026-07-26|宏观迁移测试未提供 value 却期待 stale；质量契约正确判为 unavailable|V55；给有值的配置快照 fixture 补 value/unit，⊥ 新 invariant
B41|2026-07-26|个股详情把 Tencent 尾字段 `59` 统一当 PB，导致 A股 37/170/666 倍、港股股息率 0.25/0.33 冒充 PB；US 总市值还误读公司名字段 `46`|V76；按市场校正 PB 与总/流通市值索引，US PB 不伪造
B42|2026-07-26|V76 带索引 fixture 在市场特定 Tencent 映射修正前复现 A股 PB=37|V76；预期 TDD 红灯，⊥ 新 invariant
B43|2026-07-26|V77/V78 red tests 在个股研究清单与组合不可用保护模块创建前导入接口|V77,V78；预期 TDD 红灯，⊥ 新 invariant
B44|2026-07-26|浏览器验收发现 A股实测资金流有序列但无 `sourceUrl`，研究清单仍标 `ok`|V79；无可点击来源时降为 partial 并警告
B45|2026-07-26|V79 回归测试在资金流来源完整性判断实现前复现 `ok`|V79；预期 TDD 红灯，⊥ 新 invariant
B46|2026-07-26|资金流 section 只有来源名称，没有可点击 URL；V79 来源测试缺字段|V79；Sina/Yahoo/东方财富返回实际页面或请求 URL
B47|2026-07-26|桌面 QA 脚本在异步详情渲染前读取空 selector 的 computed style|先等待 `.stock-research-panel` visible 并空值安全读取；非产品缺陷
B48|2026-07-26|早期误把分析层放进项目并新增 `src.investment_agent`/readiness；用户澄清 Codex 才是唯一 LLM|V67,V86；删除项目 Agent，改统一 MCP 数据边界
B49|2026-07-26|财报读边界测试使用仓库未配置的 `pytest.mark.asyncio`，测试函数未执行即失败|V88；改用 `asyncio.run`，不新增依赖
B50|2026-07-26|MCP 隔离环境只装运行依赖，误用 `.venv-mcp -m pytest` 导致无 pytest|V88；stdio smoke 用测试文件自带 `unittest` 入口
B51|2026-07-26|直接执行 stdio 测试时 `sys.path[0]=tests`，尾部安全测试无法 import `src`|V89；显式加入仓库根
B52|2026-07-26|真实页面 QA 点击抓取按钮时，浏览器自动化未暴露可控原生确认框并在超时后启动了抓取|V90；不再在真实本机 API 点击副作用按钮，以静态回归+只读页面检查验证边界

## §G（关注游戏配置）

G10: 游戏页 → 用户可增删/导入关注游戏；Steam / Sensor Tower / 点点 / 七麦只向项目缓存、API、页面输出关注游戏。

## §C（关注游戏配置）

C37: `config/game_region_watchlist.json` → 唯一关注目录；现有 31 款为初始值；`games: []` 合法且 ⊥ 自动恢复默认值。
C38: 导入支持 JSON/CSV + `merge|replace`；replace ! 二次确认；单次 ≤500 款、正文 ≤1 MiB。
C39: 匹配优先来源专属 appId；缺失 ID → 规范化中/英文名+aliases；歧义/重复 → 拒绝，⊥ 猜测归并。
C40: Steam 在线/历史请求仅关注游戏；Steam/点点/七麦榜单可读取完整榜单以保留真实名次，但未关注行 ⊥ 进入业务缓存/API/UI；Sensor Tower/本地导入同样先过滤再成表。
C41: 写入原子替换+完整校验；失败 → 原目录不变；写动作沿用 loopback/local-action 守卫。
C42: 清单变更 → 内存+SQLite 游戏快照按 watchlist revision 失效；旧快照 ⊥ 复活已删除游戏。

## §I（关注游戏配置）

data.watchlist: `config/game_region_watchlist.json` → `games[].id/name/nameZh/publisher/group/platforms/aliases/appId/sourceIds` + `regions[]`。
api.watchlist.read: `GET /api/games/watchlist` → `{schemaVersion,revision,games,importSchema}`。
api.watchlist.import: `POST /api/games/watchlist/import` → `{format,json|csv content,mode}` → 原子 merge/replace 结果。
api.watchlist.delete: `DELETE /api/games/watchlist/{game_id}` → 删除 1 款；未知 id → `404`。
ui.watchlist: `/games` → `关注游戏` 子 tab → 添加、删除、JSON/CSV 导入、来源映射状态。

## §V（关注游戏配置）

V91: GET → 当前目录 31 款；add/import/delete 成功后再次 GET → 持久结果；重启语义不变。
V92: `games: []` 保存/重读仍空；Steam/Sensor Tower/点点/七麦 payload 均 0 关注行；⊥ DEFAULT_GAMES fallback。
V93: ∀ source row → sourceIds 精确命中 ∨ 唯一 alias 命中才保留；未命中/歧义 → 排除+可审计 warning。
V94: 点点/七麦原始 rank、Steam 原始 rank/tier 保留；过滤后 ⊥ 重编号。
V95: 清单 revision 变化 → `/api/games` + `/api/games/region` 旧内存/SQLite 快照失效；删除项 ⊥ 残留。
V96: 非法 JSON/CSV、重复 id/来源 ID、缺少名称、>500 款、>1 MiB → `4xx`；文件字节不变。
V97: UI → 键盘可用添加/删除/导入；replace/delete 二次确认；空目录/校验错误可见；390px 无横向溢出阻断。
V98: 现有游戏 API 字段、地区列表、来源真实排名、stale fallback 保持兼容；定向 Python tests + 全量 tests + `npm run build` + 1440/390 browser QA exit 0。

## §T（关注游戏配置）

id|status|task|cites
T40|x|新增关注目录 schema/校验/原子 merge-replace-delete/revision + 单测|C37-C42,V91-V96,I.data.watchlist
T41|x|注册 watchlist API；Steam/Sensor Tower/点点/七麦统一过滤+缓存 revision；补 API/来源回归|V91-V96,V98,I.api.watchlist.*
T42|x|新增关注游戏子 tab：添加/删除/JSON-CSV 导入/来源映射状态；补响应式与交互回归|V91,V97,V98,I.ui.watchlist
T43|x|全量 tests/build/API/桌面移动浏览器验收；核对任务 diff 不覆盖 T31/用户修改|V91-V98,C41,C42

## §B（关注游戏配置）

id|date|cause|fix
B53|2026-07-26|T40 red test 在关注目录服务创建前导入 `src.game_watchlist_service`|V91-V96；预期 TDD 红灯，⊥ 新 invariant
B54|2026-07-26|T41 red tests 在 watchlist API/四来源过滤/revision 接口实现前断言集成行为|V91-V96,V98；预期 TDD 红灯，⊥ 新 invariant
B55|2026-07-26|路由测试假设 ∀ FastAPI route 有 `methods`，静态 `Mount` 无该属性|测试用 `getattr(route, "methods", set())`；非产品缺陷，⊥ 新 invariant
B56|2026-07-26|旧 stale 回归夹具缺 `watchlistRevision`，与 V95 跨目录 revision 禁止回退冲突|夹具显式同 revision 后验证来源失败 LKG；非产品缺陷，⊥ 新 invariant
B57|2026-07-26|来源行 appId 未命中后仍回退同名 alias，可能把不同商店条目误归并|V93；有来源 ID 时仅精确匹配，缺 ID 才 alias
B58|2026-07-26|榜单本次 0 关注命中 → `merge_ranking_rows` 无 replace scope，旧未关注行残留文件|V93,C40；用原始抓取 scope 清旧行并全文件重滤
B59|2026-07-26|T42 red test 在 `GameWatchlistTab`/导入删除交互/响应式样式实现前断言 V97|V97；预期 TDD 红灯，⊥ 新 invariant
B60|2026-07-26|全量 pytest 收集被既有脏 `src/ai_service.py` 缺 `migrate_ai_projects_snapshot` 阻断|本任务不改 AI；T43 保持 `~`，排除该文件继续验证其余范围；⊥ 新 invariant

## §G（GitHub AI 工具发现）

G11: `/ai#github` → 优先发现可直接使用/安装即用 AI 工具；专业 ML 训练框架、SDK、教程/合集默认隐藏；支持新上榜、近期爆发、关注与高信号提醒。

## §C（GitHub AI 工具发现）

C43: 分类拆为使用门槛+多选用途+交付形态；`MCP`/`Skill`/`CLI` ⊥ 抢占项目主体类别。
C44: GitHub Search 请求 ≤10/分钟匿名预算；新项目发现 ! 独立 recent query；release/README enrichment 有界，失败保留已有元数据。
C45: ⊥ 新 runtime dependency；⊥ GitHub 写操作；`GITHUB_TOKEN` 仅服务端可选读取公开数据。
C46: 关注项目/作者/用途、忽略/纠错、通知去重 → 浏览器本地持久化；⊥ 上传个人偏好。
C47: 历史按项目+日期 upsert，保留 ≤120 天；无足够历史 → `collecting`，⊥ 伪造 7/30 天增长。
C48: 现有 `/api/ai-projects`、刷新/stale fallback、旧字段与旧 `#github/<category>` 链接兼容；⊥ 覆盖 T31/T40 或用户无关修改。

## §R（GitHub AI 工具发现，2026-07-26）

R6: GitHub repository search → 每页 ≤100、单查询 ≤1000；sort ∈ `stars|forks|help-wanted-issues|updated`；匿名 10 req/min、认证 30 req/min。https://docs.github.com/en/rest/search/search
R7: repository search qualifiers 支持 `created:`/`pushed:` ISO8601、`stars:`、`archived:false`、`fork:false`；recent discovery 可独立查询。https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories
R8: public release read 无需认证；release 返回 `published_at`、`html_url`、assets/download metadata；core rate 与 search bucket 独立。https://docs.github.com/en/rest/releases/releases#get-the-latest-release
R9: repository contents API 的 README 响应提供 Base64 `content`；只提取安装/Quickstart/Demo 布尔信号，⊥ 持久化全文。https://docs.github.com/en/rest/repos/contents#get-a-repository-readme

## §I（GitHub AI 工具发现）

api.ai-projects: `GET /api/ai-projects` → 旧字段 + `useStages/capabilities/deliverySurfaces/discoveryViews/signals/historyStatus`。
data.ai-history: SQLite `ai_project_history(project_key,observed_date,stars,forks,pushed_at,release_at,release_tag)`；`PRIMARY KEY(project_key,observed_date)`。
ui.ai-discovery: `/ai#github/<view>` → `recommended|new|rising|followed` + 用途/形态/使用门槛筛选 + 富卡片/关注/反馈/提醒摘要。
storage.ai-preferences: localStorage `newsDigest.aiDiscoveryPreferences.v1` → projects/owners/capabilities/ignored/feedback/notification state。

## §V（GitHub AI 工具发现）

V99: ∀ project → `useStage ∈ {ready,integrate,build,train_research,resource}` + `capabilityTags[]` + `deliverySurfaces[]` + reasons/confidence；`matchedCategories` 仅 provenance，⊥ 分类兜底。
V100: 默认结果 ∈ `{ready,integrate}`；`build/train_research/resource` 仅显式开关显示；教程/Awesome/模型数据 ⊥ 混入默认榜。
V101: discovery views = `recommended/new/rising/followed`；recommended 按 usability+quality+freshness+momentum，累计 Stars 仅弱信誉项；recent query 候选 ⊥ 被累计 Stars 门槛阻断。
V102: 每日 history upsert+≤120 天清理；有 ≥7/30 天样本才输出真实 delta；release enrichment 有界+LKG；失败 ⊥ 清空旧 release。
V103: 关注 project/owner/capability + ignored/framework feedback → reload 后保持；followed 只显示匹配项；⊥ 调 GitHub star/watch API。
V104: high signal ! `useStage ∈ {ready,integrate}` 且 recent stable release ∨ qualified new project ∨ momentum threshold；其他变化 → daily digest；同 signal 只通知 1 次。
V105: 卡片首要显示 task outcome、useStage/capability/surface、安装/Demo、release、7/30 天增长、推荐理由、关注/反馈；fork/language → 次要详情。
V106: 旧 API 字段、分类 metadata、刷新/stale、`#github/<legacy-category>` → 保持可读/可导航；schema 增量升级 ⊥ 冷启动空白。
V107: 1440px/390px → filters/cards/notification summary 可用、keyboard focus 可见、zero console errors、⊥ document overflow。
V108: 分类/评分/历史/信号/兼容回归 + 全量 Python tests + `npm run build` + API + 1440/390 browser QA exit 0。
V109: enrichment 每次刷新 core requests ≤24（匿名）或 ≤80（认证）；失败/超额 → 复用 previous metadata + 标记 unavailable，⊥ 拖垮主榜。
V110: history upsert 覆盖 ∀ 有效候选后再选榜；未入榜项目后续增长仍可进入 `rising`。
V111: 旧 `ai-projects` schema → 本地 additive migration 后立即可读；联网失败 → migrated stale payload，⊥ 冷启动空白。
V112: localStorage/Notification unavailable|denied → in-memory 偏好+页内提醒仍可用；系统通知授权仅用户点击触发。

## §T（GitHub AI 工具发现）

id|status|task|cites
T44|x|实现 useStage/capability/surface 分类、可解释评分、recent search、旧字段兼容；补金标/排序测试|C43-C45,C48,R6-R7,V99-V101,V106,V111,I.api.ai-projects
T45|x|实现 SQLite 每日 Stars/Release 历史、增长、LKG enrichment、高信号/digest；补存储/信号测试|C44,C47,R8-R9,V102,V104,V109,V110,I.data.ai-history
T46|x|实现四发现视图、门槛/用途/形态筛选、关注/反馈/通知、富卡片与旧 hash 兼容|C46,C48,V100,V103-V107,V112,I.ui.ai-discovery,I.storage.ai-preferences
T47|x|定向/全量 tests、build、API schema、桌面/移动浏览器验收；核对 diff 不覆盖并行任务|C48,V108

## §B（GitHub AI 工具发现）

id|date|cause|fix
B62|2026-07-26|T44 red test 在发现分类模块创建前导入 `src.ai_discovery`|V99-V101；预期 TDD 红灯，⊥ 新 invariant
B63|2026-07-26|T44 migration red test 在本地旧快照迁移函数实现前导入接口|V106,V111；预期 TDD 红灯，⊥ 新 invariant
B64|2026-07-26|T44 新多轴语义替换旧单类别后，3 个旧测试仍断言 MCP/Skills 类型名、matchedCategories 分类回退与每旧类固定 30 项|V99-V101,V106；更新旧回归测试到新公开行为，非产品缺陷，⊥ 新 invariant
B65|2026-07-26|T44 更新后的 no-fallback 回归夹具把旧类别 ID 写进仓库名，分类器从真实名称语义识别出 MCP/Skills，导致错误期望全为 coding-agents|V101；夹具改用中性仓库名，仅隔离验证搜索命中不参与分类，⊥ 新 invariant
B66|2026-07-26|T45 red test 在历史增长、README 信号、enrichment 预算与通知信号函数实现前导入接口|V102,V104,V109,V110；预期 TDD 红灯，⊥ 新 invariant
B67|2026-07-26|T46 red test 在前端发现视图、关注偏好、反馈、旧 hash 迁移与通知权限模块创建前导入接口|V100,V103-V107,V112；预期 TDD 红灯，⊥ 新 invariant
B68|2026-07-26|T46 capability 关注在 followed 视图把同用途的 train_research 项目一并放出，绕过默认隐藏门槛|V100,V103；项目/作者的精确关注可放出隐藏项，宽泛 capability 关注仍守默认门槛，⊥ 新 invariant
B69|2026-07-26|T46 浏览器 QA 点击“开发组件”后按钮与结果不变：recommended 末级判断仍无条件要求 defaultVisible，覆盖显式门槛筛选|V100；显式 includeHiddenStages 时 recommended 服从 useStages，补前端回归，⊥ 新 invariant
B70|2026-07-26|T46 390px 浏览器 QA 显示无信号时整个提醒区被隐藏，用户无法主动开启通知；搜索的 sr-only 文本因仓库无该工具类而可见换行|V107,V112；提醒入口恒显、输入框改原生 aria-label，⊥ 新 invariant

## §G（游戏配置体验增强）

G12: 游戏页字体优化 + 国家下拉筛选 + 游戏/国家 CRUD。

## §C（游戏配置体验增强）

C49: 游戏页中文 UI 字体；字重仅 400/600/700；不引入网络字体。
C50: 国家筛选 = 单选下拉框；选项仅来自关注国家目录。
C51: 游戏/国家增删改原子持久化；`global` 基础范围保留。

## §I（游戏配置体验增强）

api.watchlist.update: `PUT /api/games/watchlist/{game_id}` → 原子更新 1 款游戏；未知 id → `404`。
api.watchlist.regions.create: `POST /api/games/watchlist/regions` → 原子新增关注国家。
api.watchlist.regions.update: `PUT /api/games/watchlist/regions/{code}` → 原子更新关注国家。
api.watchlist.regions.delete: `DELETE /api/games/watchlist/regions/{code}` → 原子删除关注国家；`global` → `400`。
ui.watchlist.manage: `/games` → `关注配置` → 游戏/国家双目录增删改；Steam 国家筛选为单选下拉框。

## §V（游戏配置体验增强）

V113: 游戏编辑与国家 CRUD 后 revision 变化，重读结果持久。
V114: 国家下拉选项与关注国家目录一致；删除当前国家 → 回退 `global`。
V115: 1440/390px 字体、下拉框、管理界面无溢出。
V116: 编辑/删除键盘可用；删除二次确认；错误不破坏原配置。
V117: 切换游戏/国家目录或取消编辑 → 状态恢复当前目录摘要，⊥ 残留旧编辑提示。

## §T（游戏配置体验增强）

id|status|task|cites
T48|x|游戏编辑与国家 CRUD 服务/API/回归测试|V113,V116,I.api.watchlist.*
T49|x|字体、国家下拉框、双目录管理界面|V114-V117,I.ui.watchlist.manage
T50|x|tests/build/API/5174 桌面与手机验收|V113-V116,C49-C51

## §B（游戏配置体验增强）

id|date|cause|fix
B71|2026-07-26|定向测试命令使用 WSL 中不存在的 `python` 入口，测试逻辑未执行|改用仓库 `.venv/bin/python`；环境入口问题，⊥ 新 invariant
B72|2026-07-26|T48 red tests 在游戏编辑、国家 CRUD/API 与新界面契约实现前断言 V113-V116|V113-V116；预期 TDD 红灯，⊥ 新 invariant
B73|2026-07-26|浏览器验收后端不支持文档列出的 `networkidle` 等待条件|改用 `domcontentloaded` + 可见 DOM 状态；工具兼容问题，⊥ 新 invariant
B74|2026-07-26|重启后 Steam 冷启动刷新超过 20 秒，浏览器等待刷新按钮恢复超时|布局与本地关注目录分离验收，不重复等待外部 Steam 刷新；⊥ 新 invariant
B75|2026-07-26|取消游戏编辑后切到国家目录仍显示旧“正在编辑”提示|V117；切换目录与取消编辑统一恢复当前目录摘要
B76|2026-07-26|390px 通用 `.secondary-action` 规则把国家管理/刷新按钮压成仅图标|V115；国家筛选操作覆盖宽度、内边距和字号，保留完整文字

## §V（今日数据健康分类修复）

V118: domain health 仅 hard source error|snapshot stale|stale/error component → non-ok；成功 fallback → `warnings`+明细，⊥ `errors`；optional derived `invalid` → value=`null`+风险/禁算说明，⊥ domain failure。
V119: commodity 8 组独立 provider → 并发启动且仍受 per-domain coordinator 限流；startup refresh ≤180s，超时保留 LKG+显式状态。
V120: ETF 成分行业映射 → 可用 `push2delay.eastmoney.com`；大批次断连 → ≤15 code 小批重试；部分缺失 → `未分类`+数量说明；全空 → 失败并保留机构配置 LKG。

## §T（今日数据健康分类修复）

id|status|task|cites
T51|x|分离 error/warning/optional invalid；并发大宗独立来源；ETF 行业映射自适应重试；刷新股票/大宗快照；tests/build/API/browser 验收|V57,V61,V65,V69,V118-V120

## §B（今日数据健康分类修复）

id|date|cause|fix
B77|2026-07-26|今日 health 把成功备用源提示写入 `errors`，并把 36 个安全禁算基差当成 domain failure；旧大宗快照还保留已修复 Sina encoding 错误|V118；诊断分层+真实刷新覆盖旧快照
B78|2026-07-26|V118 red tests 在诊断 helper/health 分类实现前 import 失败并复现 optional invalid=`partial`、stale component=`ok`|V118；预期 TDD 红灯，⊥ 新 invariant
B79|2026-07-26|大宗 8 组独立 provider 串行等待；多页/多品种子请求累计 >180s，startup refresh 超时且旧快照无法覆盖|V119；顶层有界并发，域名协调器继续限流
B80|2026-07-26|V119 red test 在 `fetch_commodity_sources` 并发入口实现前 import 失败|V119；预期 TDD 红灯，⊥ 新 invariant
B81|2026-07-26|ETF 持仓已取到后，成分行业映射按 60 code 批请求；任一批被远端断开 → 整个机构配置回退 stale|V120；大批失败后拆 ≤15 code 重试，剩余缺口显式未分类
B82|2026-07-26|V120 red test 复现 45 code 大批断连直接抛错，⊥ 小批恢复|V120；预期 TDD 红灯，⊥ 新 invariant
B83|2026-07-26|`push2.eastmoney.com/api/qt/ulist.np/get` 对 2/15/60 code 均主动断连；同接口 `push2delay.eastmoney.com` 返回完整 `f100` 行业|V120；行业映射切可用 delayed host，保留拆批恢复
B84|2026-07-26|V120 host red assertion 复现行业映射仍请求不可用 `push2`|V120；预期 TDD 红灯，⊥ 新 invariant
B85|2026-07-26|本轮新增 V/B 条目沿用前段已有编号，造成规范标识冲突|重编号为 V118-V120、B77-B84；文档一致性问题，⊥ 新 invariant

## §V（全项目 review 修复）

V121: AI project search 全失败 + valid LKG → return migrated stale LKG；⊥ previous projects 改写 fresh TTL。
V122: 200 JSON/text 业务正文仅含 `captcha`/`too many requests` → ⊥ domain circuit；风控需 403/429 ∨ 强特征 ∨ HTML verify context。
V123: startup `games-region` 全 unavailable/empty + errors → `status=error` + `refreshed=false` + version 不增；⊥ `done`。
V124: today health 全 `unavailable|empty|error` → `hasData=false`；∃ `ok|partial|stale` → true。
V125: system notification → 仅 delivered signal IDs 标 seen；constructor failure 后未发送 IDs ! retryable。
V126: `MAX_REGIONS` 含自动 `global`；100 non-global input → reject，⊥ return 101。

## §T（全项目 review 修复）

id|status|task|cites
T52|x|修复 stale/风控/刷新健康/通知去重/地区上限并补回归|V121-V126,I.api.ai-projects,I.module,I.startup,I.ui.health,I.storage.ai-preferences,I.data.watchlist

## §B（全项目 review 修复）

id|date|cause|fix
B86|2026-07-26|search errors + previous merge 早于 empty fallback → stale LKG 重标 fresh|V121
B87|2026-07-26|body marker scan 将业务正文通用词误判 verification page|V122
B88|2026-07-26|`games-region` 缺 `hasData`；refresh 默认 true → empty refresh 标 done|V123
B89|2026-07-26|today `hasData` 排除 error/empty 但遗漏 unavailable|V124
B90|2026-07-26|notify 仅返回 count；caller partial failure 后标记全部 unseen|V125
B91|2026-07-26|region 上限校验早于自动插入 `global`|V126
