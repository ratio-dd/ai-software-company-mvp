const state = {
  projects: [],
  selectedProjectId: null,
  detail: null,
  config: null,
  selectedNode: "contract",
  selectedArtifactId: null,
  selectedFile: null,
  collapsed: { brief: false, evidence: true, logs: true }
};

const roleLabels = {
  pm: "PM",
  architect: "Architect",
  frontend: "Frontend",
  backend: "Backend",
  qa: "QA",
  api_contract: "Architect"
};

const nodeDesigns = {
  pm: {
    title: "PM Agent",
    responsibility: "把 Human CTO 的自然语言需求转成 PRD，定义目标用户、核心功能、用户故事和验收标准。",
    input: "Project.name + Project.requirement",
    output: "prd.md + feature_manifest",
    gate: "PM Harness 检查 prd.md、必需章节和 feature list。"
  },
  architect: {
    title: "Architect Agent",
    responsibility: "消费 PRD，产出系统架构、模块边界、数据模型和 API contract。",
    input: "prd.md",
    output: "architecture.md + api-contract.json",
    gate: "Architect Harness 校验 architecture.md 与 api-contract.json schema。"
  },
  frontend: {
    title: "Frontend Agent",
    responsibility: "基于 API contract 生成可独立运行的前端产物，并暴露实际 API usages。",
    input: "prd.md + architecture.md + api-contract.json",
    output: "frontend/ + manifest/api-usages.json + run.json",
    gate: "Frontend Harness 检查启动入口，并从 fetch 调用提取 API usage manifest。"
  },
  backend: {
    title: "Backend Agent",
    responsibility: "基于 API contract 生成可独立运行的后端产物，并暴露实际 routes。",
    input: "prd.md + architecture.md + api-contract.json",
    output: "backend/ + manifest/routes.json + run.json",
    gate: "Backend Harness 检查启动入口，并从 route 定义提取 route manifest。"
  },
  contract: {
    title: "ContractChecker",
    responsibility: "比较 Frontend API usages 和 Backend routes。v0.1 只把 Frontend 调用了但 Backend 没有的 API 记为 Conflict。",
    input: "frontend/manifest/api-usages.json + backend/manifest/routes.json",
    output: "Conflict(open/resolved) 或进入 QA",
    gate: "Conflict 是业务状态，不是 failed；必须等待 Human CTO 决策。"
  },
  qa: {
    title: "QA Agent",
    responsibility: "在冲突解决后生成 QA 报告，覆盖主流程、API 契约、冲突处理和风险结论。",
    input: "latest valid/repaired artifacts + Conflict decision history",
    output: "qa_report.md",
    gate: "QA Harness 检查测试范围、测试用例、API 契约验证、冲突处理验证和风险结论。"
  }
};

