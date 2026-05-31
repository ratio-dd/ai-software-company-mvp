# AI Software Company - ArtifactHarness 设计 v0.1

> 依据:
> - `requirements-clarification-v0.1.md`
> - `state-machine-v0.1.md`
>
> 目标: 设计 v0.1 的基础 harness。Harness 负责把 Agent 原始输出转成可保存、可展示、可检测、可下载、可运行的规范化 Artifact。

## 1. 设计结论

ArtifactHarness 是每个 AgentRun 成功前的确定性质量门。

它要做:

- 校验 Agent 输出是否符合该 role 的产物契约。
- 补齐确定性的固定文件和格式外壳。
- 规范化文件路径和文件名。
- 用确定性代码提取结构化 manifest，例如 API contract、frontend API usage、backend route manifest。
- 生成 harness report，记录校验、修复、失败原因。

它不能做:

- 不能替 Agent 编造核心业务内容。
- 不能调用 LLM。
- 不能跳过状态机。
- 不能把 Frontend/Backend API mismatch 直接记成 failed。
- 不能隐式读取历史 BuildRun 的产物。

核心原则:

```text
Agent raw output
  -> ProviderOutputAdapter
  -> ArtifactHarness
      -> normalize
      -> deterministic repair
      -> validate
      -> deterministic manifest extraction
      -> produce ArtifactBundle or retry/failure
```

## 2. Harness 边界

### 2.1 ProviderOutputAdapter vs ArtifactHarness

`ProviderOutputAdapter` 负责把 provider 输出转成候选文件包。

```text
MockProvider / OpenAICompatibleProvider
  -> raw output
  -> ProviderOutputAdapter
  -> CandidateArtifactBundle
```

`ArtifactHarness` 只处理候选文件包，不直接处理复杂 LLM 对话状态。

原因:

- MockProvider 可以天然返回结构化 bundle。
- LLM provider 可能返回 Markdown 或 JSON，需要先解析。
- Harness 应保持确定性和可测试。

### 2.2 Harness 不负责业务生成

可以 repair:

- 文件名大小写，例如 `PRD.md` -> `prd.md`。
- 缺少 Markdown 标题，但已有可用正文。
- 缺少 README 外壳。
- 缺少 manifest wrapper，但代码/契约可提取。
- 文件树缺少空目录占位。

不能 repair:

- PRD 没有功能列表。
- Architect 没有 API 契约。
- Frontend 没有任何 API 调用或可启动入口。
- Backend 没有任何路由定义。
- QA 报告没有测试用例。

这些属于核心内容缺失，应进入 `invalid_retryable`，由 Agent retry。

## 3. 通用数据结构

### 3.1 CandidateArtifactBundle

```text
CandidateArtifactBundle {
  role                  // pm | architect | frontend | backend | qa
  build_run_id
  agent_run_id
  files: Map<relative_path, content>
  metadata
  raw_output_ref
}
```

规则:

- 所有路径必须是相对路径。
- 禁止绝对路径。
- 禁止 `..` 路径穿越。
- 禁止写入 workspace 外部。
- 文本文件必须使用 UTF-8。

### 3.2 NormalizedArtifactBundle

```text
NormalizedArtifactBundle {
  role
  artifact_type
  files: Map<canonical_relative_path, content>
  manifests
  harness_report
}
```

### 3.3 HarnessResult

```text
HarnessResult {
  status                 // valid | repaired | invalid_retryable | invalid_final
  normalized_bundle
  errors
  warnings
  repairs
  extracted_manifests
}
```

状态含义:

| status | 含义 | 状态机行为 |
| --- | --- | --- |
| `valid` | 原始输出满足契约 | 保存 Artifact |
| `repaired` | 经过确定性修复后满足契约 | 保存 Artifact，记录 repair log |
| `invalid_retryable` | 核心内容缺失或结构严重错误，可能通过重跑修复 | Agent retry |
| `invalid_final` | 明确不可修复，或 retry 耗尽后仍失败 | `generation_invalid` |

## 4. 通用 Harness 流程

### 4.1 Normalize

基础规范化:

- 统一路径分隔符为 `/`。
- 去除危险路径。
- 合并重复路径，重复冲突时标记 warning 或 error。
- 统一核心文件名:
  - `PRD.md` / `prd.MD` -> `prd.md`
  - `Architecture.md` -> `architecture.md`
  - `QA.md` / `qa.md` -> `qa_report.md`
- 为 role 加默认目录前缀:
  - PM: root `prd.md`
  - Architect: root `architecture.md`, `api-contract.json`
  - Frontend: `frontend/`
  - Backend: `backend/`
  - QA: root `qa_report.md`

### 4.2 Deterministic Repair

允许的修复:

- 补 Markdown 一级标题。
- 补缺失但可确定的 README 外壳。
- 补固定目录和占位文件。
- 从代码中提取 API usage / route manifest。
- 从 API 契约 Markdown 表格转成 `api-contract.json`。
- 为 generated frontend/backend 补运行说明。

不允许的修复:

