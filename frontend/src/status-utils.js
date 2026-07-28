const STATUS_PROBLEM_RE = /失败|异常|错误|超时|限流|风控|不可用/;

function normalizeIssues(values) {
  return [...new Set(
    (Array.isArray(values) ? values : [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)
  )];
}

export function summarizeStatusText(status) {
  const text = String(status || "暂无更新状态");
  const segments = text.split("；").map((segment) => segment.trim()).filter(Boolean);
  const problem = [...segments]
    .reverse()
    .find((segment) => !segment.startsWith("来源提示") && STATUS_PROBLEM_RE.test(segment));
  const summarySegments = [segments[0], problem || segments[1]].filter(Boolean);
  const summary = [...new Set(summarySegments)].join(" · ");
  const hasDetails = segments.length > summarySegments.length;
  const failed = Boolean(
    problem
    && !problem.startsWith("部分")
    && /(?:刷新|获取|请求).*(?:失败|错误|超时)|(?:失败|错误|超时).*(?:刷新|获取|请求)/.test(problem)
  );
  return { text, problem, summary, hasDetails, failed };
}

export function compactIssueSummary(values) {
  const issues = normalizeIssues(values);
  if (!issues.length) return "";
  return issues.length === 1 ? issues[0] : `${issues[0]}（另${issues.length - 1}项）`;
}

export function joinIssueDetails(values) {
  return normalizeIssues(values).join("、");
}