const panelMeta = {
  brief: { label: "Brief", icon: "" },
  evidence: { label: "Evidence", icon: "right" },
  logs: { label: "Logs", icon: "bottom" }
};

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try { message = JSON.parse(text).error || text; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

async function loadProjects() {
  if (!state.config) {
    state.config = await api("/api/config");
  }
  const result = await api("/api/projects");
  state.projects = result.projects || [];
  if (!state.selectedProjectId && state.projects.length) {
    state.selectedProjectId = state.projects[0].id;
  }
  if (state.selectedProjectId) {
    await loadDetail(state.selectedProjectId);
  } else {
    state.detail = null;
    render();
  }
}

async function loadDetail(projectId) {
  state.detail = await api(`/api/projects/${projectId}`);
  state.selectedProjectId = projectId;
  pickDefaultArtifact();
  render();
}

function pickDefaultArtifact() {
  const artifacts = state.detail?.artifacts || [];
  if (!artifacts.length) {
    state.selectedArtifactId = null;
    state.selectedFile = null;
    return;
  }
  if (!artifacts.some((artifact) => artifact.id === state.selectedArtifactId)) {
    const preferred = artifacts.find((artifact) => artifact.type === "frontend") || artifacts[artifacts.length - 1];
    state.selectedArtifactId = preferred.id;
    state.selectedFile = preferred.files?.[0] || null;
  }
}

function statusClass(status) {
  return `status-${status || "draft"}`;
}

function render() {
  renderStatusStrip();
  renderProviderBlocker();
  renderWorkspaceClass();
  renderProjects();
  renderPipeline();
  renderArtifacts();
  renderDecision();
  renderLogs();
  renderDock();
}

function renderStatusStrip() {
  const project = state.detail?.project;
  const build = state.detail?.active_build_run;
  const nextAction = nextCtoAction();
  const provider = build?.provider_mode_actual || qs("#providerMode").value;
  const llmValue = provider === "llm"
    ? (state.config?.llm?.configured ? "configured" : "missing")
    : "not required";
  const items = [
    { label: "Project", value: project?.name || "none", tone: "default" },
    { label: "Run state", value: project?.status || "draft", tone: project?.status || "draft" },
    { label: "Next CTO action", value: nextAction, tone: nextAction.includes("Conflict") || nextAction.includes("Review") ? "attention" : "default" },
    { label: "Runtime boundary", value: "logical agents / in-process", tone: "quiet" },
    { label: "Toolset", value: state.config?.toolset?.mode || "minimal", tone: "quiet" },
    { label: "Provider", value: provider, tone: "quiet" },
    { label: "LLM config", value: llmValue, tone: provider === "llm" && !state.config?.llm?.configured ? "attention" : "quiet" }
  ];
  qs("#statusStrip").innerHTML = items.map((item) => `
    <article class="run-chip ${item.tone === "attention" ? "attention" : ""}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
    </article>
  `).join("");
  qs("#buildStatus").textContent = project?.status || "draft";
  qs("#buildStatus").className = `status-pill ${statusClass(project?.status || "draft")}`;
}

function nextCtoAction() {
  const project = state.detail?.project;
  if (!project) return "Create project";
  if (project.status === "awaiting_review") return "Review architecture";
  if (project.status === "conflict") return "Resolve Conflict";
  if (project.status === "completed") return "Download ZIP";
  if (project.status === "failed") return "Inspect blocker";
  if (project.status === "running") return "Monitor run";
  return "Start BuildRun";
}

function llmMissingText() {
  const missing = state.config?.llm?.missing || [];
  return missing.length ? missing.join(", ") : "LLM_API_KEY, LLM_BASE_URL, LLM_MODEL";
}

function renderProviderBlocker() {
  const blocker = qs("#providerBlocker");
  if (!blocker) return;
  const isLlm = qs("#providerMode").value === "llm";
  const configured = Boolean(state.config?.llm?.configured);
  blocker.hidden = !isLlm || configured;
  if (!blocker.hidden) {
    blocker.innerHTML = `
      <strong>LLM 配置阻塞</strong>
      <span>当前选择了 LLM，但缺少：${escapeHtml(llmMissingText())}。</span>
      <span>不会 fallback 到 Mock。请配置环境变量后重启，或切回 Mock。</span>
    `;
  }
}

function renderWorkspaceClass() {
  const hidden = Object.entries(state.collapsed).filter(([, value]) => value).map(([key]) => `hide-${key}`);
  qs("#workspace").className = `workspace ${hidden.join(" ")}`.trim();
  Object.keys(panelMeta).forEach((key) => {
    qs(`[data-panel="${key}"]`)?.classList.toggle("hidden-panel", state.collapsed[key]);
  });
}

function renderProjects() {
  qs("#projectList").innerHTML = state.projects.map((project) => `
    <button class="project-row ${project.id === state.selectedProjectId ? "active" : ""}" data-project-id="${project.id}">
      <div class="project-title">
        <span>${escapeHtml(project.name)}</span>
        <span class="status-pill ${statusClass(project.status)}">${escapeHtml(project.status)}</span>
      </div>
      <div class="project-desc">active: ${escapeHtml(project.active_build_run_id || "none")}</div>
      <div class="project-desc">stage: ${escapeHtml(project.active_stage || "not started")}</div>
    </button>
  `).join("");
}

function latestAgentByRole(role) {
  const runs = state.detail?.agent_runs || [];
  return [...runs].reverse().find((run) => run.role === role);
}

function latestArtifactByType(type) {
  const artifacts = state.detail?.artifacts || [];
  return [...artifacts].reverse().find((artifact) => artifact.type === type);
}

function renderPipeline() {
  const projectStatus = state.detail?.project?.status || "draft";
  const contractStatus = projectStatus === "conflict" ? "blocked" : projectStatus === "completed" ? "completed" : "pending";
  const card = (role) => {
    const run = latestAgentByRole(role);
    const status = run?.status || "pending";
    const artifactType = role === "architect" ? "api_contract" : role;
    const artifact = latestArtifactByType(artifactType);
    return `
      <button class="flow-node ${status} ${state.selectedNode === role ? "selected" : ""}" data-node="${role}" data-role="${role}" data-artifact-id="${artifact?.id || ""}">
        <span class="node-marker"></span>
        <span class="node-main">
          <strong>${roleLabels[role] || role}</strong>
          <small>${artifact?.type || "waiting"} · attempt ${run?.attempt_no || "-"}</small>
        </span>
        <span class="status-pill ${statusClass(status)}">${status}</span>
      </button>
    `;
  };
  qs("#pipeline").innerHTML = `
    ${renderCommandSummary()}
    <div class="pipeline-command">
      <div class="timeline-shell">
        <div class="timeline-label">BuildRun timeline</div>
        <div class="pipeline-flow">
          ${card("pm")}
          ${card("architect")}
          <div class="flow-branch">
            <div class="branch-label">parallel implementation</div>
            <div class="branch-nodes">
              ${card("frontend")}
              ${card("backend")}
            </div>
          </div>
          <button class="flow-node ${contractStatus} ${state.selectedNode === "contract" ? "selected" : ""}" data-node="contract">
            <span class="node-marker"></span>
            <span class="node-main">
              <strong>Contract Check</strong>
              <small>FE usages vs BE routes · ${openConflict() ? "1 open conflict" : "no open conflict"}</small>
            </span>
            <span class="status-pill ${statusClass(contractStatus)}">${contractStatus}</span>
          </button>
          ${card("qa")}
        </div>
      </div>
      ${renderNodeDetail()}
    </div>
  `;
}

function renderCommandSummary() {
  const project = state.detail?.project;
  const build = state.detail?.active_build_run;
  const conflict = openConflict();
  const reviewGate = openReviewGate();
  const cards = [
    {
      label: "Current state",
      value: project?.status || "draft",
      note: build?.stage ? `stage: ${build.stage}` : "no active BuildRun"
    },
    {
      label: "CTO decision",
      value: reviewGate ? "Review gate" : conflict ? "API conflict" : project?.status === "completed" ? "Export ready" : "No gate",
      note: reviewGate ? "approve architecture" : conflict ? `${conflict.mismatches.length} mismatch(es)` : "no open decision"
    },
    {
      label: "Agent runtime",
      value: "Logical agents",
      note: "in-process attempts; artifact isolation"
    },
    {
      label: "Tool boundary",
      value: "Minimal toolset",
      note: "platform-owned harness/check/export"
    }
  ];
  return `
    <section class="command-summary" aria-label="BuildRun summary">
      ${cards.map((item) => `
        <article>
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
          <small>${escapeHtml(item.note)}</small>
        </article>
      `).join("")}
    </section>
  `;
}

function renderNodeDetail() {
  const node = state.selectedNode || "contract";
  const design = nodeDesigns[node] || nodeDesigns.contract;
  const run = latestAgentByRole(node);
  const artifactType = node === "architect" ? "api_contract" : node;
  const artifact = latestArtifactByType(artifactType);
  const conflict = openConflict();
  const nodeStatus = node === "contract"
    ? (conflict ? "blocked" : (state.detail?.project?.status === "completed" ? "completed" : "pending"))
    : (run?.status || "pending");
  const extra = node === "contract"
    ? `${conflict ? `${conflict.mismatches.length} mismatch(es), waiting for CTO decision.` : "No open conflict."}`
    : `${run ? `AgentRun ${run.id}, status=${run.status}, trigger=${run.trigger_reason}.` : "AgentRun not created yet."}`;
  return `
    <section class="node-detail">
      <div class="node-detail-head">
        <h3>${escapeHtml(design.title)}</h3>
        <span class="status-pill ${statusClass(nodeStatus)}">${escapeHtml(nodeStatus)}</span>
      </div>
      <div class="node-detail-grid">
        <div>
          <strong>职责</strong>
          <p>${escapeHtml(design.responsibility)}</p>
        </div>
        <div>
          <strong>输入</strong>
          <p>${escapeHtml(design.input)}</p>
        </div>
        <div>
          <strong>输出</strong>
          <p>${escapeHtml(design.output)}</p>
        </div>
        <div>
          <strong>Gate</strong>
          <p>${escapeHtml(design.gate)}</p>
        </div>
      </div>
      <div class="runtime-boundary">
        <div>
          <strong>Runtime</strong>
          <span>v0.1 uses in-process logical AgentRuns; FE/BE run in parallel threads.</span>
        </div>
        <div>
          <strong>Isolation</strong>
          <span>DB state + artifact folder per AgentRun. Process/container sandbox is an extension point.</span>
        </div>
        <div>
          <strong>Tools</strong>
          <span>Minimal platform-owned tools: read context, propose files, harness, contract check, export. No shell/browser/test-runner tools in v0.1.</span>
        </div>
      </div>
      <div class="node-footer">
        <p class="node-evidence">${escapeHtml(extra)}${artifact ? ` Latest artifact: ${artifact.type} v${artifact.version}.` : ""}</p>
        ${artifact ? `<button type="button" data-view-artifact-id="${artifact.id}">查看产物</button>` : ""}
      </div>
    </section>
  `;
}

function renderArtifacts() {
  const artifacts = state.detail?.artifacts || [];
  qs("#artifactTabs").innerHTML = artifacts.map((artifact) => `
    <button class="${artifact.id === state.selectedArtifactId ? "active" : ""}" data-artifact-id="${artifact.id}">
      ${escapeHtml(roleLabels[artifact.type] || artifact.type)} v${artifact.version}
    </button>
  `).join("") || "<span class=\"tag\">No artifacts yet</span>";

  const artifact = artifacts.find((item) => item.id === state.selectedArtifactId);
  if (!artifact) {
    qs("#fileTree").innerHTML = "";
    qs("#viewerTitle").textContent = "No artifact selected";
    renderViewerContent("", "Create a project and start a BuildRun.");
    return;
  }
  if (!state.selectedFile || !artifact.files.includes(state.selectedFile)) {
    state.selectedFile = artifact.files[0];
  }
  qs("#fileTree").innerHTML = artifact.files.map((file) => `
    <button class="${file === state.selectedFile ? "active" : ""}" data-file="${escapeAttr(file)}">${escapeHtml(file)}</button>
  `).join("");
  loadFile(artifact.id, state.selectedFile);
}

async function loadFile(artifactId, path) {
  if (!artifactId || !path) return;
  qs("#viewerTitle").textContent = path;
  renderViewerContent("", "Loading...");
  try {
    const result = await api(`/api/artifacts/${artifactId}/file?path=${encodeURIComponent(path)}`);
    if (state.selectedArtifactId === artifactId && state.selectedFile === path) {
      renderViewerContent(path, result.content);
    }
  } catch (error) {
    renderViewerContent("", error.message);
  }
}

function renderViewerContent(path, content) {
  const viewer = qs("#viewerContent");
  const isMarkdown = path.endsWith(".md");
  viewer.className = `viewer-content ${isMarkdown ? "markdown-view" : "code-view"}`;
  if (isMarkdown) {
    viewer.innerHTML = renderMarkdown(content);
    return;
  }
  const display = path.endsWith(".json") ? prettyJson(content) : content;
  viewer.innerHTML = highlightCode(display, path);
}

function prettyJson(content) {
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch (_) {
    return content;
  }
}

function renderMarkdown(content) {
  const lines = content.split(/\r?\n/);
  let html = "";
  let inList = false;
  let inCode = false;
  let code = [];
  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };
  const closeCode = () => {
    if (inCode) {
      html += `<pre>${escapeHtml(code.join("\n"))}</pre>`;
      code = [];
      inCode = false;
    }
  };
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (inCode) closeCode();
      else {
        closeList();
        inCode = true;
        code = [];
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    if (line.startsWith("# ")) {
      closeList();
      html += `<h1>${inlineMarkdown(line.slice(2))}</h1>`;
    } else if (line.startsWith("## ")) {
      closeList();
      html += `<h2>${inlineMarkdown(line.slice(3))}</h2>`;
    } else if (line.startsWith("### ")) {
      closeList();
      html += `<h3>${inlineMarkdown(line.slice(4))}</h3>`;
    } else if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inlineMarkdown(line.replace(/^\s*[-*]\s+/, ""))}</li>`;
    } else if (line.trim()) {
      closeList();
      html += `<p>${inlineMarkdown(line)}</p>`;
    } else {
      closeList();
    }
  }
  closeCode();
  closeList();
  return html || "<p>Empty file.</p>";
}

function inlineMarkdown(value) {
  return escapeHtml(value).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function highlightCode(content, path) {
  return content.split(/\r?\n/).map((line) => {
    const escaped = escapeHtml(line);
    if (/^\s*(\/\/|#)/.test(line)) {
      return `<span class="tok-comment">${escaped}</span>`;
    }
    return escaped.replace(/(&quot;[^&]*?&quot;|'[^']*?')/g, '<span class="tok-string">$1</span>');
  }).join("\n");
}

function openConflict() {
  return (state.detail?.conflicts || []).find((conflict) => conflict.status === "open");
}

function openReviewGate() {
  return (state.detail?.review_gates || []).find((gate) => gate.status === "open");
}

function renderDecision() {
  const build = state.detail?.active_build_run;
  const project = state.detail?.project;
  const conflict = openConflict();
  const reviewGate = openReviewGate();
  if (!project) {
    qs("#decisionArea").innerHTML = `<section class="state-card"><h3>No project</h3><p>Create a project to start.</p></section>`;
    return;
  }
  if (project.status === "failed") {
    const isProviderConfig = build?.failure_category === "provider_config";
    qs("#decisionArea").innerHTML = `
      <section class="state-card failed">
        <h3>${isProviderConfig ? "LLM 配置阻塞" : "BuildRun failed"}</h3>
        <p>${escapeHtml(build?.failure_category || "unknown")}: ${escapeHtml(build?.failed_reason || "")}</p>
        <div class="action-row">
          ${isProviderConfig ? '<button class="primary" id="switchMockBtnInline">切回 Mock 模式</button>' : ''}
          <button type="button" data-restore="logs">查看 Logs</button>
          <button id="rerunBtn">创建新 BuildRun</button>
        </div>
      </section>
    `;
    return;
  }
  if (reviewGate) {
    qs("#decisionArea").innerHTML = `
      <section class="state-card">
        <h3>ReviewGate open</h3>
        <p>Architect artifact is ready. Human CTO must approve before Frontend/Backend runs.</p>
        <div class="action-row"><button class="primary" id="approveReviewBtn">通过审核</button></div>
        <div class="action-row"><button type="button" data-restore="evidence">查看架构产物</button><button type="button" data-restore="logs">查看 Logs</button></div>
      </section>
    `;
    return;
  }
  if (conflict) {
    const side = (value, fallback = "-") => {
      if (!value) return fallback;
      if (typeof value === "string") return value;
      if (Array.isArray(value)) {
        return value.map((item) => {
          const route = `${item.method || "GET"} ${item.path || item.frontend_path || item.backend_path || ""}`.trim();
          const keys = item.request_keys?.length ? ` keys: ${item.request_keys.join(", ")}` : "";
          return `${route}${keys}`;
        }).join(", ") || fallback;
      }
      const route = `${value.method || "GET"} ${value.path || value.frontend_path || value.backend_path || ""}`.trim();
      const keys = value.request_keys?.length ? ` keys: ${value.request_keys.join(", ")}` : "";
      return `${route}${keys}` || fallback;
    };
    const rows = conflict.mismatches.map((item) => `
      <div class="mismatch-row issue">
        <div class="mismatch-cell">${escapeHtml(item.kind || item.method)}${item.reason ? `<br><small>${escapeHtml(item.reason)}</small>` : ""}</div>
        <div class="mismatch-cell">${escapeHtml(side(item.frontend || item.frontend_path))}</div>
        <div class="mismatch-cell">${escapeHtml(side(item.backend || item.backend_path || item.backend_candidates))}</div>
      </div>
    `).join("");
    qs("#decisionArea").innerHTML = `
      <section class="state-card conflict-card">
        <h3>Conflict: FE/BE API mismatch</h3>
        <p>Conflict 是业务状态，不是 failed。它引用产生冲突的 Frontend/Backend AgentRun attempt。</p>
        <div class="mismatch-table">
          <div class="mismatch-row">
            <div class="mismatch-cell"><strong>Method</strong></div>
            <div class="mismatch-cell"><strong>Frontend usage</strong></div>
            <div class="mismatch-cell"><strong>Backend route</strong></div>
          </div>
          ${rows}
        </div>
        <div class="action-row">
          <button class="primary" data-conflict-decision="align_to_frontend">以前端为准</button>
          <button data-conflict-decision="align_to_backend">以后端为准</button>
          <button data-conflict-decision="force_pass">强制通过</button>
          <button type="button" data-restore="evidence">查看 Evidence</button>
        </div>
      </section>
    `;
    return;
  }
  if (project.status === "completed") {
    qs("#decisionArea").innerHTML = `
      <section class="state-card">
        <h3>Ready for export</h3>
        <p>ZIP preflight passed. Download package includes prd.md, architecture.md, frontend/, backend/, qa_report.md.</p>
        <div class="action-row">
          <a class="doc-link primary" href="/api/build-runs/${build.id}/export">Download ZIP</a>
          <button type="button" data-restore="evidence">查看 Evidence</button>
        </div>
      </section>
    `;
    return;
  }
  qs("#decisionArea").innerHTML = `
    <section class="state-card">
      <h3>${escapeHtml(project.status)}</h3>
      <p>Start a BuildRun, approve review gates, or resolve conflicts when they appear.</p>
    </section>
  `;
}

function renderLogs() {
  const logs = state.detail?.logs || [];
  qs("#logs").innerHTML = logs.map((log) => `
    <section class="log-item">
      <div class="log-time">${escapeHtml((log.created_at || "").replace("T", " ").slice(11, 19))}</div>
      <div>
        <div class="log-title">${escapeHtml(log.event_type)}</div>
        <div class="log-msg">${escapeHtml(log.message)}</div>
      </div>
    </section>
  `).join("") || "<span class=\"tag\">No logs yet</span>";
}

function renderDock() {
  const hidden = Object.entries(state.collapsed).filter(([, value]) => value).map(([key]) => key);
  const dock = qs("#panelDock");
  dock.classList.toggle("has-items", hidden.length > 0);
  dock.innerHTML = hidden.map((key) => `
    <button class="dock-button" data-restore="${key}">
      <span class="side-panel-icon ${panelMeta[key].icon}"></span>
      <small>${panelMeta[key].label}</small>
    </button>
  `).join("");
}

function currentProjectId() {
  return state.selectedProjectId;
}

async function createProject() {
  const payload = formPayload();
  const detail = await api("/api/projects", { method: "POST", body: JSON.stringify(payload) });
  state.selectedProjectId = detail.project.id;
  await loadProjects();
  toast("Project created.");
}

async function startBuild() {
  if (formPayload().provider_mode === "llm" && !state.config?.llm?.configured) {
    showLlmBlocker();
    return;
  }
  if (!currentProjectId()) {
    await createProject();
  }
  const detail = await api(`/api/projects/${currentProjectId()}/builds`, { method: "POST", body: JSON.stringify(formPayload()) });
  state.detail = detail;
  await loadProjects();
  toast("BuildRun started.");
}

function switchToMock() {
  qs("#providerMode").value = "mock";
  render();
  hideLlmBlocker();
  toast("已切回 Mock 模式。");
}

function showLlmBlocker() {
  qs("#blockerMessage").textContent = "当前选择了 LLM 模式，但运行环境没有完整的 OpenAI-compatible 配置。这个阻塞不会自动 fallback 到 Mock。";
  qs("#blockerMissing").textContent = `Missing: ${llmMissingText()}\nExpected env:\nLLM_API_KEY=...\nLLM_BASE_URL=https://...\nLLM_MODEL=...`;
  qs("#blockerModal").hidden = false;
  toast("LLM 配置阻塞：缺少 " + llmMissingText());
}

