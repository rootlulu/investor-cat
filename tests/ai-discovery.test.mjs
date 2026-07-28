import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAiSignalDisplay,
  DEFAULT_AI_PREFERENCES,
  filterAiProjects,
  getAiProjectSelectionLabel,
  isProjectFollowed,
  loadAiPreferences,
  markAiSignalsSeen,
  notifyAiSignals,
  parseAiDiscoveryHash,
  recordProjectFeedback,
  requestAiNotificationPermission,
  saveAiPreferences,
  selectAiAlertSignals,
  toggleAiFollow
} from "../frontend/src/ai-discovery.js";

const projects = [
  {
    id: 1,
    fullName: "demo/ready",
    owner: "demo",
    useStage: "ready",
    defaultVisible: true,
    capabilityTags: ["programming"],
    deliverySurfaces: ["cli"],
    stars: 5000,
    discoveryScore: 80,
    discoveryModes: ["popular"]
  },
  {
    id: 2,
    fullName: "new/tool",
    owner: "new",
    useStage: "integrate",
    defaultVisible: true,
    capabilityTags: ["agent_extensions"],
    deliverySurfaces: ["mcp_server"],
    stars: 1200,
    discoveryScore: 70,
    discoveryModes: ["recent"],
    createdAt: "2026-07-20T00:00:00Z"
  },
  {
    id: 3,
    fullName: "framework/core",
    owner: "framework",
    useStage: "build",
    defaultVisible: false,
    capabilityTags: ["automation"],
    deliverySurfaces: ["sdk", "library"],
    stars: 300,
    discoveryScore: 95,
    stars7dDelta: 500,
    historyStatus: "ready"
  },
  {
    id: 4,
    fullName: "ml/train",
    owner: "ml",
    useStage: "train_research",
    defaultVisible: false,
    capabilityTags: ["programming"],
    deliverySurfaces: ["library"],
    stars: 20000,
    discoveryScore: 99
  },
  {
    id: 5,
    fullName: "low-stars/collecting",
    owner: "low-stars",
    useStage: "integrate",
    defaultVisible: true,
    capabilityTags: ["agent_extensions"],
    deliverySurfaces: ["mcp_server"],
    stars: 192,
    stars7dDelta: null,
    stars30dDelta: null,
    historyStatus: "collecting",
    discoveryScore: 100
  }
];

test("V160 recommended view admits only qualified Stars and sorts by total Stars", () => {
  const visible = filterAiProjects(projects, { view: "recommended" }, DEFAULT_AI_PREFERENCES);
  const withFrameworks = filterAiProjects(
    projects,
    { view: "recommended", useStages: ["ready", "integrate", "build"], includeHiddenStages: true },
    DEFAULT_AI_PREFERENCES
  );

  assert.deepEqual(visible.map((project) => project.fullName), ["demo/ready", "new/tool"]);
  assert.deepEqual(
    withFrameworks.map((project) => project.fullName),
    ["demo/ready", "new/tool", "framework/core"]
  );
  assert.equal(visible.some((project) => project.fullName === "low-stars/collecting"), false);
  assert.equal(getAiProjectSelectionLabel(projects[0]), "高 Stars");
  assert.equal(getAiProjectSelectionLabel(projects[2]), "7 天增长");
});

test("new and rising are independent views while hidden stages require an explicit opt-in", () => {
  const newlyListed = filterAiProjects(projects, { view: "new" }, DEFAULT_AI_PREFERENCES);
  const risingHidden = filterAiProjects(projects, { view: "rising" }, DEFAULT_AI_PREFERENCES);
  const risingAll = filterAiProjects(
    projects,
    { view: "rising", includeHiddenStages: true },
    DEFAULT_AI_PREFERENCES
  );

  assert.deepEqual(newlyListed.map((project) => project.fullName), ["new/tool"]);
  assert.deepEqual(risingHidden, []);
  assert.equal(risingAll[0].fullName, "framework/core");
});

test("project owner and capability follows all feed the followed view", () => {
  let preferences = toggleAiFollow(DEFAULT_AI_PREFERENCES, "project", "framework/core");
  preferences = toggleAiFollow(preferences, "owner", "new");
  preferences = toggleAiFollow(preferences, "capability", "programming");

  assert.equal(isProjectFollowed(projects[2], preferences), true);
  assert.equal(isProjectFollowed(projects[1], preferences), true);
  assert.equal(isProjectFollowed(projects[0], preferences), true);
  assert.deepEqual(
    filterAiProjects(projects, { view: "followed" }, preferences).map((project) => project.fullName),
    ["demo/ready", "new/tool", "framework/core"]
  );
});

test("negative feedback hides a project without changing global classification", () => {
  const preferences = recordProjectFeedback(DEFAULT_AI_PREFERENCES, "demo/ready", "not-relevant");
  const visible = filterAiProjects(projects, { view: "recommended" }, preferences);

  assert.deepEqual(visible.map((project) => project.fullName), ["new/tool"]);
  assert.equal(preferences.feedbackByProject["demo/ready"], "not-relevant");
});