- 编造业务功能。
- 编造用户故事。
- 编造 API 路由。
- 编造测试用例。
- 自动改变 Frontend API 调用以匹配 Backend，或反过来。该行为必须走 Conflict 决策。

### 4.3 Validate

每个 role 先执行通用校验:

- 必需文件存在。
- 文件不为空。
- 文件路径合法。
- 产物大小在合理范围。
- 文本可解码。

再执行 role-specific 校验。

### 4.4 Deterministic Manifest Extraction

Manifest 是后续 Orchestrator 和 UI 使用的结构化证据。

必须提取:

- Architect: `api_contract`
- Frontend: `api_usages`
- Backend: `routes`

可选提取:

- PM: `feature_list`
- QA: `test_cases`
- Generated frontend/backend: `run_manifest`

### 4.5 Persist

只有 `valid` 或 `repaired` 可以保存为有效 Artifact。

保存内容:

- normalized files。
- extracted manifests。
- harness report。
- source agent_run_id。

## 5. 通用 Harness Report

每次 harness 执行都生成 report:

```text
HarnessReport {
  role
  status
  checks: [
    { id, status, message, severity }
  ]
  repairs: [
    { id, description, files_changed }
  ]
  manifests: [
    { type, path, item_count }
  ]
  retry_recommendation
}
```

Severity:

| severity | 含义 |
| --- | --- |
| `info` | 记录信息 |
| `warning` | 已修复或不阻塞 |
| `error` | 阻塞当前 Artifact，但可 retry |
| `fatal` | 不可恢复或 retry 后仍失败 |

## 6. Role Harness 契约

### 6.1 PM Harness

Artifact:

- `prd.md`

必需章节:

- 产品目标
- 目标用户
- 核心功能列表
- 用户故事
- 验收标准
- 非目标范围

可提取 manifest:

```text
feature_manifest {
  features: [
    { id, title, description, priority }
  ]
  user_stories: [
    { as_a, i_want, so_that }
  ]
}
```

可 repair:

- 补 `# PRD - {project_name}` 标题。
- 标准化章节标题。
- 把 bullet list 归并到“核心功能列表”章节。

不可 repair:

- 完全缺少功能列表。
- 完全缺少用户故事。
- 内容与项目需求明显无关。

失败分类:

- 核心内容缺失 -> `generation_invalid`

### 6.2 Architect Harness

Artifact:

- `architecture.md`
- `api-contract.json`

必需章节:

- 架构概览
- 主要模块
- 数据模型
- API 契约
- 前后端协作说明

`api-contract.json` v0.1 schema:

```json
{
  "version": "1.0",
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/courses",
      "summary": "List courses",
      "requestParams": [],
      "requestBody": null,
      "responseBody": {
        "type": "array"
      }
    }
  ]
}
```

可 repair:

- 从 `architecture.md` 中的 API 表格提取 `api-contract.json`。
- 标准化 HTTP method 大小写。
- 标准化 path 前缀，确保以 `/` 开头。

不可 repair:

- 没有任何 API endpoint。
- API path/method 无法解析。
- 数据模型完全缺失。

失败分类:

- 缺 API 契约 -> `generation_invalid`
- API 契约可读但字段缺失 -> harness repair 或 `generation_invalid`

### 6.3 Frontend Harness

Artifact:

- `frontend/`

必需文件:

- `frontend/README.md`
- `frontend/package.json` 或后续选定技术栈等价文件
- 前端入口文件，例如 `frontend/src/main.*` 或 `frontend/index.html`
- `frontend/manifest/api-usages.json`
- `frontend/manifest/run.json`

`api-usages.json` schema:

```json
{
  "usages": [
    {
      "method": "GET",
      "path": "/api/courses",
      "sourceFile": "src/api.ts",
      "source": "fetch"
    }
  ]
}
```

`run.json` schema:

```json
{
  "kind": "frontend",
  "install": "npm install",
  "dev": "npm run dev",
  "port": 5173,
  "env": {
    "API_BASE_URL": "http://localhost:8000"
  }
}
```

可 repair:

- 补 `README.md`。
- 补 `manifest/` 目录。
- 从 `fetch` / `axios` 调用提取 `api-usages.json`。
- 补 `run.json`，前提是启动命令能从已存在文件判断。

不可 repair:

- 没有前端入口。
- 没有任何可识别 API 调用，且该项目需求明确需要 API。
- 缺少可运行依赖描述，且无法从文件判断技术栈。

失败分类:

- 缺启动入口 -> `generation_invalid`
- 无法提取 API usage -> `contract_parse_error`

### 6.4 Backend Harness

Artifact:

- `backend/`

必需文件:

- `backend/README.md`
- `backend/package.json` / `backend/requirements.txt` / 后续选定技术栈等价文件
- 后端入口文件，例如 `backend/src/server.*` / `backend/app.py`
- `backend/manifest/routes.json`
- `backend/manifest/run.json`

`routes.json` schema:

