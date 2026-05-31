const { test, expect } = require("@playwright/test");

function uniqueName(prefix) {
  return `${prefix} ${Date.now().toString(36)}`;
}

function hasOpenReviewGate(detail) {
  return (detail.review_gates || []).some((gate) => gate.status === "open");
}

function openConflict(detail) {
  return (detail.conflicts || []).find((conflict) => conflict.status === "open");
}

async function fetchProjectDetail(request, projectId) {
  const response = await request.get(`/api/projects/${projectId}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function pollProjectDetail(request, projectId, predicate, label) {
  const deadline = Date.now() + 10_000;
  let detail = await fetchProjectDetail(request, projectId);
  while (Date.now() < deadline) {
    if (predicate(detail)) return detail;
    await new Promise((resolve) => setTimeout(resolve, 250));
    detail = await fetchProjectDetail(request, projectId);
  }
  throw new Error(`Timed out waiting for ${label}. Last project status=${detail.project.status}, build status=${detail.active_build_run?.status}`);
}

test("Mock mode completes a BuildRun with review, conflict resolution, and ZIP export", async ({ page, request }) => {
  const projectName = uniqueName("E2E Mock Flow");

  await page.goto("/");
  await expect(page).toHaveTitle(/AI Software Company MVP/);
  await expect(page.getByRole("heading", { name: "AI Software Company" })).toBeVisible();

  await page.locator("#providerMode").selectOption("mock");
  await page.locator("#forceConflict").setChecked(true);
  await page.locator("#reviewRequired").setChecked(true);
  await page.locator("#projectName").fill(projectName);
  await page.locator("#requirementText").fill(
    "Create a course scheduling MVP with teacher availability, classroom capacity checks, conflict detection, and a downloadable delivery package."
  );

  const createResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && response.url().endsWith("/api/projects") && response.status() === 200
  );
  await page.getByRole("button", { name: "创建 Project" }).click();
  const createdDetail = await (await createResponse).json();
  const projectId = createdDetail.project.id;

  await expect(page.locator(`[data-project-id="${projectId}"]`)).toBeVisible();

  const startResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && response.url().includes(`/api/projects/${projectId}/builds`) && response.status() === 200
  );
  await page.getByRole("button", { name: "Start BuildRun" }).click();
  let detail = await (await startResponse).json();

  if (hasOpenReviewGate(detail)) {
    await expect(page.getByRole("heading", { name: "ReviewGate open" })).toBeVisible();
    const approveResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && response.url().includes("/review/approve") && response.status() === 200
    );
    await page.getByRole("button", { name: "通过审核" }).click();
    detail = await (await approveResponse).json();
  }

  detail = await pollProjectDetail(
    request,
    projectId,
    (current) => ["conflict", "completed", "failed"].includes(current.project.status),
    "the build to reach conflict, completed, or failed"
  );
  expect(detail.project.status).not.toBe("failed");

  if (openConflict(detail)) {
    await expect(page.getByRole("heading", { name: "Conflict: FE/BE API mismatch" })).toBeVisible();
    const resolveResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && response.url().includes("/api/conflicts/") && response.url().endsWith("/resolve") && response.status() === 200
    );
    await page.locator('[data-conflict-decision="align_to_backend"]').click();
    detail = await (await resolveResponse).json();
  }

  detail = await pollProjectDetail(
    request,
    projectId,
    (current) => current.project.status === "completed" || current.active_build_run?.status === "completed",
    "the build to complete"
  );

  expect(detail.project.status).toBe("completed");
  expect(detail.active_build_run.status).toBe("completed");
  expect(detail.artifacts.map((artifact) => artifact.type)).toEqual(expect.arrayContaining(["pm", "api_contract", "frontend", "backend", "runtime", "qa"]));

  await expect(page.getByRole("heading", { name: "Ready for export" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download ZIP" })).toBeVisible();

  const exportResponse = await request.get(`/api/build-runs/${detail.active_build_run.id}/export`);
  expect(exportResponse.status()).toBe(200);
  expect(exportResponse.headers()["content-type"]).toContain("application/zip");
  expect((await exportResponse.body()).length).toBeGreaterThan(100);
});

test("Mock mode completes without conflict when force_api_conflict is disabled", async ({ request }) => {
  const projectResponse = await request.post("/api/projects", {
    data: {
      name: uniqueName("E2E No Conflict"),
      requirement: "Create a scheduling MVP with stable frontend and backend API contracts.",
      provider_mode: "mock",
      force_api_conflict: false,
      human_review_required: false
    }
  });
  expect(projectResponse.ok()).toBeTruthy();
  const project = await projectResponse.json();

  const buildResponse = await request.post(`/api/projects/${project.project.id}/builds`, {
    data: {
      provider_mode: "mock",
      force_api_conflict: false,
      human_review_required: false,
      context_policy: "fresh"
    }
  });
  expect(buildResponse.ok()).toBeTruthy();
  const detail = await buildResponse.json();

  expect(detail.project.status).toBe("completed");
  expect(detail.active_build_run.status).toBe("completed");
  expect((detail.conflicts || []).filter((conflict) => conflict.status === "open")).toEqual([]);
  expect(detail.agent_runs.filter((run) => run.role === "frontend")).toHaveLength(1);
  expect(detail.agent_runs.filter((run) => run.role === "backend")).toHaveLength(1);
});

test("force_pass records a forced conflict decision and proceeds to QA", async ({ request }) => {
  const projectResponse = await request.post("/api/projects", {
    data: {
      name: uniqueName("E2E Force Pass"),
      requirement: "Create a scheduling MVP and demonstrate forced conflict pass.",
      provider_mode: "mock",
      force_api_conflict: true,
      human_review_required: false
    }
  });
  expect(projectResponse.ok()).toBeTruthy();
  const project = await projectResponse.json();

  const buildResponse = await request.post(`/api/projects/${project.project.id}/builds`, {
    data: {
      provider_mode: "mock",
      force_api_conflict: true,
      human_review_required: false,
      context_policy: "fresh"
    }
  });
  expect(buildResponse.ok()).toBeTruthy();
  let detail = await buildResponse.json();
  const conflict = openConflict(detail);
  expect(conflict).toBeTruthy();

  const resolveResponse = await request.post(`/api/conflicts/${conflict.id}/resolve`, {
    data: { decision: "force_pass" }
  });
  expect(resolveResponse.ok()).toBeTruthy();
  detail = await resolveResponse.json();

  expect(detail.project.status).toBe("completed");
  expect(detail.conflicts[0].status).toBe("forced");
  expect(detail.conflicts[0].decision).toBe("force_pass");
  expect(detail.agent_runs.filter((run) => run.resolves_conflict_id === conflict.id)).toHaveLength(0);
  expect(detail.agent_runs.some((run) => run.role === "qa" && run.status === "completed")).toBeTruthy();
});

test("LLM mode without configuration shows an explicit blocker and does not fallback to Mock", async ({ page }) => {
  await page.goto("/");
  await page.locator("#providerMode").selectOption("llm");
  await expect(page.locator("#providerBlocker")).toContainText("LLM 配置阻塞");
  await page.locator("#projectName").fill(uniqueName("E2E LLM Blocked"));
  await page.getByRole("button", { name: "Start BuildRun" }).click();
  await expect(page.locator("#blockerModal")).toBeVisible();
  await expect(page.locator("#blockerMissing")).toContainText("LLM_API_KEY");
  await expect(page.locator("#blockerMessage")).toContainText("不会自动 fallback 到 Mock");
});

test("config exposes minimal platform-owned toolset boundary", async ({ request }) => {
  const response = await request.get("/api/config");
  expect(response.ok()).toBeTruthy();
  const config = await response.json();

  expect(config.toolset.mode).toBe("minimal_platform_owned");
  expect(config.toolset.llm_tool_calling).toBe(false);
  expect(config.toolset.implemented.map((tool) => tool.name)).toEqual([
    "read_context",
    "propose_files",
    "run_harness",
    "run_conflict_scenario",
    "run_contract_check",
    "run_runtime_harness",
    "export_artifacts",
  ]);
  expect(config.toolset.extension_points).toEqual(expect.arrayContaining([
    "sandboxed_shell",
    "browser_automation",
    "test_runner",
    "worker_queue",
  ]));
});

test("artifact evidence exposes harness reports and manifest files", async ({ request }) => {
  const projectResponse = await request.post("/api/projects", {
    data: {
      name: uniqueName("E2E Harness Evidence"),
      requirement: "Create a scheduling MVP and expose harness evidence.",
      provider_mode: "mock",
      force_api_conflict: false,
      human_review_required: false
    }
  });
  const project = await projectResponse.json();
  const buildResponse = await request.post(`/api/projects/${project.project.id}/builds`, {
    data: { provider_mode: "mock", force_api_conflict: false, human_review_required: false }
  });
  const detail = await buildResponse.json();
  const frontend = detail.artifacts.find((artifact) => artifact.type === "frontend");
  expect(frontend.files).toContain("_harness-report.json");
  expect(frontend.files).toContain("_manifest/api_usages.json");

  const reportResponse = await request.get(`/api/artifacts/${frontend.id}/file?path=${encodeURIComponent("_harness-report.json")}`);
  expect(reportResponse.ok()).toBeTruthy();
  const report = await reportResponse.json();
  expect(JSON.parse(report.content).status).toMatch(/valid|repaired/);
});

test("force_api_conflict is injected by platform harness, not provider output", async ({ request }) => {
  const projectResponse = await request.post("/api/projects", {
    data: {
      name: uniqueName("E2E Deterministic Conflict"),
      requirement: "Create a scheduling MVP and let the platform inject the contract conflict.",
      provider_mode: "mock",
      force_api_conflict: true,
      human_review_required: false
    }
  });
  const project = await projectResponse.json();
  const buildResponse = await request.post(`/api/projects/${project.project.id}/builds`, {
    data: { provider_mode: "mock", force_api_conflict: true, human_review_required: false }
  });
  const detail = await buildResponse.json();
  const conflict = openConflict(detail);
  expect(conflict).toBeTruthy();

  const frontendArtifacts = detail.artifacts.filter((artifact) => artifact.type === "frontend");
  expect(frontendArtifacts.length).toBeGreaterThanOrEqual(2);
  const injectedFrontend = frontendArtifacts[frontendArtifacts.length - 1];
  const scenarioRun = detail.agent_runs.find((run) => run.id === injectedFrontend.agent_run_id);
  expect(scenarioRun.trigger_reason).toBe("scenario_conflict_injection");
  expect(scenarioRun.provider_mode).toBe("platform");

  const reportResponse = await request.get(`/api/artifacts/${injectedFrontend.id}/file?path=${encodeURIComponent("_harness-report.json")}`);
  expect(reportResponse.ok()).toBeTruthy();
  const report = JSON.parse((await reportResponse.json()).content);
  expect(report.repairs.some((repair) => repair.id === "scenario_api_conflict_injected")).toBeTruthy();
  expect(conflict.mismatches.some((item) => item.kind === "frontend_usage_missing_backend_route")).toBeTruthy();
});
