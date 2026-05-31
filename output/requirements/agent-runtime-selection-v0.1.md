# AI Software Company - Agent Runtime 选型 v0.1

> 依据:
> - `requirements-clarification-v0.1.md`
> - `state-machine-v0.1.md`
> - `artifact-harness-v0.1.md`
>
> 目标: 选择 v0.1 的多 Agent runtime / orchestrator 方案。这里讨论的是平台自身如何编排 PM / Architect / Frontend / Backend / QA，不是 generated `frontend/` / `backend/` 的技术栈。

## 1. 结论

v0.1 推荐使用 **自研轻量 Orchestrator Runtime**，不要把 LangGraph / CrewAI / AutoGen / Temporal 作为核心 runtime。

理由:

- 题目考查的是工程功能取舍和架构设计，核心应该是我们自己的 `Project / BuildRun / AgentRun / Artifact / Conflict / ReviewGate / LogEvent` 状态模型。
- 本项目流程是明确 DAG + 状态机，不是开放式多 Agent 聊天。
- MockProvider、LLMProvider、ArtifactHarness、ContractChecker 都需要确定性插入点。
- Human CTO 审核和 Conflict 决策是业务状态，不应被外部框架隐藏。
- 面试场景下，自研轻量 runtime 更容易解释，也更容易通过 README 和 UI 展示工程设计。

推荐边界:

```text
Core runtime: 自研 Orchestrator Runtime
LLM/Mock: Provider adapter
Quality gate: ArtifactHarness
API mismatch: ContractChecker
Persistence: app DB / file store
External agent frameworks: 不作为 v0.1 核心依赖，可后续作为 AgentProvider 内部实现
```

## 2. 选型标准

| 标准 | 重要性 | 说明 |
| --- | --- | --- |
| 显式状态机 | 高 | 必须准确表达 BuildRun、AgentRun、Conflict、ReviewGate |
| Human-in-the-loop | 高 | 必须暂停、展示、等待 CTO 操作后恢复 |
| 并行执行 | 高 | Frontend / Backend 必须并行 |
| Retry 可控 | 高 | failure_category、attempt、retry 规则必须由我们控制 |
| Mock/LLM 共用路径 | 高 | Mock 不能绕过真实编排 |
| Harness 插入 | 高 | Agent 输出必须先过确定性 harness |
| Conflict 可解释 | 高 | Conflict 只表示 FE/BE API mismatch |
| Docker Compose 简单 | 高 | 面试官应能直接启动 |
| 面试可解释性 | 高 | 架构不能被黑盒 framework 抢走重点 |
| 长期可扩展 | 中 | 后续可迁移到 durable workflow 或 graph runtime |

## 3. 候选方案

### 3.1 自研轻量 Orchestrator Runtime

核心思路:

```text
OrchestratorService
  -> StateMachineReducer
  -> AgentRunScheduler
  -> AgentProvider
       -> MockProvider
       -> OpenAICompatibleProvider
  -> ArtifactHarness
  -> ContractChecker
  -> Repository / EventLog
```

能力映射:

| 需求 | 实现方式 |
| --- | --- |
| BuildRun 构建会话 | 自有 DB 表 |
| AgentRun attempt | 自有 DB 表，`attempt_no` + `trigger_reason` |
| FE/BE 并行 | in-process async queue / worker pool |
| Human review | BuildRun pause + ReviewGate open |
| Conflict | 独立 Conflict 表 |
| Retry | Orchestrator 创建新 AgentRun |
| Mock/LLM | Provider adapter |
| Harness | AgentRun 完成后同步执行 |
| Contract check | Deterministic ContractChecker |
| Logs | Append-only LogEvent |

优点:

- 最贴合当前状态机。
- 最容易解释。
- Mock/LLM、harness、conflict 都是清晰的一等概念。
- 本地部署最轻。
- 不被 framework conversation model 牵着走。

缺点:

- 要自己实现基本调度、持久化、retry、resume。
- 如果未来需要强 durable execution，需要迁移或补充运行时。

v0.1 判断:

**推荐。** 本项目流程规模小、状态边界明确，自研 runtime 成本低于引入重框架的理解和适配成本。

### 3.2 LangGraph

官方定位强调 stateful graph、durable execution、persistence、human-in-the-loop。官方文档说明其 persistence/checkpointer 支持 human-in-the-loop、fault-tolerant execution、interrupt/resume 等能力。

适配方式:

```text
LangGraph graph
  PM node
  Architect node
  Frontend node + Backend node
  ContractCheck node
  QA node
```

优点:

