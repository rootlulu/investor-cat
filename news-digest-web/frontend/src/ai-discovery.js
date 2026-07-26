const STORAGE_KEY = "newsDigest.aiDiscoveryPreferences.v1";

export const AI_DISCOVERY_VIEWS = [
  { id: "recommended", label: "为你推荐", description: "优先展示可直接使用或简单安装后即可使用的 AI 工具。" },
  { id: "new", label: "新上榜", description: "独立搜索与近期创建信号发现的新项目，不被累计 Stars 榜单淹没。" },
  { id: "rising", label: "近期爆发", description: "按真实 7 / 30 天 Stars 增长排序；样本不足时不会伪造趋势。" },
  { id: "followed", label: "已关注", description: "你关注的项目、作者和用途标签。" }
];

export const DEFAULT_AI_PREFERENCES = Object.freeze({
  version: 1,
  followedProjects: [],
  followedOwners: [],
  followedCapabilities: [],
  ignoredProjects: [],
  feedbackByProject: {},
  systemNotifications: false,
  seenSignalIds: []
});

let memoryPreferences = clonePreferences(DEFAULT_AI_PREFERENCES);

export function aiProjectKey(project) {
  return String(project?.fullName || project?.id || "").trim().toLowerCase();
}

export function normalizeAiPreferences(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    version: 1,
    followedProjects: uniqueStrings(source.followedProjects),
    followedOwners: uniqueStrings(source.followedOwners),
    followedCapabilities: uniqueStrings(source.followedCapabilities),
    ignoredProjects: uniqueStrings(source.ignoredProjects),
    feedbackByProject: source.feedbackByProject && typeof source.feedbackByProject === "object"
      ? { ...source.feedbackByProject }
      : {},
    systemNotifications: Boolean(source.systemNotifications),
    seenSignalIds: uniqueStrings(source.seenSignalIds).slice(-500)
  };
}

export function loadAiPreferences(storage = globalThis?.localStorage) {
  try {
    const encoded = storage?.getItem(STORAGE_KEY);
    if (!encoded) return clonePreferences(memoryPreferences);
    memoryPreferences = normalizeAiPreferences(JSON.parse(encoded));
  } catch {
    return clonePreferences(memoryPreferences);
  }
  return clonePreferences(memoryPreferences);
}

export function saveAiPreferences(preferences, storage = globalThis?.localStorage) {
  memoryPreferences = normalizeAiPreferences(preferences);
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(memoryPreferences));
    return Boolean(storage);
  } catch {
    return false;
  }
}

export function toggleAiFollow(preferences, kind, value) {
  const result = normalizeAiPreferences(preferences);
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return result;
  const field = {
    project: "followedProjects",
    owner: "followedOwners",
    capability: "followedCapabilities"
  }[kind];
  if (!field) return result;
  const values = new Set(result[field]);
  values.has(normalized) ? values.delete(normalized) : values.add(normalized);
  result[field] = [...values];
  return result;
}

export function isProjectFollowed(project, preferences) {
  const normalized = normalizeAiPreferences(preferences);
  const projectKey = aiProjectKey(project);
  const owner = String(project?.owner || project?.fullName?.split("/")[0] || "").toLowerCase();
  const capabilities = new Set((project?.capabilityTags || []).map((value) => String(value).toLowerCase()));
  return normalized.followedProjects.includes(projectKey)
    || normalized.followedOwners.includes(owner)
    || normalized.followedCapabilities.some((value) => capabilities.has(value));
}

export function recordProjectFeedback(preferences, projectKey, feedback) {
  const result = normalizeAiPreferences(preferences);
  const key = String(projectKey || "").trim().toLowerCase();
  if (!key) return result;
  result.feedbackByProject[key] = String(feedback || "");
  const ignored = new Set(result.ignoredProjects);
  if (["not-relevant", "framework"].includes(feedback)) ignored.add(key);
  if (feedback === "useful") ignored.delete(key);
  result.ignoredProjects = [...ignored];
  return result;
}

