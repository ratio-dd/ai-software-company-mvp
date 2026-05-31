const { test, expect } = require("@playwright/test");

const VIEWPORTS = [
  { name: "desktop", width: 1512, height: 900 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 }
];

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

async function createStartedBuildRun(page, viewportName) {
  const projectName = uniqueName(`E2E Layout ${viewportName}`);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AI Software Company" })).toBeVisible();

  await page.locator("#providerMode").selectOption("mock");
  await page.locator("#forceConflict").setChecked(true);
  await page.locator("#reviewRequired").setChecked(true);
  await page.locator("#projectName").fill(projectName);
  await page.locator("#requirementText").fill(
    "Build a scheduling command center with project status, pipeline evidence, conflict review, event logs, and export readiness."
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
  const startedDetail = await (await startResponse).json();

  return { projectId, projectName, detail: startedDetail };
}

async function completeBuildRun(page, request, projectId, detail) {
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

  return pollProjectDetail(
    request,
    projectId,
    (current) => current.project.status === "completed" || current.active_build_run?.status === "completed",
    "the build to complete"
  );
}

async function assertNoHorizontalOverflow(page) {
  const globalOverflow = await page.evaluate(() => ({
    bodyScrollWidth: document.body.scrollWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    documentClientWidth: document.documentElement.clientWidth,
    viewportWidth: window.innerWidth
  }));

  expect(globalOverflow.bodyScrollWidth, JSON.stringify(globalOverflow)).toBeLessThanOrEqual(globalOverflow.documentClientWidth + 1);
  expect(globalOverflow.documentScrollWidth, JSON.stringify(globalOverflow)).toBeLessThanOrEqual(globalOverflow.documentClientWidth + 1);

  const overflowing = await page.locator([
    "#workspace",
    ".topbar",
    ".status-strip",
    ".panel",
    ".panel-body",
    ".pipeline",
    ".pipeline-flow",
    ".flow-node",
    ".flow-branch",
    ".node-detail",
    ".node-detail-grid",
    ".state-card",
    ".mismatch-table",
    ".artifact-layout",
    ".file-tree",
    ".viewer",
    "#viewerContent",
    ".viewer-content",
    ".markdown-view",
    ".logs",
    ".log-item"
  ].join(", ")).evaluateAll((elements) => {
    function describe(element) {
      if (element.id) return `#${element.id}`;
      const classes = typeof element.className === "string" ? element.className.trim().split(/\s+/).filter(Boolean).slice(0, 3).join(".") : "";
      return classes ? `${element.tagName.toLowerCase()}.${classes}` : element.tagName.toLowerCase();
    }

    return elements
      .filter((element) => {
        const style = window.getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden" || element.getClientRects().length === 0) return false;
        return Math.ceil(element.scrollWidth) > Math.ceil(element.clientWidth) + 1;
      })
      .map((element) => ({
        selector: describe(element),
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
        text: (element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120)
      }));
  });

  expect(overflowing, JSON.stringify(overflowing, null, 2)).toEqual([]);
}

for (const viewport of VIEWPORTS) {
  test(`no horizontal overflow after a completed Mock BuildRun on ${viewport.name}`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });

    const { projectId, projectName, detail } = await createStartedBuildRun(page, viewport.name);
    const completedDetail = await completeBuildRun(page, request, projectId, detail);

    expect(completedDetail.project.status).toBe("completed");
    expect(completedDetail.active_build_run.status).toBe("completed");

    await page.reload();
    await page.locator(`[data-project-id="${projectId}"]`).click();
    await expect(page.locator("#statusStrip")).toContainText(projectName);
    await expect(page.getByRole("heading", { name: "Ready for export" })).toBeVisible();
    await expect(page.locator(".flow-node")).toHaveCount(6);

    await page.locator('[data-node="frontend"]').click();
    await expect(page.locator(".node-detail")).toBeVisible();
    await expect(page.locator('[data-view-artifact-id]')).toBeVisible();
    await page.locator('[data-view-artifact-id]').click();
    await expect(page.locator(".evidence-panel")).toBeVisible();
    await expect(page.locator("#artifactTabs")).not.toContainText("No artifacts yet");
    await expect(page.locator("#viewerContent")).not.toHaveText("Loading...");
    await expect(page.locator("#viewerContent.markdown-view h1")).toBeVisible();

    await assertNoHorizontalOverflow(page);
  });
}
