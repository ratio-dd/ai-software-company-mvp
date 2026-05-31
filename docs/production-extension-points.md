# Production Extension Points

This document describes what the v0.1 evaluation build deliberately leaves as
extension points. The goal is to show the production path without shipping a
complete reusable internal agent platform.

## Current v0.1 Runtime

The current system is a lightweight in-process orchestrator:

```text
Web UI
  -> OrchestratorService
  -> AgentProvider
       -> MockProvider
       -> OpenAICompatibleProvider
  -> ArtifactHarness
  -> ContractChecker
  -> Repository / ArtifactStore / EventLog
```

The LLM provider is real in the sense that it can call an OpenAI-compatible
`/chat/completions` endpoint when configured. However, the LLM does not receive
arbitrary execution tools. It returns candidate files, and the platform runs the
deterministic gates.

## Minimal Platform-Owned Tool Loop

v0.1 exposes the smallest tool loop needed to complete the assignment safely:

| Tool | Owner | Purpose |
| --- | --- | --- |
| `read_context` | Platform | Prepare role-scoped project, previous artifact, alignment, and conflict context. |
| `propose_files` | Provider | Mock or LLM provider returns candidate files for the role. |
| `run_harness` | Platform | Validate required files, repair deterministic structure, extract manifests. |
| `run_contract_check` | Platform | Compare Frontend API usages with Backend routes. |
| `export_artifacts` | Platform | Package latest valid artifacts into a downloadable ZIP. |

This loop is enough to demonstrate multi-agent delivery while keeping execution
auditable and deterministic.

## Deliberately Excluded From v0.1

The following tools are not included in the evaluation build:

- Shell command execution.
- Browser automation.
- Package installation.
- Repository checkout or branch mutation.
- Internet access tools.
- General filesystem read/write outside artifact bundles.
- Autonomous generated-app test runner.
- Visual regression tools.
- Long-running self-repair loops.

These are not missing accidentally. They are production concerns that require
security, isolation, cost controls, and failure-policy design.

## Production AgentWorker Direction

A production version would replace the direct provider call with an isolated
worker boundary:

```text
OrchestratorService
  -> AgentRunScheduler
  -> AgentWorkerQueue
  -> AgentWorker
       -> WorkspaceSandbox
       -> ToolAllowlist
       -> SecretScope
       -> ModelProvider
       -> ArtifactEmitter
  -> ArtifactHarness
  -> ContractChecker
```

The state machine should remain owned by the platform. Agent workers should not
decide BuildRun status, Conflict status, retry exhaustion, or export readiness.

## Tool Expansion Plan

| Area | v0.1 | Production extension |
| --- | --- | --- |
| LLM provider | OpenAI-compatible chat completion | Multi-provider router, model policies, prompt registry |
| Agent tools | Minimal platform-owned loop | Sandboxed shell, browser, package install, test runner |
| Isolation | DB rows + per-AgentRun artifact folder | Per-Agent container or workspace sandbox |
| Frontend validation | API usage extraction | Generated app smoke test and visual QA |
| API checking | Regex/manifest extraction | AST-level route and client extraction |
| Repair | Retry by failure category | Multi-round repair loop with bounded tool budget |
| Scheduling | In-process calls and FE/BE threads | Durable queue, resumable workers, cancellation |
| Secrets | Process env for LLM provider | Per-Agent scoped credentials and redaction |
| Audit | SQLite LogEvent | Replayable traces, cost accounting, decision audit |
| Multi-user | Single local operator | Auth, roles, project ownership, approval policies |

## Tool Policy

Production tools should be granted by role and by stage:

| Role | Likely production tools |
| --- | --- |
| PM | Requirements context read, PRD schema validation |
| Architect | API contract validation, design linting, dependency policy checks |
| Frontend | Workspace write, package install, test runner, browser screenshot QA |
| Backend | Workspace write, package install, API smoke test, route scanner |
| QA | Generated app runner, contract tests, report generator |

Each tool should have:

- explicit input schema,
- allowed filesystem scope,
- network policy,
- secret access policy,
- timeout,
- cost budget,
- structured result,
- audit event.

## Why The Evaluation Build Stops Here

The evaluation build demonstrates the engineering backbone:

- role-oriented AgentRun attempts,
- BuildRun as a full session,
- deterministic ArtifactHarness gates,
- conflict as business state rather than failure,
- human CTO decision points,
- explicit Mock/LLM provider switch,
- runnable Docker Compose path,
- evidence and E2E tests.

It does not ship the full production tool runtime because that would turn the
interview submission into a reusable internal platform. The important design
choice is that the existing boundaries are compatible with such a runtime
without requiring the state model to be rewritten.
