# PDF Goal Gap Analysis

This document compares the current implementation against the parsed assignment
PDF in `output/pdf/ai-software-company-multi-agent-platform.md`.

Status meanings:

- `Covered`: implemented and verified in the current repository.
- `Partial`: the core requirement is present, but there is a deliberate scope
  boundary or a non-critical fidelity difference.
- `Extension`: intentionally left as a documented production/evaluation
  extension point.

## Executive Summary

The current MVP covers the assignment's primary requirements:

- runnable source code with Docker Compose,
- PM / Architect / Frontend / Backend / QA roles,
- nonlinear flow with Frontend and Backend running in parallel,
- API contract mismatch detection,
- Human CTO conflict decisions,
- artifact viewing,
- ZIP export,
- OpenAI-compatible LLM provider path,
- no-key Mock demo path,
- README and architecture documentation.

The remaining gaps are mostly deliberate boundaries:

- LLM mode uses file-bundle generation, not a full autonomous tool runtime.
- Human artifact editing before approval is not implemented.
- UI pipeline is optimized as a CTO command center rather than an exact clone
  of the PDF wireframe.
- Production-grade sandboxing, browser tools, shell tools, and autonomous repair
  are extension points.

## Requirement Matrix

| PDF requirement | Current status | Evidence | Notes |
| --- | --- | --- | --- |
| Build an "AI Software Company" multi-agent collaboration platform | Covered | `app/server.py`, Web UI, `docker-compose.yml` | Runnable local platform. |
| User acts as Human CTO and inputs product requirements | Covered | `app/static/index.html`, `app/static/app.js` | Project Brief form accepts project name and requirement. |
| Automatically coordinate 5 AI Agent roles | Covered | `ROLES`, `run_initial_until_pause_or_done`, `continue_after_review` | PM, Architect, Frontend, Backend, QA are separate AgentRun roles. |
| PM Agent outputs Markdown PRD | Covered | `MockProvider`, `ArtifactHarness` | `prd.md` required and exported. |
| Architect outputs architecture doc and API contract | Covered | `architecture.md`, `api-contract.json` | API contract is JSON rather than full OpenAPI schema; sufficient for v0.1 contract checking. |
| Frontend Agent generates frontend page code | Covered | `frontend/README.md`, `frontend/server.py`, `frontend/index.html`, `frontend/src/app.js` | Static HTML + JS, allowed by PDF's React/HTML + JS wording. |
| Backend Agent generates API implementation | Covered | `backend/README.md`, `backend/server.py` | Python stdlib API server. |
| QA Agent outputs Markdown test plan/report | Covered | `qa_report.md` | Generated and exported after conflict resolution. |
| PM -> Architect -> parallel FE/BE -> contract check -> QA | Covered | `run_initial_until_pause_or_done`, `run_parallel_agents`, `run_contract_check`, `run_qa_and_complete` | FE/BE are scheduled in parallel threads. |
| Detect Frontend/Backend API mismatch | Covered | `ArtifactHarness.extract_frontend_usages`, `extract_backend_routes`, `ContractChecker.compare` | Compares method, path, and request keys. |
| Enter `conflict` state when mismatch exists | Covered | `conflicts` table, project status `conflict` | Conflict is modeled as business state, not failed state. |
| Show conflict points in project detail page | Covered | `renderDecision` mismatch table | Mismatch rows are red-highlighted in the decision panel. |
| CTO buttons: align to frontend, align to backend, force pass | Covered | `resolve_conflict`, UI decision buttons | All three actions implemented. |
| Rerun corresponding Agent and keep other artifacts unchanged | Covered | `alignment_mode`, `resolves_conflict_id`, `superseded` attempts | Resolution creates new Frontend or Backend AgentRun. |
| Optional human review point | Covered | ReviewGate model and approval button | Implemented as architecture review gate. |
| Human can directly edit artifact before approval | Extension | Not implemented | This is explicitly out of v0.1; editing requires artifact editor, validation, and audit policy. |
| Project creation: name + requirement | Covered | `/api/projects`, Project Brief UI | Implemented. |
| Project list with status/current phase | Covered | `/api/projects` includes project status and active BuildRun stage | UI shows project status, active build, and stage. |
| Project detail page with title/status/start build | Covered | Web UI header/status strip/Brief panel | Layout adapted into CTO command center. |
| Visual pipeline with dependencies | Covered | `BuildRun Pipeline` timeline | Uses vertical CTO-friendly timeline rather than exact PDF box diagram. |
| Click Agent node to view artifacts | Covered | Pipeline node selection + `查看产物` | Evidence panel opens from selected node. |
| Markdown rendering for PRD/architecture/QA | Covered | `renderMarkdown` | Markdown files render as HTML. |
| Code highlighting for frontend/backend code | Covered | `highlightCode` | Lightweight code rendering, not full syntax parser. |
| Conflict area only visible in conflict state | Covered | `renderDecision` | Conflict panel appears only for open conflict. |
| Red-highlighted differences | Covered | `.conflict-card`, `.mismatch-row.issue` | Added explicit red visual treatment. |
| Logs in reverse chronological order, collapsible | Covered | `renderLogs`, Logs dock | Current query returns newest first and the panel is collapsible. |
| ZIP export after completion | Covered | `/api/build-runs/{id}/export` | Packages latest PM, architecture, frontend, backend, QA artifacts. |
| ZIP contains `prd.md`, `architecture.md`, `frontend/`, `backend/`, `qa_report.md` | Covered | `export_zip` and E2E export test | Also includes `api-contract.json`. |
| LLM mode through OpenAI-compatible API | Covered | `OpenAICompatibleProvider` | Requires `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. |
| Mock mode must run without LLM key | Covered | `MockProvider`, default provider | E2E verifies no-key path. |
| "未配置 API Key 时自动进入 Mock" | Partial | UI default is Mock; LLM missing config blocks explicitly | This is a deliberate user-approved deviation: no silent fallback when LLM is explicitly selected. |
| Mock content dynamically uses project name/requirement | Covered | `MockProvider.run` | Project name and requirement are interpolated into generated artifacts. |
| Mock conflict scenario | Covered | `force_api_conflict` | Toggleable in UI and API. |
| Example scheduling system flow | Covered | Default Brief is a scheduling system | Generated frontend/backend and tests use scheduling examples. |
| Full source code with clear README | Covered | `README.md`, `SUBMISSION.md`, docs | README now includes architecture, orchestration, conflict detection, env, dev/test steps. |
| `docker-compose.yml` one-command start | Covered | `docker-compose.yml` | `docker-compose up --build`. |
| README architecture design explanation | Covered | `README.md` Architecture Overview / Orchestration / Conflict Detection | Implemented. |
| README local development steps | Covered | `README.md` Start / Local Development Checklist | Implemented. |
| README environment variables | Covered | `README.md` LLM Mode | Implemented. |
| README Mock mode no-key conflict demo | Covered | `README.md` Demo Path | Implemented. |

## Deliberate Evaluation-Build Boundaries

The following are intentionally not shipped as reusable production
infrastructure:

1. **Full agent tool runtime**
   - Current: minimal platform-owned tool loop.
   - Extension: sandboxed shell, browser automation, test runner, package
     install, repo checkout.

2. **Agent isolation**
   - Current: logical AgentRun isolation, DB state, per-AgentRun artifact
     directory.
   - Extension: per-Agent container/workspace sandbox and secret scope.

3. **Artifact editing**
   - Current: Human CTO can approve or resolve conflicts.
   - Extension: in-browser artifact editor with audit trail and revalidation.

4. **Generated app QA**
   - Current: artifact harness, contract check, export test, and a smoke test
     during development.
   - Extension: integrated generated app runner, browser visual QA, screenshot
     comparison.

5. **OpenAPI fidelity**
   - Current: compact JSON API contract sufficient for route comparison.
   - Extension: full OpenAPI schema generation and validation.

## Current Risk / Gap Register

| Gap | Impact | Recommended next step |
| --- | --- | --- |
| LLM provider is implemented but not verified with a real key in this repo state | The interface exists, but quality depends on model output | Run one private LLM smoke test before final submission if credentials are available. |
| No artifact editor for Human CTO review | Optional PDF bonus not fully covered | Document as extension or add a constrained Markdown editor later. |
| Contract extraction is regex/manifest based | Good for v0.1, weaker than AST-level extraction | Keep as stated extension point. |
| No production sandbox/tool runtime | Prevents direct internal-platform reuse, but limits real autonomous coding | Keep as deliberate evaluation boundary. |
| UI differs from original PDF wireframe | Better CTO usability, but not pixel-identical | README/SUBMISSION should frame it as command-center interpretation of required regions. |

## Final Assessment

The implementation satisfies the assignment's core deliverables and demonstrates
the engineering architecture expected by the PDF. Remaining gaps are either
optional bonus features or deliberate evaluation-build boundaries documented in
`SUBMISSION.md` and `docs/production-extension-points.md`.
