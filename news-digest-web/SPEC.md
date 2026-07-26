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

G2: 游戏页新增「区域」子 tab（排在第一个），展示所选地区（全球 + 30 个国家/地区，共 31 个）的 Steam 热销榜排名，以及固定游戏清单的在线人数趋势（全球并发口径）。
G3: 固定游戏清单来自 `config/game_region_watchlist.json`；缺失 steamAppId 或取数失败的游戏，在线人数显示「—」，禁止伪造。
G4: 其余子 tab（流水总览 / 榜单 / 数据导入）本阶段先留空壳占位，现有 Top100 流水与点点/七麦国家榜保留在「流水总览」「榜单」中，不丢失现有能力。

## §C（游戏区域）

C11: 热销榜取自 Steam 热销榜（按地区 cc），仅标注进入榜单的固定游戏名次；未进入榜单显示「—」。
C12: 在线人数趋势 = Steam Charts 月度均值/峰值 + Steam 当前在线 API 实时并发；均为全球口径，随地区切换不变化，但在区域视图内呈现。
C13: 数据来源失败（风控/超时）时保留上次有效快照并标记 stale，前端展示警告，禁止报错中断页面。
C14: 缓存复用 SQLite `latest_games_region` 表，按地区 id 单行覆盖；默认半小时最小刷新间隔。

## §I（游戏区域）

ui: 游戏页子 tab 栏 → 区域（热销榜表 + 在线人数趋势折线图）/ 流水总览 / 榜单 / 数据导入。
api: `GET /api/games/region?cc=global`（支持 `?refresh=true`）。
data: 固定清单 `config/game_region_watchlist.json`（`games[].appId/name/nameZh/publisher/group`，`regions[].code/name`）。
source.hot: Steam 热销榜 `store.steampowered.com/charts/topselling/{cc}`。
source.players: SteamCharts `steamcharts.com/app/{appId}` + Steam 当前在线 API `GetNumberOfCurrentPlayers`。

## §V（游戏区域）

V15: 默认进入「区域」子 tab；地区选择器为可横向滚动的胶囊按钮，全球排首位。
V16: 热销榜表格列：排名 / 游戏（中+英） / 厂商 / 实时在线 / 峰值 / 近月均值；进入榜单者按名次升序，未进入者列末。
V17: 在线人数趋势为 SVG 多序列折线图，X 为月份、Y 为月度均值；图例可逐个显隐序列，默认全部显示。
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

## §Browser（模拟浏览器抓取）

B-m1: 所有对外 Steam / 雪球 / 三方数据抓取统一走 `src/browser_service.py` 的模拟浏览器（Playwright Chromium 持久化上下文），禁止裸 httpx 直连——此前直连已被 Steam 风控封 IP。
B-m2: `browser_service` 提供进程级单例浏览器会话（`_ensure_session` + `atexit` 关闭），`fetch_html_via_browser` / `fetch_json_via_browser` 通过 `asyncio.to_thread` 包装同步 Playwright 调用，失败自动重试（默认 2 次，失败时重置会话）。
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

## §T（Steam 抓取修复）

id|status|task|cites
T13|x|修复 Steam proxy/browser/top-sellers/cache/UI error path + Steam/Sensor Tower 分区|V20-V25,I.api,I.source.*

## §B（Steam 抓取修复）

id|date|cause|fix
B2|2026-07-26|runtime route stale + Chromium libs missing + Steam Store direct timeout + DOM no appId + error hidden/source status mixed|V20-V25
B3|2026-07-26|全量验证误用系统 Python；pytest 测试模块无法导入|改用项目环境或隔离测试依赖；非产品代码缺陷
