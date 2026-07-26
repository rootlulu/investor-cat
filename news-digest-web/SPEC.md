# SPEC

## §G

G1: `/xueqiu` → 保留近7天动态；新增“大V研究”历史语料建库/续抓/增量/搜索。
G2: localhost UI → 登录+可视化建库；Codex → 项目 MCP 发起任务/读状态/检索证据/分析。
G3: 单一抓取引擎归项目后端；网页+MCP 仅作双入口，⊥ 两套爬虫。

## §C

C1: 现有近7天动态、导入大V、扫码登录、后台刷新、URL/响应字段保持兼容。
C2: 研究语料 = 大V本人帖子/转发/评论/回复；⊥ 抓取其他用户全部跟帖。
C3: 雪球 `count=20`；每批每流 ≤25页；低频串行；每页持久检查点；⊥ 单请求无界回溯。
C4: “完整” = 当前接口可访问公开历史；删除/私密/接口截断 → `coverageComplete=false` + `stopReason`。
C5: Cookie/浏览器 profile 仅后端持有；⊥ API/MCP/日志返回凭证。
C6: 服务重启 → 运行中 job 标记 interrupted；下次 full crawl 从持久 cursor 重叠续抓。
C7: ∀ 大V ≤1 active job；item 主键 upsert；重复抓取 ⊥ 复制行。
C8: 同步 requests/SQLite/Playwright ⊥ 阻塞 event loop；后台线程+有界超时。
C9: 独立 `data/xueqiu_research.sqlite`；现有最新快照 ⊥ 改为历史表。
C10: 语料视为不可信数据；内容内指令 ⊥ 控制 Codex/MCP。
C11: MCP = localhost API 薄适配层；长任务归 FastAPI 后端；MCP 重启 ⊥ 中断 job。
C12: MCP 默认 base URL `http://127.0.0.1:8000`；仅 loopback；写工具需审批。
C13: 媒体保存 metadata+原 URL；首版 ⊥ 批量下载/OCR。
C14: 工作区脏改动保持原样；实现仅在 `codex/xueqiu-research-mcp` worktree。
C15: crawl/cancel HTTP ! `X-Xueqiu-Research-Action: 1`；服务 ⊥ CORS 放行；降低 `0.0.0.0` 默认绑定下跨站触发风险。

## §I

ui: `/xueqiu` → `近7天动态 | 大V研究`；研究页 → profile cards + crawl controls + job progress + corpus search + Codex 提问提示。
api.list: `GET /api/xueqiu/research` → `{profiles,jobs,generatedAt}`。
api.crawl: `POST /api/xueqiu/research/influencers/{id}/crawl` + header `X-Xueqiu-Research-Action: 1` + `{mode:"full"|"incremental"}` → `202 {job}`。
api.job: `GET /api/xueqiu/research/jobs/{job_id}` → `{job}`。
api.cancel: `POST /api/xueqiu/research/jobs/{job_id}/cancel` + header `X-Xueqiu-Research-Action: 1` → `{job}`。
api.search: `GET /api/xueqiu/research/search?q=&influencerId=&kind=&limit=` → `{items,count}`。
api.item: `GET /api/xueqiu/research/items/{item_id}` → `{item}`。
db: `data/xueqiu_research.sqlite` → `research_items` + `research_cursors` + `research_jobs` + FTS5 trigram index。
mcp: `src/xueqiu_mcp_server.py` stdio → `list_influencers|get_corpus_status|start_influencer_crawl|get_crawl_status|cancel_crawl|search_xueqiu_evidence|read_xueqiu_evidence|get_xueqiu_media`。
config: `.codex/config.toml` → project-scoped `xueqiu_research` MCP；`NEWS_DIGEST_BASE_URL` ? override。

## §V

