# AI Software Company 多Agent协作平台 - 需求澄清 v0.1

> 依据: `output/pdf/ai-software-company-multi-agent-platform.md`
>
> 本文档用于定义第一版交付给用户验收的 MVP v0.1。该 MVP 是中间迭代稿，不是最终面试交付版；但它必须是完整可运行的工程闭环，并且从一开始保留工程题的核心考查点。

## 1. 当前结论

MVP v0.1 的目标不是做一个缩水 demo，而是做一个 **可运行、可演示、架构方向正确的第一版**。

它需要覆盖工程题的主功能面:

- 项目创建与项目详情。
- 5 个 Agent 的职责、输入、输出和状态流转。
- PM -> Architect -> Frontend/Backend 并行 -> Orchestrator 冲突检测 -> QA 的非线性协作流程。
- Mock 模式下无 LLM Key 完整跑通。
- 可选制造 API 冲突，并通过人类 CTO 决策继续流程。
- Agent 产物可查看，最终可打包下载。
- 下载后的 generated `frontend/` 和 `backend/` 必须可以单独运行。

MVP v0.1 可以轻量实现的部分:

- Agent 输出先以模板化 Mock 为主，但模板必须合理、动态、可解释。
- 冲突检测先做字符串级 API 比对。
- 人类审核先做“查看 + 通过”，产物在线编辑作为预留能力。
- LLM 模式先做 OpenAI-compatible adapter 接口与配置入口，真实效果不作为 v0.1 的唯一验收路径。

## 2. 产品目标

构建一个模拟软件公司协作的全栈平台。用户作为“人类 CTO”，输入产品需求后，系统自动编排多个 AI Agent，从需求分析、架构设计、前后端实现、冲突检测到 QA 报告，完成一个从 0 到 1 的软件项目交付流程。

面试官视角下，平台重点展示:

- 工程功能取舍是否清晰。
- 多 Agent 编排是否有真实状态机和依赖关系。
- 并行执行与冲突处理是否落地。
- 无 LLM Key 时是否仍可稳定演示。
- `docker-compose up` 是否没有阻塞点。
- README 是否清晰说明启动、配置、Mock 模式、人类 CTO 操作路径。
- Web UI 是否能清楚展示人类 CTO 如何介入审核、冲突决策和产物下载。
- 最终产物是否能下载并独立运行。

## 3. 目标用户

### 主要用户

面试官/评审。

他们会重点观察:

- 系统能否一键跑通。
- 设计是否覆盖题目要求。
- 架构是否可解释、可扩展。
- Mock 与 LLM 是否解耦。
- 冲突检测和人工决策是否真实存在，而不是页面假展示。

### 操作角色

人类 CTO。

人类 CTO 负责:

- 创建项目并输入需求。
- 启动构建。
- 在 Agent 产物完成后进行可选审核。
- 在 API 冲突出现时选择解决方向。
- 下载最终交付物。

## 3.1 部署与自助演示要求

当前不预设固定的“5 分钟演示脚本”。验收重点是让面试官通过 README 和 Web UI 自助理解并运行系统。

必须做到:

- 根目录 `docker-compose up` 能启动完整应用，不需要额外手工拼装服务。
- README 第一屏说明最短启动路径。
- README 明确说明默认使用 Mock 模式；如需 LLM，必须显式切换到 LLM 模式并配置环境变量。
- README 明确说明如何打开 Web UI。
- Web UI 能清楚呈现人类 CTO 的操作点:
  - 创建项目。
  - 启动构建。
  - 查看 Agent 产物。
  - 通过审核点。
  - 处理 API 冲突。
  - 下载 ZIP。
- 示例项目可内置或在 README 中推荐，例如“排课系统”，但不要求固定演示脚本。

## 4. MVP v0.1 范围

### 4.1 必须实现

1. 项目管理
   - 创建项目: 项目名称、需求描述。
   - 项目列表: 展示项目、当前阶段、状态。
   - 项目详情页: 作为核心演示页面。

2. Agent 编排
   - PM Agent。
   - Architect Agent。
   - Frontend Agent。
   - Backend Agent。
   - QA Agent。
   - Orchestrator 作为系统编排与冲突检测组件。

3. 状态机
   - `created`
   - `running`
   - `awaiting_review`
   - `conflict`
   - `completed`
   - `failed`

