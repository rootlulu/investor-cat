const STORAGE_KEY = "newsDigest.aiDiscoveryPreferences.v1";
const MIN_TOTAL_STARS = 1000;
const MIN_7D_STAR_GROWTH = 100;
const MIN_30D_STAR_GROWTH = 500;

export const AI_DISCOVERY_VIEWS = [
  { id: "recommended", label: "高 Stars", description: "仅展示 Stars 总数或真实增长达标的项目，按 Stars 总数排序。" },
  { id: "new", label: "新上榜", description: "仅从 Stars 总数或真实增长达标的项目中查看近期创建项目。" },
  { id: "rising", label: "近期爆发", description: "仅展示达到门槛的真实 7 / 30 天 Stars 增长；采集中不入榜。" },
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

export function getAiProjectSelectionBasis(project) {
  const basis = [];
  if (Number(project?.stars || 0) >= MIN_TOTAL_STARS) basis.push("total-stars");
  if (project?.historyStatus !== "ready") return basis;
  if (Number(project?.stars7dDelta || 0) >= MIN_7D_STAR_GROWTH) basis.push("7d-growth");
  if (Number(project?.stars30dDelta || 0) >= MIN_30D_STAR_GROWTH) basis.push("30d-growth");
  return basis;
}

export function getAiProjectSelectionLabel(project) {
  const basis = getAiProjectSelectionBasis(project);
  const labels = [];
  if (basis.includes("total-stars")) labels.push("高 Stars");
  if (basis.includes("7d-growth")) labels.push("7 天增长");
  if (basis.includes("30d-growth")) labels.push("30 天增长");
  return labels.join(" + ") || "未达标";
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
    const selectionBasis = getAiProjectSelectionBasis(project);
    if (!selectionBasis.length) return false;
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
      return selectionBasis.includes("7d-growth") || selectionBasis.includes("30d-growth");
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
    return Number(right.stars || 0) - Number(left.stars || 0)
      || Number(right.stars7dDelta || 0) - Number(left.stars7dDelta || 0)
      || Number(right.stars30dDelta || 0) - Number(left.stars30dDelta || 0);
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

export function buildAiSignalDisplay(signals, expanded = false, previewLimit = 4) {
  const items = Array.isArray(signals) ? signals : [];
  const limit = Math.max(0, Number(previewLimit) || 0);
  const visibleItems = expanded ? items : items.slice(0, limit);
  return {
    items: visibleItems,
    totalCount: items.length,
    hiddenCount: Math.max(0, items.length - visibleItems.length),
  };
}

export function notifyAiSignals(signals, preferences, NotificationApi = globalThis?.Notification) {
  if (!preferences?.systemNotifications || !NotificationApi || NotificationApi.permission !== "granted") return [];
  const seen = new Set(preferences.seenSignalIds || []);
  const unseenSignals = [];
  const queuedIds = new Set();
  for (const signal of signals || []) {
    if (!signal?.eventId || seen.has(signal.eventId) || queuedIds.has(signal.eventId)) continue;
    queuedIds.add(signal.eventId);
    unseenSignals.push(signal);
  }
  if (!unseenSignals.length) return [];

  const firstSignal = unseenSignals[0];
  const notificationCount = unseenSignals.length;
  const title = notificationCount === 1
    ? firstSignal.title || "AI 项目新动态"
    : `${notificationCount} 条 GitHub 项目新提醒`;
  const body = notificationCount === 1
    ? firstSignal.reason || "打开 AI 情报查看详情。"
    : `${firstSignal.title || "有新的项目动态"}；另有 ${notificationCount - 1} 条，打开 AI 情报查看。`;
  try {
    new NotificationApi(title, {
      body,
      tag: "ai-project-alert-summary",
      renotify: false,
    });
  } catch {
    return [];
  }
  return unseenSignals.map((signal) => signal.eventId);
}

export function selectAiAlertSignals(projects, signalGroups, preferences) {
  const normalized = normalizeAiPreferences(preferences);
  const followedProjects = new Set(normalized.followedProjects);
  const ignoredProjects = new Set(normalized.ignoredProjects);
  const projectKeyByEventId = new Map();

  for (const project of projects || []) {
    const projectKey = aiProjectKey(project);
    for (const level of ["high", "digest"]) {
      for (const signal of project?.signals?.[level] || []) {
        if (signal?.eventId && projectKey) projectKeyByEventId.set(signal.eventId, projectKey);
      }
    }
  }

  const projectKeyForSignal = (signal) => String(
    signal?.projectKey
      || signal?.fullName
      || projectKeyByEventId.get(signal?.eventId)
      || ""
  ).trim().toLowerCase();
  const isFollowedRelease = (signal) => {
    if (signal?.type !== "release") return false;
    const projectKey = projectKeyForSignal(signal);
    return followedProjects.has(projectKey) && !ignoredProjects.has(projectKey);
  };
  const alertsById = new Map();

  for (const signal of signalGroups?.high || []) {
    if (!signal?.eventId) continue;
    alertsById.set(signal.eventId, {
      ...signal,
      followedRelease: isFollowedRelease(signal),
    });
  }
  for (const signal of signalGroups?.digest || []) {
    if (!signal?.eventId || !isFollowedRelease(signal)) continue;
    alertsById.set(signal.eventId, { ...signal, followedRelease: true });
  }

  return [...alertsById.values()].sort((left, right) => {
    const followedDelta = Number(Boolean(right.followedRelease)) - Number(Boolean(left.followedRelease));
    if (followedDelta) return followedDelta;
    const occurredDelta = Date.parse(right.occurredAt || 0) - Date.parse(left.occurredAt || 0);
    return Number.isFinite(occurredDelta) ? occurredDelta : 0;
  });
}

function clonePreferences(preferences) {
  return normalizeAiPreferences(preferences);
}

function uniqueStrings(values) {
  return [...new Set((Array.isArray(values) ? values : []).map((value) => String(value).trim().toLowerCase()).filter(Boolean))];
}
