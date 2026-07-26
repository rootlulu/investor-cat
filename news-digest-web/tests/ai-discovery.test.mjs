import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_AI_PREFERENCES,
  filterAiProjects,
  isProjectFollowed,
  loadAiPreferences,
  markAiSignalsSeen,
  notifyAiSignals,
  parseAiDiscoveryHash,
  recordProjectFeedback,
  requestAiNotificationPermission,
  saveAiPreferences,
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
    discoveryScore: 99
  }
];

test("recommended view defaults to usable tools and does not let stars dominate", () => {
  const visible = filterAiProjects(projects, { view: "recommended" }, DEFAULT_AI_PREFERENCES);
  const withFrameworks = filterAiProjects(
    projects,
    { view: "recommended", useStages: ["ready", "integrate", "build"], includeHiddenStages: true },
    DEFAULT_AI_PREFERENCES
  );

  assert.deepEqual(visible.map((project) => project.fullName), ["demo/ready", "new/tool"]);
  assert.deepEqual(withFrameworks.map((project) => project.fullName), ["framework/core", "demo/ready", "new/tool"]);
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
    ["framework/core", "demo/ready", "new/tool"]
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

test("V125 notification failure only marks delivered signals as seen", () => {
  class FailingNotification {
    static permission = "granted";
    constructor(_title, options) {
      if (options.tag === "signal-2") throw new Error("notification service unavailable");
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

  assert.deepEqual(deliveredIds, ["signal-1"]);
  assert.deepEqual(next.seenSignalIds, ["signal-1"]);
});
