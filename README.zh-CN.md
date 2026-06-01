# AI Software Company MVP v0.1

面向工程面试题的多 Agent 协作平台。默认使用 Mock 模式，因此下载后不需要任何 LLM Key 就可以完整演示。

English version: [README.md](./README.md)

## 评估许可说明

本仓库仅用于招聘/面试评估，不是开源项目，也不授权用于商业使用、产品使用、内部工具复用、再分发、模型训练或评估流程以外的衍生开发。

完整条款见 [LICENSE-EVALUATION.md](./LICENSE-EVALUATION.md)。

## 面试官阅读入口

建议从 [SUBMISSION.md](./SUBMISSION.md) 开始看，它说明了推荐验收路径、已实现范围和评估版本边界。

生产级 Agent 工具能力，例如沙箱 Shell、浏览器自动化、包安装、浏览器级生成应用 QA、自动修复循环等，已作为明确扩展点记录在 [docs/production-extension-points.md](./docs/production-extension-points.md)。本版本保留这些工程边界，但不把它们做成可直接复用的生产平台。

## 启动

推荐使用 Docker Compose：

```bash
docker-compose up --build
```

打开：

```text
http://127.0.0.1:3000
```

也可以本地 Python 启动：

```bash
python3 app/server.py --port 3000
```

## 目录结构

```text
app/
  server.py              # Python 标准库实现的 API server、编排器、provider、harness、导出逻辑
  static/                # 面向 Human CTO 的 Web UI
docs/
  production-extension-points.md
  assignment-gap-analysis.md
output/
  requirements/          # 需求澄清和架构设计记录
  pdf/                   # 原 PDF 解析后的 Markdown、页面和架构图引用
  prototypes/            # 早期静态 UI 原型
  reports/               # MVP 验证报告
tests/
  e2e/                   # Playwright 流程和响应式布局测试
  unit/                  # ContractChecker 单元测试
```

## 架构概览

平台把编排状态放在模型之外。PM、Architect、Frontend、Backend、QA 都被建模为同一个 `BuildRun` 内的 `AgentRun` attempt。每个成功的 AgentRun 会产出一个 `Artifact`，但 provider 的原始输出必须先经过 `ArtifactHarness` 校验、修复、规范化和 manifest 提取，之后才会成为有效 artifact。

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

核心实体：

- `Project`：用户侧项目容器，包含当前状态和 active BuildRun。
- `BuildRun`：一次完整构建会话；Agent retry、harness repair、冲突解决和审核都发生在同一个 BuildRun 内。
- `AgentRun`：某个角色的一次 attempt，包含 `attempt_no`、`trigger_reason`、输入/输出 artifact、retry 关系，以及可选 conflict 关联。
- `Artifact`：版本化产物，包含 manifest 和 harness report。
- `Conflict`：Frontend/Backend API mismatch 的业务状态，不是 failed 状态。
- `ReviewGate`：Human CTO 审核点。
- `LogEvent`：追加式运行证据。

## API Contract 边界

v0.1 使用 `api-contract.json` 作为平台内部的紧凑 JSON contract，不是完整 OpenAPI 文档。当前 ContractChecker 只需要对比 Frontend usages 和 Backend routes 的 method、path、request keys，因此这个格式足够支撑 MVP 的 API mismatch 检测。

完整 OpenAPI schema 生成、校验，以及更强的 AST 级提取，被明确保留为生产级扩展点，不属于 v0.1 直接交付范围。

## Agent 编排流程

当前实现的主流程：

1. PM Agent 生成 `prd.md`。
2. Architect Agent 生成 `architecture.md` 和 `api-contract.json`。
3. 如果开启 `human_review_required`，BuildRun 暂停等待 Human CTO 审核。
4. Frontend 和 Backend AgentRun 并行执行。
5. 如果开启 `force_api_conflict` 且生成产物本身没有 mismatch，ConflictScenarioHarness 会确定性改写最新 Frontend artifact，制造一个可审计的 API mismatch。
6. ContractChecker 对比 Frontend API usages 和 Backend routes。
7. 如果存在 mismatch，项目进入 `conflict`，等待 Human CTO 决策。
8. Conflict 决策：
   - `以前端为准`：重跑 Backend Agent，使用 `alignment_mode=align_to_frontend`。
   - `以后端为准`：重跑 Frontend Agent，使用 `alignment_mode=align_to_backend`。
   - `强制通过`：跳过重跑，继续进入 QA。
9. RuntimeHarness 在 QA 前启动最新 generated frontend/backend。
10. QA Agent 生成 `qa_report.md`。
11. ZIP 导出会打包最新有效产物。