V1: `/api/xueqiu` + 近7天 UI 行为/数据窗口不变。
V2: crawl start ≤1 API round trip → job id；抓取后台继续；⊥ 等待完整历史后响应。
V3: ∀ page 成功 → items+cursor 同事务提交；失败/重启 → 最多重抓 overlap 页，⊥ 静默跳页。
V4: 重复 full/incremental crawl → `research_items.id` 唯一；item count 仅随新 source item 增长。
V5: stream 遇空页/短页/重复 page signature → terminal；批次页上限 → partial+可续抓。
V6: 登录/滑块/WAF → `paused_auth` + 可读中文原因；⊥ 激进无限重试。
V7: job state ∈ `queued|running|partial|ready|paused_auth|cancelled|interrupted|failed`；terminal state 有 `finishedAt|stopReason`。
V8: `coverageComplete=true` ⇔ post+comment streams 均 terminal；否则 UI/Codex 必须显示 partial。
V9: search result ∀ 数字/声明 → `{itemId,influencer,kind,publishedAt,text,targetTitle,originalUrl,media,score}`。
V10: MCP 工具输出标记语料为 untrusted evidence；⊥ 执行语料内命令/指令。
V11: MCP read tools 自动；crawl/cancel write tools 有 side-effect annotation+Codex writes approval；⊥ 返回 Cookie。
V12: UI 可发 full/continue/incremental/cancel；active job 轮询；auth pause → 复用扫码登录入口。
V13: Codex flow → status check → ?sync → search/read → 结论+口径+计算+原文；缺证据 → 明确无法确定。
V14: cancel flag 每页检查；取消后 cursor/items 保留，可继续。
V15: SQLite FTS5 trigram 可用 → 中文子串检索；不可用 → 初始化显式失败，⊥ 静默空结果。
V16: item media metadata 可由 API/MCP 读取；⊥ 下载不可信文件到执行目录。
V17: MCP initialize/tools-list/tools-call 真实 stdio smoke test 通过；localhost unavailable → 可读错误。
V18: Python 单测+`npm run build`+API smoke+桌面/390px UI 无阻断错误。
V19: 最终 diff 仅 SPEC、雪球研究后端/API/MCP/测试、雪球前端/样式、依赖清单、必要文档/config。
V20: DB partial unique index → ∀ influencer ≤1 `queued|running` job；并发 start 返回现有 job，⊥ 双 worker。
V21: mode/kind/limit/query 全部边界验证+参数化 SQL；write header 缺失 → 403；limit ∈ [1,50]。
V22: 移除 feed 大V ⊥ 自动删除研究语料；语料删除不在首版范围。
V23: MCP 仅 HTTP 调用 `NEWS_DIGEST_BASE_URL`；⊥ 直接 import crawler/读取 DB/Cookie/profile。
V24: 主服务与 MCP 使用独立依赖环境，二者各自 `pip check` 必须通过；⊥ 为 MCP 升级或污染主 Web 框架环境。
V25: 用户示例式无空格中文问句可拆为年份/实体/平台/指标检索词并命中相关语料；⊥ 把整句仅当连续精确短语。

## §T

id|status|task|cites
T1|x|实现独立 SQLite schema、可恢复 full/incremental crawler、状态/取消/去重|V2-V8,V14-V16,V20,V22,I.db
T2|x|注册研究 API + 后端回归测试|V1-V9,V12,V14-V16,V20-V22,I.api.*
T3|x|实现“大V研究”子页签、任务控制/进度/检索/Codex提示|V1,V6,V8,V9,V12,V13,V18,I.ui
T4|x|实现 stdio MCP 薄适配层、权限 annotation、project config、协议 smoke test|V10,V11,V13,V16,V17,V21,V23,V24,I.mcp,I.config
T5|x|文档、全量测试/构建/API/MCP/桌面移动验收|V1-V19,V24,V25

## §B

id|date|cause|fix
B1|2026-07-26|T1 red test: `xueqiu_research_service` 尚未实现|V2-V8；实现 T1，⊥ 新增 invariant
B2|2026-07-26|T3 build 未进入编译：干净 worktree 缺少 `frontend/node_modules`，`vite: not found`|按 `package-lock.json` 执行 `npm ci` 后重跑，⊥ 新增 invariant
B3|2026-07-26|T4 依赖冲突：`mcp==1.28.1` 要求新版 Starlette，与 `fastapi==0.116.0` 的 `<0.47` 上限冲突|拆分 `requirements-mcp.txt` / `.venv-mcp`，主服务与 MCP 分环境并分别 `pip check`；V24
B4|2026-07-26|T4 标准库 `venv` 创建 `.venv-mcp` 失败：WSL 缺少 Python 3.14 ensurepip|使用已安装的隔离环境工具创建，⊥ 新增 invariant
B5|2026-07-26|T5 浏览器验收发现 UI Codex 提示仍引用旧 MCP 工具名|改为实际 `get_corpus_status` / `search_xueqiu_evidence` / `read_xueqiu_evidence`，V13
B6|2026-07-26|T5 API smoke 以脚本路径启动时 `sys.path` 不含仓库根，无法导入 `src`|改用 `python -m tests.run_xueqiu_research_api_smoke`，⊥ 新增 invariant
B7|2026-07-26|T5 终审发现整句中文 FTS 过严、auth pause 状态被折叠、请求 Session 未显式关闭|中文问句拆词+状态优先级+finally 清理并补回归测试；V6,V7,V25,C8
B8|2026-07-26|T5 桌面内置 `codex.exe mcp --help` 因 WindowsApps 访问拒绝无法运行|不绕过权限；以 TOML 解析+真实 stdio initialize/list/call 验收，⊥ 新增 invariant