- 图结构和我们的 Phase flow 比较接近。
- 有 checkpoint / interrupt / resume 概念，适合 human-in-the-loop。
- 对长流程和可恢复执行比纯手写更成熟。

缺点:

- 会引入 LangGraph 的 thread/checkpoint/Command/interrupt 语义，需要和我们的 BuildRun/AgentRun/Artifact 模型映射。
- 我们仍然需要自建 ArtifactHarness、Conflict、ZIP、UI state。
- 对 v0.1 来说可能增加解释负担。

v0.1 判断:

**备选，不作为默认。** 如果后续决定主后端用 Python，并希望借用 graph checkpoint/human interrupt，可以考虑；但核心系统-of-record 仍建议保留在自有 DB 模型里。

### 3.3 CrewAI / CrewAI Flows

CrewAI 有 Agents/Creds/Flows 概念；官方文档中 Flows 支持 start/listen/router、状态、持久化、人类反馈等。

优点:

- 面向多 Agent 协作，有现成 agents/tasks/flows 抽象。
- Flows 比 Crews 更适合受控工作流。
- Human feedback 和 persistence 有现成能力。

缺点:

- 框架更偏“agent 产品化抽象”，容易把 PM/Architect/Frontend/Backend 建成框架角色，而不是我们的业务状态机。
- 我们需要非常明确的 Artifact 和 Conflict，CrewAI 的默认抽象不一定贴合。
- 面试官可能看到的是“套了 CrewAI”，而不是我们自己设计的 runtime。

v0.1 判断:

**不推荐作为核心 runtime。** 可以作为后续某个 AgentProvider 内部实现，但不要让它拥有 BuildRun/Conflict 的主状态。

### 3.4 AutoGen

AutoGen 更偏多 Agent 对话、消息、topic/subscription/runtime。官方 core docs 描述了 agent runtime、topic、subscription 等事件式 agent 系统能力。

优点:

- 多 Agent 消息模型强。
- 适合开放式对话、agent-to-agent 协商、工具调用。
- 后续如果要展示“真实多 Agent conversation”，可以考虑。

缺点:

- 本题 v0.1 是明确 pipeline，不需要开放式群聊。
- Frontend/Backend 并行 + ContractCheck + CTO 决策更像状态机，不像 chat。
- Artifact/Conflict/Harness 仍需自建。

v0.1 判断:

**不推荐作为核心 runtime。** 它会把简单可解释的工程流程变成多 Agent 消息系统，偏离当前 MVP 重点。

### 3.5 Temporal

Temporal 是 durable execution / workflow engine，不是 AI agent framework。官方文档强调 crash-proof / durable execution，适合长期运行和强恢复语义。

优点:

- Durable execution、retry、恢复能力很强。
- 对生产级长流程可靠性非常好。
- Activity/Workflow 模型适合把 LLM call、harness、zip 打包拆成 activity。

缺点:

- 对 v0.1 太重。
- Docker Compose 和本地启动复杂度上升。
- 面试题重点会被 Temporal infrastructure 抢走。
- Human CTO UI / Artifact / Conflict 仍要自建。

v0.1 判断:

**不推荐。** 后续如果要把平台产品化、长流程可靠性成为核心诉求，再考虑。

## 4. 推荐架构

### 4.1 Runtime 模块

```text
Runtime/
  OrchestratorService
  StateMachineReducer
  AgentRunScheduler
  AgentExecutor
  ProviderAdapter
  ArtifactHarnessRunner
  ContractChecker
  ExportService
  EventLogger
```

### 4.2 执行流程

```text
start_build
  -> create BuildRun
  -> create PM AgentRun(trigger_reason=initial)
  -> execute AgentRun
  -> ProviderAdapter returns CandidateArtifactBundle
  -> ArtifactHarness validates/repairs/extracts
  -> save Artifact + LogEvent
  -> maybe ReviewGate
  -> next stage
```

Frontend / Backend 并行:

```text
architect completed
  -> create frontend AgentRun
  -> create backend AgentRun
  -> scheduler runs both concurrently
  -> both completed
  -> contract_check
```

Conflict:

```text
ContractChecker mismatch
  -> create Conflict(open)
  -> pause BuildRun
  -> CTO decision
  -> create new FE or BE AgentRun(trigger_reason=conflict_resolution)
  -> contract_check again
```

Retry:

```text
AgentRun failed retryable=true
  -> create AgentRun(trigger_reason=retry, retry_of_agent_run_id=...)
  -> same BuildRun, same stage
```

### 4.3 Provider Adapter

```text
AgentProvider {
  run(input: AgentRunInput): CandidateArtifactBundle
}
```