export function filterAiProjects(projects, options = {}, preferences = DEFAULT_AI_PREFERENCES) {
  const view = options.view || "recommended";
  const normalized = normalizeAiPreferences(preferences);
  const ignored = new Set(normalized.ignoredProjects);
  const stageFilter = options.useStages?.length
    ? new Set(options.useStages)
    : view === "followed" || options.includeHiddenStages
      ? null
      : new Set(["ready", "integrate"]);
  const capabilities = new Set(options.capabilities || []);
  const surfaces = new Set(options.surfaces || []);
  const query = String(options.query || "").trim().toLowerCase();
  const current = options.now instanceof Date ? options.now : new Date();

  const result = (projects || []).filter((project) => {
    const key = aiProjectKey(project);
    if (!key || ignored.has(key)) return false;
    if (stageFilter && !stageFilter.has(project.useStage)) return false;
    if (capabilities.size && !project.capabilityTags?.some((value) => capabilities.has(value))) return false;
    if (surfaces.size && !project.deliverySurfaces?.some((value) => surfaces.has(value))) return false;
    if (query) {
      const haystack = [project.fullName, project.description, project.descriptionZh, ...(project.topics || [])]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (view === "followed") {
      const owner = String(project?.owner || project?.fullName?.split("/")[0] || "").toLowerCase();
      const directFollow = normalized.followedProjects.includes(key) || normalized.followedOwners.includes(owner);
      const capabilityFollow = normalized.followedCapabilities.some((value) => project.capabilityTags?.includes(value));
      return directFollow || (capabilityFollow && (options.includeHiddenStages || project.defaultVisible));
    }
    if (view === "new") {
      if ((project.discoveryModes || []).includes("recent")) return true;
      const createdAt = Date.parse(project.createdAt || "");
      return Number.isFinite(createdAt) && current.getTime() - createdAt <= 180 * 86_400_000;
    }
    if (view === "rising") {
      return project.historyStatus === "ready"
        && (Number(project.stars7dDelta || 0) > 0 || Number(project.stars30dDelta || 0) > 0);
    }
    return options.includeHiddenStages
      || Boolean(project.defaultVisible ?? ["ready", "integrate"].includes(project.useStage));
  });

  return result.sort((left, right) => {
    if (view === "new") {
      const dateDelta = Date.parse(right.createdAt || 0) - Date.parse(left.createdAt || 0);
      if (Number.isFinite(dateDelta) && dateDelta) return dateDelta;
    }
    if (view === "rising") {
      const delta7 = Number(right.stars7dDelta || 0) - Number(left.stars7dDelta || 0);
      if (delta7) return delta7;
      const delta30 = Number(right.stars30dDelta || 0) - Number(left.stars30dDelta || 0);
      if (delta30) return delta30;
    }
    return Number(right.discoveryScore || 0) - Number(left.discoveryScore || 0)
      || Number(right.stars || 0) - Number(left.stars || 0);
  });
}

export function parseAiDiscoveryHash(hash) {
  const [section, legacyCategory] = String(hash || "").replace(/^#/, "").split("/");
  if (section !== "github") return { view: "recommended" };
  if (AI_DISCOVERY_VIEWS.some((view) => view.id === legacyCategory)) return { view: legacyCategory };
  const mappings = {
    skills: { view: "recommended", useStages: ["integrate"], surfaces: ["skill"] },
    mcp: { view: "recommended", surfaces: ["mcp_server"] },
    "coding-agents": { view: "recommended" },
    "agent-frameworks": { view: "recommended", useStages: ["build"], includeHiddenStages: true },
    "dev-workflows": { view: "recommended", capabilities: ["context_memory"] }
  };
  return mappings[legacyCategory] ? { ...mappings[legacyCategory] } : { view: "recommended" };
}

export async function requestAiNotificationPermission(NotificationApi = globalThis?.Notification) {
  if (!NotificationApi) return "unsupported";
  if (NotificationApi.permission !== "default") return NotificationApi.permission;
  try {
    return await NotificationApi.requestPermission();
  } catch {
    return "denied";
  }
}

export function markAiSignalsSeen(preferences, signalIds) {
  const result = normalizeAiPreferences(preferences);
  result.seenSignalIds = uniqueStrings([...result.seenSignalIds, ...(signalIds || [])]).slice(-500);
  return result;
}

export function notifyAiSignals(signals, preferences, NotificationApi = globalThis?.Notification) {
  if (!preferences?.systemNotifications || !NotificationApi || NotificationApi.permission !== "granted") return [];
  const seen = new Set(preferences.seenSignalIds || []);
  const notifiedSignalIds = [];
  for (const signal of signals || []) {
    if (!signal?.eventId || seen.has(signal.eventId)) continue;
    try {
      new NotificationApi(signal.title || "AI 项目新动态", { body: signal.reason || "", tag: signal.eventId });
      notifiedSignalIds.push(signal.eventId);
    } catch {
      return notifiedSignalIds;
    }
  }
  return notifiedSignalIds;
}

function clonePreferences(preferences) {
  return normalizeAiPreferences(preferences);
}

function uniqueStrings(values) {
  return [...new Set((Array.isArray(values) ? values : []).map((value) => String(value).trim().toLowerCase()).filter(Boolean))];
}