test("legacy GitHub hashes map locally to the new filter model", () => {
  assert.deepEqual(parseAiDiscoveryHash("#github/skills"), {
    view: "recommended",
    useStages: ["integrate"],
    surfaces: ["skill"]
  });
  assert.equal(parseAiDiscoveryHash("#github/agent-frameworks").includeHiddenStages, true);
});

test("storage denial falls back in memory and notification permission only runs on explicit call", async () => {
  const deniedStorage = {
    getItem() { throw new Error("denied"); },
    setItem() { throw new Error("denied"); }
  };
  const preferences = loadAiPreferences(deniedStorage);
  assert.deepEqual(preferences, DEFAULT_AI_PREFERENCES);
  assert.equal(saveAiPreferences(preferences, deniedStorage), false);

  let permissionRequests = 0;
  class FakeNotification {
    static permission = "default";
    static async requestPermission() {
      permissionRequests += 1;
      return "granted";
    }
  }
  assert.equal(permissionRequests, 0);
  assert.equal(await requestAiNotificationPermission(FakeNotification), "granted");
  assert.equal(permissionRequests, 1);
});

test("V125 notification constructor failure leaves the whole batch retryable", () => {
  class FailingNotification {
    static permission = "granted";
    constructor() {
      throw new Error("notification service unavailable");
    }
  }
  const preferences = { ...DEFAULT_AI_PREFERENCES, systemNotifications: true };
  const signals = [
    { eventId: "signal-1", title: "First" },
    { eventId: "signal-2", title: "Second" },
    { eventId: "signal-3", title: "Third" }
  ];

  const deliveredIds = notifyAiSignals(signals, preferences, FailingNotification);
  const next = markAiSignalsSeen(preferences, deliveredIds);

  assert.deepEqual(deliveredIds, []);
  assert.deepEqual(next.seenSignalIds, []);
});

test("V155 one unseen batch creates one aggregate notification and is then deduped", () => {
  class FakeNotification {
    static permission = "granted";
    static calls = [];
    constructor(title, options) {
      FakeNotification.calls.push({ title, options });
    }
  }
  const preferences = { ...DEFAULT_AI_PREFERENCES, systemNotifications: true };
  const signals = [
    { eventId: "signal-1", title: "First", reason: "First reason" },
    { eventId: "signal-2", title: "Second", reason: "Second reason" },
    { eventId: "signal-3", title: "Third", reason: "Third reason" }
  ];

  const deliveredIds = notifyAiSignals(signals, preferences, FakeNotification);
  const next = markAiSignalsSeen(preferences, deliveredIds);
  const duplicateIds = notifyAiSignals(signals, next, FakeNotification);

  assert.deepEqual(deliveredIds, ["signal-1", "signal-2", "signal-3"]);
  assert.deepEqual(duplicateIds, []);
  assert.equal(FakeNotification.calls.length, 1);
  assert.equal(FakeNotification.calls[0].title, "3 条 GitHub 项目新提醒");
  assert.equal(FakeNotification.calls[0].options.tag, "ai-project-alert-summary");
});

test("V154 alert preview reports hidden count and expansion exposes every signal", () => {
  const signals = Array.from({ length: 18 }, (_, index) => ({ eventId: `signal-${index + 1}` }));

  const preview = buildAiSignalDisplay(signals, false);
  const expanded = buildAiSignalDisplay(signals, true);

  assert.equal(preview.totalCount, 18);
  assert.equal(preview.items.length, 4);
  assert.equal(preview.hiddenCount, 14);
  assert.equal(expanded.items.length, 18);
  assert.equal(expanded.hiddenCount, 0);
});

test("followed library stable releases are promoted ahead of general high signals", () => {
  const release = {
    eventId: "release-framework-v2",
    type: "release",
    projectKey: "framework/core",
    fullName: "framework/core",
    title: "framework/core 发布 v2.0.0",
    reason: "最近发布了稳定版本",
    occurredAt: "2026-07-28T08:00:00Z"
  };
  const general = {
    eventId: "general-signal",
    type: "momentum",
    projectKey: "demo/ready",
    title: "demo/ready 热度快速上升",
    occurredAt: "2026-07-28T09:00:00Z"
  };
  const preferences = toggleAiFollow(DEFAULT_AI_PREFERENCES, "project", "framework/core");

  const alerts = selectAiAlertSignals(projects, { high: [general], digest: [release, general] }, preferences);

  assert.deepEqual(alerts.map((signal) => signal.eventId), ["release-framework-v2", "general-signal"]);
  assert.equal(alerts[0].followedRelease, true);
});

test("owner or capability follows do not fan out release notifications", () => {
  const release = {
    eventId: "release-framework-v2",
    type: "release",
    projectKey: "framework/core",
    occurredAt: "2026-07-28T08:00:00Z"
  };
  let preferences = toggleAiFollow(DEFAULT_AI_PREFERENCES, "owner", "framework");
  preferences = toggleAiFollow(preferences, "capability", "automation");

  assert.deepEqual(selectAiAlertSignals(projects, { high: [], digest: [release] }, preferences), []);
});