```json
{
  "routes": [
    {
      "method": "GET",
      "path": "/api/courses",
      "handler": "listCourses",
      "sourceFile": "src/server.ts"
    }
  ]
}
```

`run.json` schema:

```json
{
  "kind": "backend",
  "install": "npm install",
  "dev": "npm run dev",
  "port": 8000,
  "health": "GET /health"
}
```

可 repair:

- 补 `README.md`。
- 补 `manifest/` 目录。
- 从路由定义提取 `routes.json`。
- 补 `run.json`，前提是启动命令能从已存在文件判断。

不可 repair:

- 没有后端入口。
- 没有任何路由定义。
- 没有健康检查且无法确定服务是否启动。

失败分类:

- 缺启动入口 -> `generation_invalid`
- 无法提取 routes -> `contract_parse_error`

### 6.5 QA Harness

Artifact:

- `qa_report.md`

必需章节:

- 测试范围
- 测试用例
- API 契约验证
- 冲突处理验证
- 风险与结论

可提取 manifest:

```text
test_case_manifest {
  test_cases: [
    { id, title, type, status }
  ]
}
```

可 repair:

- 补 `# QA Report - {project_name}` 标题。
- 标准化测试用例编号。
- 如果 `force_pass` 发生，确保风险章节存在。

不可 repair:

- 没有测试用例。
- 没有验收结论。
- 强制通过冲突后，报告完全不提风险。

失败分类:

- 缺测试用例或结论 -> `generation_invalid`

## 7. API Contract 与 Conflict 的关系

Harness 只负责用确定性规则提取 manifest，不负责判定冲突决策。

这里的 extractor 不是 Agent，也不是 LLM prompt。它是普通程序代码:

- Frontend manifest extractor: 从 generated frontend 文件中提取 `fetch` / `axios` 调用。
- Backend manifest extractor: 从 generated backend 文件中提取路由定义。
- Architect contract extractor: 从架构产物中提取或校验 `api-contract.json`。

Orchestrator 的 `ContractChecker` 消费这些 manifest，比较 Frontend API usage 与 Backend routes。它可以是编排器内部的确定性模块，但不应该被建模成一个 AI Agent。

流程:

```text
FrontendHarness -> api-usages.json
BackendHarness  -> routes.json
ArchitectHarness -> api-contract.json
Orchestrator ContractChecker
  -> compare frontend usages vs backend routes
  -> mismatch => Conflict
```

规则:

- 提取失败是 `contract_parse_error`。
- 提取成功但 FE/BE 不一致是 `Conflict`。
- Conflict 只比较 Frontend/Backend API mismatch。
- Architect contract 可作为辅助证据，不作为 v0.1 唯一冲突来源。

## 8. Retry 与 Repair 关系

Harness repair 不消耗 Agent retry。

```text
raw output
  -> repaired
  -> valid Artifact
```

只有核心内容缺失才 retry:

```text
raw output
  -> invalid_retryable
  -> AgentRun failed retryable=true
  -> new AgentRun(trigger_reason=retry)
```

Retry 不应该发生在以下情况:

- 文件名大小写可修复。
- 缺 README 外壳可修复。
- path 格式可修复。
- manifest wrapper 可从代码提取。

Retry 应该发生在以下情况:

- PM 缺功能列表。
- Architect 缺 API endpoint。
- Frontend 无启动入口。
- Backend 无路由。
- QA 无测试用例。

## 9. Harness 与 ZIP 导出

ZIP 只能使用 latest valid/repaired Artifact。

导出前检查:

- `prd.md` 存在。
- `architecture.md` 存在。
- `api-contract.json` 存在。
- `frontend/` 存在。
- `frontend/manifest/run.json` 存在。
- `backend/` 存在。
- `backend/manifest/run.json` 存在。
- `qa_report.md` 存在。

如果缺失:

- 不允许下载 ZIP。
- 进入 `artifact_io` 或 `generation_invalid`，取决于缺失原因。

## 10. v0.1 最小实现顺序

建议按这个顺序实现 harness:

1. 通用路径安全和文件名规范化。
2. 通用 HarnessResult 和 HarnessReport。
3. PM / Architect / QA Markdown 章节校验。
4. API contract schema。
5. Frontend deterministic manifest extractor。
6. Backend deterministic manifest extractor。
7. Frontend/Backend run manifest。
8. ZIP preflight 检查。

## 11. 已确认决策与待确认问题

### 11.1 已确认

1. generated `frontend/` / `backend/` 的具体技术栈还未确定，因此 `run.json` 的命令先作为抽象契约。该选型是产物模板选择，不是多 Agent Runtime 选型。
2. Deterministic manifest extractor v0.1 先做字符串/正则级，后续可升级 AST。
3. Harness v0.1 先作为确定性静态质量门，负责文件结构、启动入口、run manifest、API manifest 和 ZIP preflight。

### 11.2 待确认

1. 是否在 ZIP 导出前自动执行 generated app 的 `install/dev/health` smoke test。当前建议: 第一版先保证产物模板可手动运行，最终面试交付前再补自动 smoke。