function hideLlmBlocker() {
  qs("#blockerModal").hidden = true;
}

function formPayload() {
  return {
    name: qs("#projectName").value,
    requirement: qs("#requirementText").value,
    provider_mode: qs("#providerMode").value,
    context_policy: qs("#contextPolicy").value,
    force_api_conflict: qs("#forceConflict").checked,
    human_review_required: qs("#reviewRequired").checked
  };
}

async function approveReview() {
  const build = state.detail.active_build_run;
  state.detail = await api(`/api/build-runs/${build.id}/review/approve`, { method: "POST", body: "{}" });
  await loadProjects();
  toast("Review approved.");
}

async function resolveConflict(decision) {
  const conflict = openConflict();
  state.detail = await api(`/api/conflicts/${conflict.id}/resolve`, { method: "POST", body: JSON.stringify({ decision }) });
  await loadProjects();
  toast(`Conflict resolved: ${decision}`);
}

function toast(message) {
  const el = qs("#toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(window.__toast);
  window.__toast = setTimeout(() => el.classList.remove("show"), 2200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

document.addEventListener("click", async (event) => {
  try {
    const project = event.target.closest("[data-project-id]");
    if (project) {
      await loadDetail(project.dataset.projectId);
      return;
    }
    const node = event.target.closest("[data-node]");
    if (node) {
      state.selectedNode = node.dataset.node;
      if (!node.dataset.artifactId) {
        render();
        return;
      }
    }

    const artifact = event.target.closest("[data-artifact-id]");
    if (artifact?.dataset.artifactId) {
      state.selectedArtifactId = artifact.dataset.artifactId;
      const selected = state.detail.artifacts.find((item) => item.id === state.selectedArtifactId);
      state.selectedFile = selected?.files?.[0] || null;
      render();
      return;
    }
    const viewArtifact = event.target.closest("[data-view-artifact-id]");
    if (viewArtifact) {
      state.selectedArtifactId = viewArtifact.dataset.viewArtifactId;
      const selected = state.detail.artifacts.find((item) => item.id === state.selectedArtifactId);
      state.selectedFile = selected?.files?.[0] || null;
      state.collapsed.evidence = false;
      render();
      return;
    }
    const role = event.target.closest("[data-role]");
    if (role?.dataset.artifactId) {
      state.selectedNode = role.dataset.role;
      state.selectedArtifactId = role.dataset.artifactId;
      const selected = state.detail.artifacts.find((item) => item.id === state.selectedArtifactId);
      state.selectedFile = selected?.files?.[0] || null;
      render();
      return;
    }
    const file = event.target.closest("[data-file]");
    if (file) {
      state.selectedFile = file.dataset.file;
      renderArtifacts();
      return;
    }
    const collapse = event.target.closest("[data-collapse]");
    if (collapse) {
      state.collapsed[collapse.dataset.collapse] = true;
      render();
      return;
    }
    const restore = event.target.closest("[data-restore]");
    if (restore) {
      state.collapsed[restore.dataset.restore] = false;
      render();
      return;
    }
    const decision = event.target.closest("[data-conflict-decision]");
    if (decision) {
      await resolveConflict(decision.dataset.conflictDecision);
      return;
    }
    if (event.target.closest("#createProjectBtn")) await createProject();
    if (event.target.closest("#startBuildBtn")) await startBuild();
    if (event.target.closest("#approveReviewBtn")) await approveReview();
    if (event.target.closest("#rerunBtn")) await startBuild();
    if (event.target.closest("#switchMockBtn") || event.target.closest("#switchMockBtnInline")) switchToMock();
    if (event.target.closest("#closeBlockerBtn")) hideLlmBlocker();
    if (event.target.closest("#refreshBtn")) await loadProjects();
    if (event.target.closest("#focusStageBtn")) {
      state.collapsed.brief = true;
      state.collapsed.evidence = true;
      state.collapsed.logs = true;
      render();
    }
  } catch (error) {
    toast(error.message);
  }
});

qs("#providerMode").addEventListener("change", () => {
  renderProviderBlocker();
  if (qs("#providerMode").value === "llm" && !state.config?.llm?.configured) {
    toast("LLM 配置缺失，Start BuildRun 会被阻塞。");
  }
});

loadProjects().catch((error) => toast(error.message));
