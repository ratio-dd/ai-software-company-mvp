# AI Software Company MVP v0.1

Multi-agent collaboration platform for the engineering assignment. The default path is Mock mode, so it runs without any LLM key.

中文说明见 [README.zh-CN.md](./README.zh-CN.md).

## Evaluation License Notice

This repository is submitted for recruiting/interview evaluation only. It is not open source and is not licensed for commercial use, product use, internal tooling reuse, redistribution, model training, or derivative development outside the evaluation process.

See [LICENSE-EVALUATION.md](./LICENSE-EVALUATION.md) for the full evaluation-only terms.

## Interview Submission Notes

Start with [SUBMISSION.md](./SUBMISSION.md) for the recommended review path, implemented scope, and evaluation-build boundaries.

Production-grade agent tools such as sandboxed shell execution, browser automation, package installation, generated-app smoke runners, and autonomous repair loops are documented as extension points rather than shipped as reusable production infrastructure. See [docs/production-extension-points.md](./docs/production-extension-points.md).

## Start

```bash
docker-compose up --build
```

Open:

```text
http://127.0.0.1:3000
```

Local Python-only start:

```bash
python3 app/server.py --port 3000
```

## Project Structure

```text
app/
  server.py              # Python stdlib API server, orchestrator, providers, harness, export
  static/                # CTO-facing Web UI
docs/
  production-extension-points.md
  assignment-gap-analysis.md
output/
  requirements/          # requirement clarification and architecture design notes
  pdf/                   # parsed PDF source material and page/diagram references
  prototypes/            # earlier static UI prototype
  reports/               # MVP verification report
tests/
  e2e/                   # Playwright flow and responsive layout tests
  unit/                  # ContractChecker unit tests
```

## Architecture Overview

The platform keeps orchestration state outside the model. PM, Architect,
Frontend, Backend, and QA are represented as `AgentRun` attempts inside a
`BuildRun` session. Each successful AgentRun emits an `Artifact`; raw provider
output must pass through `ArtifactHarness` before it becomes a valid artifact.

```text
Web UI
  -> OrchestratorService
  -> AgentProvider
       -> MockProvider
       -> OpenAICompatibleProvider
  -> ArtifactHarness
  -> ConflictScenarioHarness
  -> ContractChecker
  -> RuntimeHarness
  -> Repository / ArtifactStore / EventLog
```

Core entities:

- `Project`: user-facing container with current status and active BuildRun.
- `BuildRun`: one full build session; retries and conflict resolution happen
  inside it.
- `AgentRun`: one role attempt with `attempt_no`, `trigger_reason`,
  input/output artifact IDs, retry metadata, and optional conflict link.
- `Artifact`: versioned generated output plus manifest and harness report.
- `Conflict`: Frontend/Backend API mismatch business state, not a failed state.
- `ReviewGate`: Human CTO approval point.
- `LogEvent`: append-only runtime evidence.

## Agent Orchestration Logic

The implemented flow is:

1. PM Agent creates `prd.md`.
2. Architect Agent creates `architecture.md` and `api-contract.json`.
3. If `human_review_required` is enabled, the build pauses for CTO approval.
4. Frontend and Backend AgentRuns execute in parallel threads.
5. If `force_api_conflict` is enabled and generation did not already produce a
   mismatch, ConflictScenarioHarness deterministically rewrites the latest
   Frontend artifact to create an API mismatch.
6. ContractChecker compares Frontend API usages with Backend routes.
7. If mismatches exist, the project enters `conflict` and waits for CTO
   decision.
8. Conflict decisions:
   - `以前端为准`: rerun Backend Agent with `alignment_mode=align_to_frontend`.
   - `以后端为准`: rerun Frontend Agent with `alignment_mode=align_to_backend`.
   - `强制通过`: skip rerun and continue to QA.
9. RuntimeHarness starts the latest generated frontend/backend before QA.
10. QA Agent creates `qa_report.md`.
11. ZIP export packages the latest valid artifacts.

Retryable failures create a new AgentRun attempt inside the same BuildRun before
the BuildRun is marked failed.

## Conflict Detection

ArtifactHarness extracts:

- Frontend API usages from `fetch(...)` / `axios(...)` calls and request key
  comments/schema hints.
- Backend routes from generated route declarations and route schema hints.

ContractChecker compares method, path, and request keys. Open mismatches are
shown in the Human CTO decision panel with red-highlighted rows and decision
buttons. Resolved conflicts preserve the original Frontend/Backend attempts and
record the resolution AgentRun when a rerun occurs.

The conflict demo switch is platform-owned. LLM output is not trusted to create
the scenario; when needed, ConflictScenarioHarness creates a new frontend
artifact version with an auditable harness report.

## Demo Path

1. Open the Web UI.
2. Use the prefilled project, or edit project name and requirement.
3. Keep `Provider=Mock`.
4. Keep `force_api_conflict` enabled to demonstrate Human CTO conflict resolution.
5. Click `创建 Project`.
6. Click `Start BuildRun`.
7. If review is enabled, click `通过审核`.
8. Resolve the API conflict:
   - `以前端为准`: reruns Backend Agent.
   - `以后端为准`: reruns Frontend Agent.
   - `强制通过`: skips rerun and proceeds to QA.
9. Download ZIP after the BuildRun reaches `completed`.

## What MVP v0.1 Covers

- Project creation.
- BuildRun as a full build session.
- AgentRun attempts for PM, Architect, Frontend, Backend, and QA.
- MockProvider as the default complete path.
- Explicit Mock/LLM provider dispatch. LLM mode uses an OpenAI-compatible chat completions endpoint when configured, and fails with `provider_config` when required env vars are missing.
- ArtifactHarness for required files, deterministic repair, manifest extraction, and harness reports.
- ConflictScenarioHarness for deterministic API mismatch injection when the demo switch is enabled.
- Frontend/Backend API ContractChecker.
- RuntimeHarness that starts generated frontend/backend on assigned ports before QA and records `runtime_report`.
- Conflict as a business state, not a failed state.
- Retryable AgentRun failures create a new `AgentRun` attempt in the same BuildRun before the BuildRun is marked failed.
- Human CTO review gate and conflict decision.
- SQLite metadata state.
- Local filesystem artifact store.
- ZIP export with `prd.md`, `architecture.md`, `api-contract.json`, `frontend/`, `backend/`, `runtime_report`, and `qa_report.md`.

For the explicit PDF-to-implementation mapping, see
[docs/assignment-gap-analysis.md](./docs/assignment-gap-analysis.md).

## Data

Runtime state is stored under:

```text
data/
  app.db
  artifacts/
  exports/
```

Delete `data/` to reset local state.

## LLM Mode

The UI allows explicit LLM mode. It requires:

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://openai-compatible-host/v1
LLM_MODEL=...
```

DeepSeek smoke-tested example:

```bash
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

When configured, the platform calls `${LLM_BASE_URL}/chat/completions` and expects JSON shaped as `{"files": {"relative/path": "content"}}`. Selecting LLM with missing config fails with `provider_config`; it never falls back to Mock.

LLM mode does not grant arbitrary tools to the model. v0.1 uses a minimal platform-owned tool loop: `read_context`, `propose_files`, `run_harness`, `run_conflict_scenario`, `run_contract_check`, `run_runtime_harness`, and `export_artifacts`. Shell, browser, package installation, repository access, and autonomous repair tools are production extension points, not part of this evaluation build.

## E2E Tests

Playwright specs live under `tests/e2e`. After npm dependencies and browser binaries are installed, run:

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

By default the tests target `http://127.0.0.1:3000`; set `PLAYWRIGHT_BASE_URL` to test another running server. Without that override, the Playwright config starts `python3 app/server.py --port 3000` with a temporary `DATA_DIR`.

## Local Development Checklist

```bash
python3 -m py_compile app/server.py
node --check app/static/app.js
node --check tests/e2e/mvp-flow.spec.js
python3 -m unittest tests.unit.test_contract_checker
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 npm run test:e2e
```

The Playwright run covers Mock mode, LLM missing-config blocker, conflict
resolution, ZIP export, artifact evidence, the minimal toolset boundary, and
desktop/tablet/mobile overflow checks.