4. 协作流程
   - Phase 1: PM Agent 生成 PRD。
   - Phase 2: Architect Agent 生成架构文档和 API 契约。
   - Phase 3: Frontend Agent 与 Backend Agent 基于 API 契约并行执行。
   - Phase 4: Orchestrator 做 API 契约一致性检查。
   - Phase 5: QA Agent 生成测试计划和验收报告。

5. Mock 模式
   - v0.1 默认选择 Mock 模式，确保无 `LLM_API_KEY` 时可完整演示。
   - Mock/LLM 必须通过明确开关切换；选择 LLM 后配置错误不能自动 fallback 到 Mock。
   - Mock 模式必须完整演示所有阶段。
   - Mock 产物必须根据项目名称和需求描述动态生成。
   - Mock 产物必须支持制造冲突与无冲突两种场景。

6. LLM 模式接口
   - 支持 OpenAI-compatible 配置入口:
     - `LLM_API_KEY`
     - `LLM_BASE_URL`
     - `LLM_MODEL`
   - Agent 执行层必须通过统一接口调用 provider，不能把 Mock 逻辑写死在状态机里。

7. 冲突制造开关
   - 启动构建时可选择是否制造 API 冲突。
   - 默认建议开启，用于演示冲突解决能力。
   - 关闭后应能跑通无冲突路径。

8. 冲突检测
   - 提取 Frontend 代码中的 `fetch` / `axios` 调用。
   - 提取 Backend 代码中的路由定义。
   - 比较 path、method、关键参数名。
   - 不一致时进入 `conflict` 状态。
   - 冲突信息需要可展示、可解释。

9. 人类 CTO 决策
   - `以前端为准`: Backend Agent 重新执行并对齐 Frontend 调用。
   - `以后端为准`: Frontend Agent 重新执行并对齐 Backend 实现。
   - `强制通过`: 忽略冲突并进入 QA 阶段。
   - 重试时保留其他 Agent 产物不变。

10. 人类 CTO 审核点
    - Agent 完成后可进入 `awaiting_review`。
    - 支持查看产物并点击“通过”。
    - v0.1 可不实现完整在线编辑器，但数据结构需要支持后续保存人工修改版本。

11. 项目详情页
    - 顶部: 项目标题、状态标签、开始构建按钮。
    - Pipeline: 可视化显示 Agent 节点、依赖关系和当前状态。
    - 产物查看区: 点击 Agent 节点切换 PRD、架构、前端代码、后端代码、QA 报告。
    - 冲突解决区: 仅 `conflict` 状态显示。
    - 执行日志流: 时间倒序，可折叠。

12. 产物下载
    - 支持下载 ZIP。
    - ZIP 至少包含:
      - `prd.md`
      - `architecture.md`
      - `frontend/`
      - `backend/`
      - `qa_report.md`
    - generated `frontend/` 与 `backend/` 下载后必须可以单独运行。
    - 必须通过确定性 harness 校验和补齐固定文件，不能只依赖 Agent prompt 保证文件名、章节和启动入口正确。

13. 一键启动
    - 根目录提供 `docker-compose.yml`。
    - README 中说明 `docker-compose up` 启动方式。

### 4.2 v0.1 明确不做或轻量做

| 能力 | v0.1 处理方式 | 后续扩展 |
| --- | --- | --- |
| 多用户/权限 | 不做 | 最终如需要可加登录和项目归属 |
| 分布式任务队列 | 不做，先同进程 async/job runner | 后续替换为 worker/queue |
| 复杂 LLM prompt 优化 | 不作为主验收路径 | 后续增强真实 LLM 输出质量 |
| 产物在线编辑器 | 先预留数据模型，不做复杂编辑体验 | 后续支持编辑、diff、版本 |
| AST 级冲突检测 | 先字符串/正则级 | 后续升级 AST/OpenAPI diff |
| 自动运行生成代码测试 | v0.1 至少保证下载后可手动运行 | 后续可加入沙箱执行和自动验证 |
| 多模型 provider | 只保留统一接口 | 后续接入多 provider |

## 5. Mock 模式的设计要求

Mock 不是临时兜底，而是核心设计路径。它会影响 Agent 接口、状态机、产物结构和验收方式。

关键原则:

- 允许 Mock 内容模板化，不允许 Mock 绕过真实编排链路。
- 允许真实 LLM 路径在 v0.1 轻量，不允许 Mock 和 LLM 使用两套 Agent 数据结构。
- 允许冲突样例固定，不允许冲突状态由 UI 假展示替代。
- 允许 generated 项目简单，不允许下载后缺启动入口。

### 5.1 Provider 抽象

Agent 不直接依赖 LLM SDK，而是依赖统一的 `AgentProvider`:

```text
AgentRunner
  -> AgentProvider
       -> MockProvider
       -> OpenAICompatibleProvider
```

Provider 输入必须包含:

- project name
- requirement text
- previous artifacts
- API contract
- scenario flags，例如 `force_api_conflict`
- alignment instruction，例如 `align_to_frontend` / `align_to_backend`

Provider 输出必须包含:

- artifact content
- structured metadata
- logs
- extracted API usage or route manifest if applicable

### 5.2 Mock 输出要求

Mock 输出不能是固定假文本。它至少要做到:

- 根据项目名称生成 PRD 标题和功能列表。
- 根据需求关键词生成基础模块。
- Architect 输出架构说明、数据库模型、API 契约。
- Frontend 输出可运行前端项目。
- Backend 输出可运行后端项目。
- QA 输出覆盖主流程、API 契约、冲突解决路径的测试计划。

Mock 输出也必须经过同一套 ArtifactHarness:

- PM harness 确保 `prd.md` 和固定章节存在。
- Architect harness 确保 `architecture.md` 与 API contract 存在。
- Frontend harness 确保 `frontend/` 有启动入口和 API usage manifest。
- Backend harness 确保 `backend/` 有启动入口和 route manifest。
- QA harness 确保 `qa_report.md` 覆盖测试用例、验收结论和风险。

### 5.3 冲突制造方式

冲突制造应通过场景参数控制，而不是硬编码页面状态。

示例:

```text
force_api_conflict=true

Architect contract:
  GET /api/courses

Frontend mock:
  fetch("/api/courses", { method: "GET" })

Backend mock:
  POST /api/course
```

Orchestrator 必须通过真实检测逻辑发现冲突，而不是因为开关打开就直接进入 `conflict`。

### 5.4 下载后单独运行要求

generated `frontend/` 和 `backend/` 需要满足:

- 有各自的 `README.md` 或启动说明。
- 有明确依赖文件，例如 `package.json`、`requirements.txt` 或等价配置。
- 默认端口不冲突。
- 前端 API base URL 可配置。
- 后端提供健康检查或最小可验证接口。
- Mock 生成的前端调用与后端路由在冲突修复后应一致。

## 6. Agent 输入输出边界

| Agent | 输入 | 输出 | v0.1 验收 |
| --- | --- | --- | --- |
| PM | 项目名称、需求描述 | `prd.md` | 包含目标、用户故事、功能列表、验收标准 |
| Architect | PRD | `architecture.md`、API 契约 | 包含架构、数据模型、OpenAPI 风格接口 |
| Frontend | PRD、API 契约 | `frontend/` | 可单独运行，包含页面和 API 调用 |
| Backend | PRD、API 契约 | `backend/` | 可单独运行，包含路由实现 |
| QA | PRD、架构、前后端产物、冲突决策记录 | `qa_report.md` | 包含测试用例、验收报告、风险 |
| Orchestrator | 项目状态、Agent 产物、配置 | 状态流转、冲突报告、日志 | 能真实推进流程和处理冲突 |

## 7. 项目详情页信息架构

项目详情页是面试展示的核心页面。

必须让面试官一眼看到:

- 当前项目处于哪个阶段。
- 哪些 Agent 已完成、运行中、等待审核、冲突或失败。
- Frontend/Backend 是否并行执行。
- 冲突点是什么。
- 人类 CTO 做了什么决策。
- 最终产物在哪里查看和下载。

建议页面区域:

1. 顶部操作栏
   - 项目标题。
   - 全局状态。
   - Mock/LLM 模式标识。
   - `force_api_conflict` 标识。
   - 开始构建 / 下载 ZIP。

2. Pipeline 区
   - PM、Architect、Frontend、Backend、Orchestrator、QA 节点。
   - 节点状态色。
   - Frontend 与 Backend 并行分支。
   - 点击节点切换产物。

3. Artifact 区
   - Markdown 渲染。
   - 代码高亮。
   - 文件树。

