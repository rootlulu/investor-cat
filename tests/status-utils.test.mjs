import assert from "node:assert/strict";
import test from "node:test";

import {
  compactIssueSummary,
  joinIssueDetails,
  summarizeStatusText
} from "../frontend/src/status-utils.js";

test("V153 latest refresh failure wins over stale snapshot warning", () => {
  const result = summarizeStatusText(
    "已更新：07/27 22:54；部分来源异常：Returns：近7天无结果；新闻刷新超时（180秒），已保留旧快照"
  );

  assert.equal(result.problem, "新闻刷新超时（180秒），已保留旧快照");
  assert.equal(result.summary, "已更新：07/27 22:54 · 新闻刷新超时（180秒），已保留旧快照");
  assert.equal(result.failed, true);
});

test("V153 compact issue summary names first cause and count", () => {
  assert.equal(
    compactIssueSummary(["Reuters：请求超时", "", "Bloomberg：请求限流"]),
    "Reuters：请求超时（另1项）"
  );
});

test("V153 warning details stay inside the non-error source-hint segment", () => {
  const warnings = ["Returns：近7天无匹配新闻", "标题翻译：超时，已使用本地标题"];
  const result = summarizeStatusText(
    `已更新：07/28 21:38；缓存；来源提示：${compactIssueSummary(warnings)}；来源提示明细：${joinIssueDetails(warnings)}`
  );

  assert.equal(joinIssueDetails(warnings), "Returns：近7天无匹配新闻、标题翻译：超时，已使用本地标题");
  assert.equal(result.problem, undefined);
  assert.equal(result.summary, "已更新：07/28 21:38 · 缓存");
});