Implementations:

- `MockProvider`
- `OpenAICompatibleProvider`

Important:

- Provider 不推进状态机。
- Provider 不直接写 Artifact。
- Provider 不决定 Conflict。
- Provider 只返回候选输出。

### 4.4 Deterministic Modules

不属于 Agent Runtime 的 AI 部分:

- `ArtifactHarness`
- `ManifestExtractor`
- `ContractChecker`
- `ZipExporter`

这些模块必须是可测试、可重复、可解释的普通程序代码。

## 5. 为什么不先用外部框架

本题最重要的是展示工程判断:

- 哪些能力由 Agent 负责。
- 哪些能力由 deterministic harness 负责。
- 哪些状态是业务态。
- 哪些错误是 retryable failure。
- 哪些冲突需要 CTO 决策。

如果 v0.1 直接套重 agent framework，容易出现两个问题:

- 框架抽象覆盖了我们想展示的架构边界。
- 为了适配框架，反而弱化 BuildRun / AgentRun / Conflict / Artifact 这些核心建模。

因此更好的面试展示是:

```text
我们没有把 Agent 当魔法黑盒。
我们把 AI call 包在 Provider 里，
把质量控制放在 Harness，
把协作放在 Orchestrator，
把冲突放在 Conflict，
把人类决策放在 Review/Conflict gate。
```

## 6. 后续扩展点

未来可以这样迁移，而不推翻 v0.1:

| 未来需求 | 迁移方向 |
| --- | --- |
| 需要 checkpoint / resume 更强 | 将 Orchestrator backend 替换为 LangGraph 或 durable workflow |
| 需要生产级长流程可靠性 | 引入 Temporal，AgentRun 作为 activity |
| 需要开放式 agent 协商 | 某些 AgentProvider 内部用 AutoGen |
| 需要复杂 agent crew | 某些 AgentProvider 内部用 CrewAI |
| 需要 AST 级 API 提取 | 替换 deterministic manifest extractor |

关键是:

- `Project / BuildRun / AgentRun / Artifact / Conflict` 仍然是系统-of-record。
- 外部 framework 最多进入执行层，不接管业务状态。

## 7. 选型结论表

| 方案 | v0.1 适配度 | 主要问题 | 结论 |
| --- | --- | --- | --- |
| 自研轻量 Orchestrator | 高 | 自己实现调度/持久化/retry | 推荐 |
| LangGraph | 中高 | 需映射 checkpoint/thread 到 BuildRun/AgentRun | 备选 |
| CrewAI Flows | 中 | 偏框架 agent/flow 抽象，可能遮蔽业务状态 | 不作为核心 |
| AutoGen | 中低 | 偏多 Agent 对话，不贴合明确 pipeline | 不作为核心 |
| Temporal | 中 | 强但太重，不是 agent runtime | 后续生产化再考虑 |

## 8. 官方资料参考

- LangGraph: persistence、durable execution、interrupt / human-in-the-loop。
  - https://docs.langchain.com/oss/python/langgraph
  - https://docs.langchain.com/oss/python/langgraph/durable-execution
  - https://docs.langchain.com/oss/python/langgraph/human-in-the-loop
- CrewAI: Flows、persistence、human feedback。
  - https://docs.crewai.com/en/concepts/flows
  - https://docs.crewai.com/en/learn/human-feedback-in-flows
  - https://docs.crewai.com/en/concepts/production-architecture
- AutoGen: core runtime、topic/subscription、多 Agent runtime。
  - https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/index.html
  - https://microsoft.github.io/autogen/0.7.3/user-guide/core-user-guide/core-concepts/topic-and-subscription.html
- Temporal: durable execution / workflow engine。
  - https://docs.temporal.io/

## 9. 已确认决策

1. Agent Runtime 选型不绑定主后端语言，也不绑定 generated frontend/backend 技术栈。我们做的是平台，runtime 边界应先于具体语言/模板选型。
2. README 暂时不需要专门解释“为什么没有使用 LangGraph/CrewAI/AutoGen”。这些取舍保留在设计文档中即可。
3. v0.1 使用 SQLite 作为系统状态存储，本地文件系统保存 artifact 内容。
4. v0.1 使用 DB state + in-process scheduler，不从一开始引入 Redis、BullMQ、Celery 或独立 worker 服务。

## 10. 后续待确认

1. 主应用具体技术栈选择。该选择不改变本文 runtime 边界。
2. generated `frontend/` / `backend/` 的模板技术栈。该选择属于产物模板，不属于 Agent Runtime。