4. Conflict 区
   - 只在 `conflict` 状态出现。
   - 展示 Frontend 调用、Backend 路由、差异原因。
   - 展示三个决策按钮。

5. Review 区
   - 只在 `awaiting_review` 状态出现。
   - 展示当前待审核 Agent。
   - 提供通过按钮。

6. Logs 区
   - 时间倒序。
   - 记录 Agent 开始、完成、失败、冲突检测、人工决策、重试。

## 8. 与工程题范围的覆盖对照

### 8.1 覆盖结论

v0.1 在 **需求范围层面包含工程题主干**，但不是“最终完成度完全等价”。更准确地说:

- Must 主链路: 包含。
- Mock 无 Key 演示: 必须完整实现。
- 冲突检测与人工决策: 必须真实实现。
- ZIP 下载: 必须真实实现。
- generated `frontend/` / `backend/` 可单独运行: 作为本项目增强验收项，必须真实实现。
- LLM 真接入质量: v0.1 只要求配置入口、provider adapter、错误提示和可替换路径，不作为主验收路径。
- 人类 CTO 产物编辑: v0.1 只要求状态和数据模型预留，完整编辑器后续实现。

因此，回答“是否完全包含工程题范围”时，需要区分两层:

1. **功能面是否包含**: 基本包含，且额外增加“下载后 generated 前后端可单独运行”。
2. **实现深度是否完全等价最终交付**: 不完全，LLM 真实效果和产物在线编辑是明确轻量/预留项。

| 工程题要求 | v0.1 覆盖状态 | 说明 |
| --- | --- | --- |
| 模拟真实软件公司运作的全栈平台 | full | 项目、Agent、产物、下载闭环都覆盖 |
| 用户作为人类 CTO 输入需求 | full | 创建项目输入名称和需求 |
| 自动协调 5 个 AI Agent | full | 5 个 Agent 都进入状态机和产物链路 |
| 非线性协作模式 | full | Frontend/Backend 并行，Orchestrator 汇合 |
| Agent 并行工作 | full | v0.1 至少在流程模型和执行日志中体现并行；实现可用 async/job runner |
| 存在依赖关系 | full | PM -> Architect -> FE/BE -> QA |
| 冲突需要协调 | full | conflict 状态和人工决策覆盖 |
| PM Agent PRD | full | `prd.md` |
| Architect 架构、数据库模型、API 契约 | full | `architecture.md` + 结构化 API contract |
| Frontend 生成前端页面代码 | full | `frontend/`，且需可单独运行 |
| Backend 生成 API 实现代码 | full | `backend/`，且需可单独运行 |
| QA 测试计划和验收报告 | full | `qa_report.md` |
| 契约一致性检查 | full | 字符串级 API 比对 |
| 冲突点高亮展示 | full | Conflict 区展示差异 |
| 以前端为准 | full | Backend 重跑并对齐 |
| 以后端为准 | full | Frontend 重跑并对齐 |
| 强制通过 | full | 直接进入 QA |
| 重试后保留其他产物不变 | full | 状态机与 artifact 版本需要支持 |
| 人类审核点 | light | v0.1 做查看 + 通过；在线编辑预留 |
| 创建项目 | full | 项目管理基础能力 |
| 项目列表 | full | 展示状态 |
| 项目详情页指定区域 | full | Pipeline、Artifact、Conflict、Logs |
| ZIP 下载 | full | 包含题目要求文件 |
| OpenAI-compatible LLM 模式 | light | 配置和 adapter 入口必须有；真实质量不作为主路径 |
| Mock 模式必须 | full | v0.1 核心路径 |
| 无 LLM 完整演示冲突解决 | full | 通过 Mock + 冲突制造开关 |
| 示例需求演示 | full | README 或 seed 示例包含排课系统 |
| 完整源码 | full | 最终仓库交付 |
| `docker-compose.yml` 一键启动 | full | 根目录提供 |
| README 架构说明 | full | 必须包含编排和冲突机制 |
| README 本地开发步骤 | full | 必须包含 |
| README 环境变量说明 | full | 必须包含 |
| README Mock 模式说明 | full | 必须包含 |

### 差距判断

如果按上表执行，v0.1 对工程题范围是 **主功能完全包含，少量加分/体验项轻量实现**。

