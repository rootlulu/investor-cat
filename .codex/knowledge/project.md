# 项目知识

## 架构与入口

- 后端：Python/FastAPI，入口 `src/app.py`，默认 `127.0.0.1:5173`。
- 前端：React/Vite，入口 `frontend/src/App.jsx`，现有开发服务默认 `127.0.0.1:5174`。
- 项目级 MCP：`.codex/config.toml` 注册 `src.news_digest_mcp_server`，读取本机后端。
- 规格与回归历史：`SPEC.md`。

## 服务约束

- 修改完成后可重启现有项目服务。
- 禁止新开第二个前端、第二个 Vite 实例或新端口；只复用或重启当前服务。
- 若当前前端未运行，先告知用户，不得自行启动。

## 验证命令

- 最小 Python 测试：`.venv/bin/python -m unittest <test-path> -v`。
- 全量 Python 测试：`.venv/bin/python -m unittest discover -s tests -v`。
- 前端构建：`npm run build`。
- 差异检查：从父仓库运行 `git diff --check`。

## 数据与工作区边界

- `data/news.sqlite`、JSON watchlist/cache 与生成产物可能是运行中数据；保留现有修改。
- 刷新型存储默认只保留最新可用快照；改持久化前读取 `.codex/skills/latest-snapshot-only/SKILL.md`。
- 不因测试或合并清理、还原、覆盖用户脏工作区。

## Sensor Tower 流水榜

- 后端链路位于 `src/game_service.py`，回归测试位于 `tests/test_game_sensor_tower.py`；`/api/games` 返回全球/中国两个市场的 `top100` 与 `coverage`。
- 同游戏、市场、月份的流水采用官方披露 > 权威媒体 > Sensor Tower 授权 API/正式导出 > 公开转述；关注清单仅补 identity，不过滤或重排流水榜源数据。
- 授权 Token 仅从服务端 `SENSORTOWER_AUTH_TOKEN` 读取。无有效授权时，GACHAREVENUE 公开兜底需先初始化会话，再为每个 GET 获取含 method/nonce 的签名。
- 公开兜底仅代表其移动端二游/抽卡样本；中国 Android 按中国 iOS 估算的 1.75 倍推算，不含 PC、主机和广告收入。目标不足 100 条时保留真实缺口，不补 0 或虚构排名。
- 最小验证：`.venv/bin/python -m pytest tests/test_game_sensor_tower.py tests/test_game_watchlist_integration.py tests/test_game_provider_service.py -q`；再执行 `npm run build` 与运行态 `/api/games` 检查。

## AI 新闻标题

- 抓取与翻译链路位于 `src/ai_service.py`，回归测试位于 `tests/test_ai_service.py`。
- 标题翻译失败时保留抓取原文和 `originalTitle`，状态记为 `original`；禁止用“分类名+最新动态”覆盖真实标题。
- 旧 `translationStatus=fallback` 缓存不得继续复用；下次刷新应重新翻译或展示原文。

## GitHub 项目榜与提醒

- `/ai#github` 入榜硬门槛：`stars >= 1000`，或 `historyStatus=ready` 且 `stars7dDelta >= 100` / `stars30dDelta >= 500`；增长采集中不算资格。
- 默认榜按 Stars 总数降序，近期爆发按 7 天、30 天增长数降序；`discoveryScore` 不参与入榜、排序、enrichment 优先级或 UI 展示。schema 7 读取旧快照时重新筛选。

- `/ai#github` 提醒区默认显示 4 条并明确展示总数；`查看全部` 可展开当前全部提醒。
- 每轮 unseen signals 只创建 1 条系统汇总通知；构造成功后整批 eventId 写入 `seenSignalIds`，相同批次刷新不再通知。
