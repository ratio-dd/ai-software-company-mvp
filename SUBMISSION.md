# AI Software Company MVP v0.1 - Interview Submission

This repository is an evaluation build for the engineering assignment. It is
intended to demonstrate product judgment, state-machine design, multi-agent
orchestration boundaries, artifact validation, conflict handling, and a runnable
CTO-facing Web UI.

It is not a production-ready reusable platform, and it is not licensed for
commercial use or internal tooling reuse. See
[LICENSE-EVALUATION.md](./LICENSE-EVALUATION.md).

## What To Review First

1. `README.md` for startup and demo instructions.
2. `output/requirements/requirements-clarification-v0.1.md` for scope and
   requirement decisions.
3. `output/requirements/state-machine-v0.1.md` for BuildRun, AgentRun,
   Artifact, Conflict, and ReviewGate semantics.
4. `output/requirements/artifact-harness-v0.1.md` for deterministic artifact
   validation and manifest extraction.
5. `docs/production-extension-points.md` for intentional v0.1 boundaries and
   production evolution points.

## Recommended Demo Path

```bash
docker-compose up --build
```

Open:

```text
http://127.0.0.1:3000
```

Recommended flow:

1. Keep `Provider=Mock` to verify the no-key path.
2. Keep `force_api_conflict` enabled.
3. Create a Project and start a BuildRun.
4. Approve the Human CTO review gate if it appears.
5. Resolve the Frontend/Backend API mismatch.
6. Inspect the Pipeline node details and Evidence dock.
7. Download the final ZIP.

## What Is Fully Implemented In v0.1

- Runnable Docker Compose application.
- SQLite-backed Project, BuildRun, AgentRun, Artifact, Conflict, ReviewGate,
  and LogEvent state.
- Mock mode that completes the full flow without any LLM key.
- Explicit LLM provider dispatch using an OpenAI-compatible chat completions
  endpoint when configured.
- Minimal platform-owned tool loop:
  - `read_context`
  - `propose_files`
  - `run_harness`
  - `run_contract_check`
  - `export_artifacts`
- ArtifactHarness validation, deterministic repair, manifest extraction, and
  harness reports.
- Frontend/Backend API mismatch detection.
- Human CTO review and conflict resolution decisions.
- ZIP export with generated frontend/backend artifacts.
- Playwright E2E coverage for Mock flow, LLM missing-config blocker, conflict
  handling, artifact evidence, and responsive overflow checks.

## Important Runtime Boundary

v0.1 implements logical multi-agent orchestration, not a production-grade
sandboxed agent runtime.

- Each role has a separate `AgentRun` record, attempt number, trigger reason,
  input artifact list, output artifact list, and failure/retry metadata.
- Frontend and Backend AgentRuns are scheduled in parallel threads.
- Artifact isolation is implemented through per-AgentRun artifact directories.
- The LLM provider does not receive arbitrary shell, browser, package install,
  repo checkout, or test runner tools.
- Platform-owned deterministic tools run outside the LLM and remain controlled
  by the orchestrator.

This boundary is intentional for the evaluation build. It keeps the submission
auditable while preserving clear production extension points.

## What Is Intentionally Not Included

The following areas are documented as extension points but are not fully
implemented in this evaluation build:

- Sandboxed shell execution.
- Browser automation tools for generated apps.
- Package installation tools.
- Repository checkout or multi-repo editing.
- Autonomous multi-round repair loops.
- Worker queue and distributed AgentWorker runtime.
- Per-Agent secret scopes.
- Containerized per-Agent workspace isolation.
- AST-level API extraction.
- Visual QA for generated frontend artifacts.
- Multi-provider model routing and prompt/version registry.
- Multi-user authentication and authorization.

See [docs/production-extension-points.md](./docs/production-extension-points.md)
for the rationale and production direction.

## Why This Scope

The assignment primarily evaluates engineering tradeoffs and architecture
design. This v0.1 focuses on the hard-to-fake backbone:

- state semantics,
- deterministic gates,
- artifact contracts,
- human-in-the-loop conflict handling,
- runnable demo path,
- testable behavior.

Production agent tools have security, isolation, cost, and reliability
implications. They should be added deliberately behind the existing
`AgentProvider` and tool boundary rather than hidden inside a prototype.
