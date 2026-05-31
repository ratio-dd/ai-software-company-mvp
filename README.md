# AI Software Company MVP v0.1

Multi-agent collaboration platform for the engineering assignment. The default path is Mock mode, so it runs without any LLM key.

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
- Frontend/Backend API ContractChecker.
- Conflict as a business state, not a failed state.
- Retryable AgentRun failures create a new `AgentRun` attempt in the same BuildRun before the BuildRun is marked failed.
- Human CTO review gate and conflict decision.
- SQLite metadata state.
- Local filesystem artifact store.
- ZIP export with `prd.md`, `architecture.md`, `api-contract.json`, `frontend/`, `backend/`, and `qa_report.md`.

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

When configured, the platform calls `${LLM_BASE_URL}/chat/completions` and expects JSON shaped as `{"files": {"relative/path": "content"}}`. Selecting LLM with missing config fails with `provider_config`; it never falls back to Mock.

LLM mode does not grant arbitrary tools to the model. v0.1 uses a minimal platform-owned tool loop: `read_context`, `propose_files`, `run_harness`, `run_contract_check`, and `export_artifacts`. Shell, browser, package installation, repository access, and autonomous repair tools are production extension points, not part of this evaluation build.

## E2E Tests

Playwright specs live under `tests/e2e`. After npm dependencies and browser binaries are installed, run:

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

By default the tests target `http://127.0.0.1:3000`; set `PLAYWRIGHT_BASE_URL` to test another running server. Without that override, the Playwright config starts `python3 app/server.py --port 3000` with a temporary `DATA_DIR`.