可重试失败会在同一个 BuildRun 内创建新的 AgentRun attempt；只有 retry 耗尽后 BuildRun 才会进入 failed。

## Conflict 检测

ArtifactHarness 会提取：

- Frontend 代码中的 `fetch(...)` / `axios(...)` 调用，以及请求字段注释/schema hints。
- Backend 代码中的 route 声明和 route schema hints。

ContractChecker 对比 method、path 和 request keys。发现 mismatch 后，Human CTO 决策面板会显示结构化冲突行，并高亮冲突项。解决后的 conflict 会保留原始 Frontend/Backend attempt，并在需要重跑时记录对应的 resolution AgentRun。

冲突演示开关由平台控制，不依赖 LLM “自觉”生成错误。需要制造冲突时，ConflictScenarioHarness 会创建新的 frontend artifact 版本，并在 harness report 中记录改写证据。

## 演示路径

1. 打开 Web UI。
2. 使用预填项目，或修改项目名和需求描述。
3. 保持 `Provider=Mock`。
4. 保持 `force_api_conflict` 开启，用于演示 Human CTO 冲突处理。
5. 点击 `创建 Project`。
6. 点击 `Start BuildRun`。
7. 如果出现审核点，点击 `通过审核`。
8. 处理 API conflict：
   - `以前端为准`：重跑 Backend Agent。
   - `以后端为准`：重跑 Frontend Agent。
   - `强制通过`：不重跑，直接进入 QA。
9. BuildRun 到达 `completed` 后下载 ZIP。

## MVP v0.1 覆盖范围

- Project 创建。
- BuildRun 作为完整构建会话。
- PM、Architect、Frontend、Backend、QA 的 AgentRun attempts。
- 默认完整可跑的 MockProvider。
- 显式 Mock/LLM provider 切换。LLM 模式使用 OpenAI-compatible chat completions endpoint；缺少必需环境变量时会以 `provider_config` 明确失败，不会静默 fallback 到 Mock。
- ArtifactHarness：必需文件检查、确定性 repair、manifest 提取、harness report。
- ConflictScenarioHarness：在演示开关开启时确定性注入 API mismatch。
- Frontend/Backend API ContractChecker。
- RuntimeHarness：QA 前启动 generated frontend/backend，记录 `runtime_report`。
- Conflict 作为业务状态，而不是 failed 状态。
- 可重试 AgentRun 失败会在同一个 BuildRun 内创建新 attempt。
- Human CTO review gate 和 conflict decision。
- SQLite metadata state。
- 本地文件系统 artifact store。
- ZIP 导出，包含 `prd.md`、`architecture.md`、`api-contract.json`、`frontend/`、`backend/`、`runtime_report` 和 `qa_report.md`。

PDF 原始要求到当前实现的对照见 [docs/assignment-gap-analysis.md](./docs/assignment-gap-analysis.md)。

## 数据目录

运行时状态保存在：

```text
data/
  app.db
  artifacts/
  exports/
```

删除 `data/` 可以重置本地状态。

## LLM 模式

Web UI 可以显式选择 LLM 模式。需要配置：

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://openai-compatible-host/v1
LLM_MODEL=...
```

已验证过的 DeepSeek 示例：

```bash
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

配置后，平台会调用 `${LLM_BASE_URL}/chat/completions`，并期待模型返回形如 `{"files": {"relative/path": "content"}}` 的 JSON。选择 LLM 但缺少配置时，BuildRun 会以 `provider_config` 阻塞失败，不会自动切回 Mock。

LLM 模式不会给模型任意工具权限。v0.1 只暴露平台控制的最小工具边界：`read_context`、`propose_files`、`run_harness`、`run_conflict_scenario`、`run_contract_check`、`run_runtime_harness`、`export_artifacts`。Shell、浏览器、包安装、仓库访问、自动修复工具等都是生产扩展点，不属于此评估版本的直接交付范围。

## E2E 测试

Playwright specs 位于 `tests/e2e`。安装 npm 依赖和 Chromium 后运行：

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

默认测试目标是 `http://127.0.0.1:3000`。可以设置 `PLAYWRIGHT_BASE_URL` 指向其他已启动服务。未设置时，Playwright config 会用临时 `DATA_DIR` 自动启动 `python3 app/server.py --port 3000`。

## 本地开发检查

```bash
python3 -m py_compile app/server.py
node --check app/static/app.js
node --check tests/e2e/mvp-flow.spec.js
python3 -m unittest tests.unit.test_contract_checker
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 npm run test:e2e
```

Playwright 覆盖 Mock 模式、LLM 缺配置阻塞、conflict resolution、ZIP export、artifact evidence、最小 toolset 边界，以及 desktop/tablet/mobile 的 overflow 检查。