唯一需要明确标注的非 full 项:

- 人类 CTO “直接修改产物内容后通过”: v0.1 暂不做完整编辑器，但保留 artifact revision 数据模型。
- LLM 模式: v0.1 保留 OpenAI-compatible adapter、环境变量路径、调用错误提示和替换点；主验收路径仍是 Mock。
- 模式切换: Mock/LLM 必须显式选择。默认 Mock 用于无 Key 演示；显式 LLM 配置错误时应失败并提示，不允许自动 fallback。

这些点不影响工程题主线，因为原题将人类审核点标为“可选实现，加分项”，而 Mock 模式反而是必须项；明确模式开关是为了避免 LLM 配置错误时静默降级，提升可解释性。

### 8.2 容易漏掉的硬验收点

- 默认启动路径必须选择 Mock 模式，保证未配置 `LLM_API_KEY` 也可演示。
- LLM 模式必须显式开启；配置错误不得静默 fallback。
- Mock 输出必须带项目名称和需求关键词，不应是完全固定的空壳文本。
- 冲突态必须由 Orchestrator 的检测结果触发，而不是 UI 写死。
- 冲突决策后只能重跑被对齐的一侧，其他 Agent 产物需要保持不变。
- 项目详情页需要区分 Markdown 渲染和代码高亮。
- 执行日志需要时间倒序、可折叠。
- README 必须覆盖架构说明、本地开发步骤、环境变量说明、Mock 使用说明。
- ZIP 内容清单固定包含 `prd.md`、`architecture.md`、`frontend/`、`backend/`、`qa_report.md`。
- generated `frontend/` 和 `backend/` 虽然是增强要求，但在本项目 v0.1 中必须作为验收项执行。

## 9. 验收标准

### 9.1 主流程验收

1. 启动系统。
2. 创建项目，例如“设计并实现一个排课系统”。
3. 选择 Mock 模式。
4. 开启冲突制造。
5. 点击开始构建。
6. PM 生成 PRD。
7. Architect 生成架构和 API 契约。
8. Frontend 与 Backend 并行生成。
9. Orchestrator 检测出 API 冲突。
10. 页面展示冲突点。
11. 人类 CTO 选择“以前端为准”或“以后端为准”。
12. 对应 Agent 重跑。
13. Orchestrator 再次检测通过。
14. QA 生成报告。
15. 下载 ZIP。
16. 分别启动 ZIP 中的 generated `frontend/` 和 `backend/`，确认可以运行。

### 9.2 无冲突路径验收

1. 创建项目。
2. 关闭冲突制造。
3. 构建流程应直接从 Orchestrator 进入 QA。
4. 下载产物可运行。

### 9.3 无 LLM Key 验收

1. 不设置 `LLM_API_KEY`。
2. 系统默认处于 Mock 模式，或用户明确选择 Mock 模式。
3. 全流程可跑通。
4. README 能说明如何在无 Key 情况下演示冲突解决。

## 10. 后续迭代方向

v0.1 之后，最终面试交付版重点打磨:

- README 和架构图。
- 演示脚本。
- UI 观感和状态反馈。
- Mock 产物质量。
- 真实 LLM 调用体验。
- 更稳健的 API diff。
- 产物版本、编辑和 diff。
- 自动验证 generated 项目是否可运行。

## 11. 已确认决策与待确认问题

### 11.1 已确认

1. v0.1 采用单仓应用 + Docker Compose 作为交付形态。
2. 平台持久化采用 SQLite + 本地 artifact store，不引入独立 DB/Queue 服务。
3. Agent Runtime 使用自研轻量 Orchestrator Runtime，不把 LangGraph/CrewAI/AutoGen 作为核心 runtime。
4. Mock/LLM 必须显式切换；默认 Mock；LLM 配置错误不能 fallback。
5. generated `frontend/` / `backend/` 不需要和主应用技术栈一致。
6. LLM adapter 需要保留真实 OpenAI-compatible 调用路径和明确错误提示，但 v0.1 主验收路径不依赖真实 LLM Key。

### 11.2 待确认

1. 主应用具体技术栈选择。
2. generated `frontend/` / `backend/` 的模板技术栈。
3. ZIP 导出前是否自动执行 generated app smoke test。当前建议: 第一版先静态 gate + 手动运行验收，最终面试交付前再补自动 smoke。
