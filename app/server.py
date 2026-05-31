#!/usr/bin/env python3
import argparse
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "app" / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT_DIR / "data")).resolve()
DB_PATH = DATA_DIR / "app.db"
ARTIFACT_DIR = DATA_DIR / "artifacts"
EXPORT_DIR = DATA_DIR / "exports"

ROLES = ["pm", "architect", "frontend", "backend", "qa"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def json_loads(value, default=None):
    if value is None or value == "":
        return default
    return json.loads(value)


def ensure_safe_path(path):
    clean = Path(path)
    if clean.is_absolute() or ".." in clean.parts:
        raise ValueError(f"unsafe artifact path: {path}")
    return str(clean).replace("\\", "/")


def llm_config_status():
    required = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]
    missing = [key for key in required if not os.environ.get(key)]
    return {
        "configured": not missing,
        "missing": missing,
        "fields": {
            "LLM_API_KEY": bool(os.environ.get("LLM_API_KEY")),
            "LLM_BASE_URL": os.environ.get("LLM_BASE_URL") or "",
            "LLM_MODEL": os.environ.get("LLM_MODEL") or "",
        },
    }


def preview(files):
    chunks = []
    for path, content in files.items():
        if isinstance(content, str):
            chunks.append(f"## {path}\n{content[:900]}")
        if len("\n\n".join(chunks)) > 1800:
            break
    return "\n\n".join(chunks)[:1800]


MAX_RETRIES_BY_CATEGORY = {
    "provider_transient": 2,
    "generation_invalid": 1,
    "artifact_io": 1,
    "contract_parse_error": 1,
    "runtime_validation": 0,
}

MINIMAL_AGENT_TOOLSET = [
    {
        "name": "read_context",
        "owner": "platform",
        "scope": "AgentProvider prompt context",
        "description": "Expose only role-scoped project, previous artifact, alignment, and conflict context.",
    },
    {
        "name": "propose_files",
        "owner": "provider",
        "scope": "MockProvider / OpenAICompatibleProvider",
        "description": "Return a candidate file bundle with required role files.",
    },
    {
        "name": "run_harness",
        "owner": "platform",
        "scope": "ArtifactHarness",
        "description": "Validate required files, repair deterministic structure, and extract manifests.",
    },
    {
        "name": "run_conflict_scenario",
        "owner": "platform",
        "scope": "ConflictScenarioHarness",
        "description": "When enabled, deterministically inject a FE/BE API mismatch after generation instead of relying on LLM behavior.",
    },
    {
        "name": "run_contract_check",
        "owner": "platform",
        "scope": "ContractChecker",
        "description": "Compare Frontend API usages with Backend routes and create Conflict when needed.",
    },
    {
        "name": "run_runtime_harness",
        "owner": "platform",
        "scope": "RuntimeHarness",
        "description": "Before QA, start generated frontend/backend on assigned ports and record runnable smoke evidence.",
    },
    {
        "name": "export_artifacts",
        "owner": "platform",
        "scope": "ZIP export",
        "description": "Package the latest valid PM, architecture, frontend, backend, runtime, and QA artifacts.",
    },
]

PRODUCTION_TOOL_EXTENSION_POINTS = [
    "sandboxed_shell",
    "browser_automation",
    "package_install",
    "repo_checkout",
    "test_runner",
    "visual_qa",
    "multi_round_autonomous_repair",
    "worker_queue",
    "per_agent_secret_scope",
]


def toolset_status():
    return {
        "mode": "minimal_platform_owned",
        "llm_tool_calling": False,
        "implemented": MINIMAL_AGENT_TOOLSET,
        "extension_points": PRODUCTION_TOOL_EXTENSION_POINTS,
    }


class ProviderError(Exception):
    def __init__(self, message, category="unknown", retryable=False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class ProviderConfigError(ProviderError):
    def __init__(self, message):
        super().__init__(message, category="provider_config", retryable=False)


class ProviderTransientError(ProviderError):
    def __init__(self, message):
        super().__init__(message, category="provider_transient", retryable=True)


class ProviderGenerationError(ProviderError):
    def __init__(self, message):
        super().__init__(message, category="generation_invalid", retryable=True)


class AgentProvider:
    name = "base"

    def run(self, project, build_run, role, previous, alignment_mode="none", conflict=None, retry_hint=None):
        raise NotImplementedError


class Repository:
    def __init__(self, db_path):
        self.db_path = db_path
        self._local = threading.local()
        self.init()

    def conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn = conn
        return conn

    def init(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  requirement TEXT NOT NULL,
                  status TEXT NOT NULL,
                  active_build_run_id TEXT,
                  provider_mode_preference TEXT NOT NULL DEFAULT 'mock',
                  force_api_conflict INTEGER NOT NULL DEFAULT 1,
                  human_review_required INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS build_runs (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  parent_build_run_id TEXT,
                  context_policy TEXT NOT NULL DEFAULT 'fresh',
                  status TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  provider_mode_actual TEXT NOT NULL,
                  force_api_conflict INTEGER NOT NULL,
                  human_review_required INTEGER NOT NULL,
                  failure_category TEXT,
                  started_at TEXT NOT NULL,
                  completed_at TEXT,
                  failed_reason TEXT,
                  FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                  id TEXT PRIMARY KEY,
                  build_run_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  status TEXT NOT NULL,
                  attempt_no INTEGER NOT NULL,
                  trigger_reason TEXT NOT NULL,
                  provider_mode TEXT NOT NULL,
                  input_artifact_ids TEXT NOT NULL DEFAULT '[]',
                  output_artifact_ids TEXT NOT NULL DEFAULT '[]',
                  alignment_mode TEXT NOT NULL DEFAULT 'none',
                  failure_category TEXT,
                  retryable INTEGER NOT NULL DEFAULT 0,
                  retry_of_agent_run_id TEXT,
                  resolves_conflict_id TEXT,
                  started_at TEXT,
                  completed_at TEXT,
                  failed_reason TEXT,
                  FOREIGN KEY(build_run_id) REFERENCES build_runs(id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  build_run_id TEXT NOT NULL,
                  agent_run_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  path TEXT NOT NULL,
                  content_preview TEXT,
                  version INTEGER NOT NULL,
                  manifest_json TEXT NOT NULL DEFAULT '{}',
                  harness_report_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(project_id) REFERENCES projects(id),
                  FOREIGN KEY(build_run_id) REFERENCES build_runs(id),
                  FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id)
                );

                CREATE TABLE IF NOT EXISTS conflicts (
                  id TEXT PRIMARY KEY,
                  build_run_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  frontend_agent_run_id TEXT NOT NULL,
                  backend_agent_run_id TEXT NOT NULL,
                  frontend_api_usages TEXT NOT NULL,
                  backend_routes TEXT NOT NULL,
                  mismatches TEXT NOT NULL,
                  decision TEXT,
                  resolution_agent_run_id TEXT,
                  resolved_by TEXT,
                  created_at TEXT NOT NULL,
                  resolved_at TEXT,
                  FOREIGN KEY(build_run_id) REFERENCES build_runs(id)
                );

                CREATE TABLE IF NOT EXISTS review_gates (
                  id TEXT PRIMARY KEY,
                  build_run_id TEXT NOT NULL,
                  agent_run_id TEXT,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  resolved_at TEXT,
                  FOREIGN KEY(build_run_id) REFERENCES build_runs(id)
                );

                CREATE TABLE IF NOT EXISTS log_events (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  build_run_id TEXT,
                  agent_run_id TEXT,
                  level TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  message TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def rows(self, query, args=()):
        return [dict(row) for row in self.conn().execute(query, args).fetchall()]

    def row(self, query, args=()):
        row = self.conn().execute(query, args).fetchone()
        return dict(row) if row else None

    def execute(self, query, args=()):
        conn = self.conn()
        conn.execute(query, args)
        conn.commit()

    def insert(self, table, data):
        keys = list(data.keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})"
        self.execute(sql, [data[key] for key in keys])

    def update(self, table, row_id, data):
        keys = list(data.keys())
        sets = ", ".join([f"{key}=?" for key in keys])
        self.execute(f"UPDATE {table} SET {sets} WHERE id=?", [data[key] for key in keys] + [row_id])


repo = Repository(DB_PATH)


class ArtifactStore:
    def write_bundle(self, project_id, build_run_id, agent_run_id, files, manifests, report):
        root = ARTIFACT_DIR / project_id / build_run_id / agent_run_id
        normalized = root / "normalized"
        manifests_dir = root / "manifests"
        if root.exists():
            shutil.rmtree(root)
        normalized.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in files.items():
            safe = ensure_safe_path(rel_path)
            target = normalized / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        for name, payload in manifests.items():
            (manifests_dir / f"{name}.json").write_text(json_dumps(payload), encoding="utf-8")
        (root / "harness-report.json").write_text(json_dumps(report), encoding="utf-8")
        return str(normalized.relative_to(DATA_DIR))

    def list_files(self, artifact):
        root = DATA_DIR / artifact["path"]
        artifact_root = root.parent
        files = []
        if root.exists():
            for file_path in sorted(root.rglob("*")):
                if file_path.is_file():
                    files.append(str(file_path.relative_to(root)).replace("\\", "/"))
        report = artifact_root / "harness-report.json"
        if report.exists():
            files.append("_harness-report.json")
        manifests = artifact_root / "manifests"
        if manifests.exists():
            for file_path in sorted(manifests.glob("*.json")):
                files.append(f"_manifest/{file_path.name}")
        return files

    def read_file(self, artifact, rel_path):
        safe = ensure_safe_path(rel_path)
        root = DATA_DIR / artifact["path"]
        artifact_root = root.parent
        if safe == "_harness-report.json":
            return (artifact_root / "harness-report.json").read_text(encoding="utf-8")
        if safe.startswith("_manifest/"):
            name = ensure_safe_path(safe.removeprefix("_manifest/"))
            target = (artifact_root / "manifests" / name).resolve()
            manifests_root = (artifact_root / "manifests").resolve()
            if not str(target).startswith(str(manifests_root)) or not target.exists() or not target.is_file():
                raise FileNotFoundError(rel_path)
            return target.read_text(encoding="utf-8")
        target = (root / safe).resolve()
        if not str(target).startswith(str(root.resolve())) or not target.exists() or not target.is_file():
            raise FileNotFoundError(rel_path)
        return target.read_text(encoding="utf-8")

    def read_bundle_files(self, artifact):
        root = DATA_DIR / artifact["path"]
        files = {}
        if not root.exists():
            return files
        for file_path in sorted(root.rglob("*")):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(root)).replace("\\", "/")
                files[rel_path] = file_path.read_text(encoding="utf-8")
        return files


store = ArtifactStore()


class MockProvider(AgentProvider):
    name = "mock"

    def run(self, project, build_run, role, previous, alignment_mode="none", conflict=None, retry_hint=None):
        name = project["name"]
        requirement = project["requirement"]
        if role == "pm":
            return {
                "prd.md": f"""# PRD - {name}

## 产品目标
{requirement}

## 目标用户
- 业务负责人
- 内部运营团队
- 最终使用者

## 核心功能列表
1. 项目初始化与基础数据管理
2. 核心业务流程处理
3. 冲突、异常或风险提示
4. 数据查看与导出
5. 基础权限和操作记录预留

## 用户故事
- 作为业务负责人，我希望输入需求后快速看到可运行原型。
- 作为操作人员，我希望系统提示冲突并给出处理入口。
- 作为评审者，我希望看到从需求到 QA 的完整交付链路。

## 验收标准
- Mock 模式无需 LLM Key 即可完整跑通。
- Frontend/Backend 产物下载后可以独立运行。
- API mismatch 必须进入 Conflict，并由 Human CTO 决策。

## 非目标范围
- 多用户权限。
- 生产级部署。
- 复杂在线编辑器。
"""
            }
        if role == "architect":
            api_contract = {
                "endpoints": [
                    {"method": "GET", "path": "/api/courses", "summary": "List courses", "request": {}, "response": {"items": "Course[]"}},
                    {"method": "GET", "path": "/api/teachers", "summary": "List teachers", "request": {}, "response": {"items": "Teacher[]"}},
                    {"method": "GET", "path": "/api/classrooms", "summary": "List classrooms", "request": {}, "response": {"items": "Classroom[]"}},
                    {"method": "POST", "path": "/api/schedules/check-conflicts", "summary": "Check schedule conflicts", "request": {"courseId": "string", "teacherId": "string"}, "response": {"conflicts": "Conflict[]"}},
                ]
            }
            return {
                "architecture.md": f"""# Architecture - {name}

## 系统目标
把 PRD 转换为可以演示的前后端实现，并保留 Agent 编排、ArtifactHarness、ContractChecker 的证据。

## 模块边界
- Web UI: 负责输入需求、展示 pipeline、查看 artifact、处理 CTO 决策。
- API Server: 负责项目、BuildRun、Artifact、Conflict、ReviewGate 和 ZIP。
- Orchestrator Runtime: 负责 PM -> Architect -> Frontend/Backend -> Contract Check -> QA。
- ArtifactHarness: 负责确定性校验、修复结构外壳、提取 manifest。
- ContractChecker: 只比较 Frontend API usage 和 Backend route manifest。

## API Contract
| Method | Path | Summary |
| --- | --- | --- |
| GET | /api/courses | List courses |
| GET | /api/teachers | List teachers |
| GET | /api/classrooms | List classrooms |
| POST | /api/schedules/check-conflicts | Check schedule conflicts |

## 数据模型
- Course(id, name, teacherId)
- Teacher(id, name)
- Classroom(id, name, capacity)
- ScheduleSlot(id, courseId, classroomId, startsAt, endsAt)

## 部署
generated frontend 和 backend 都应包含 README 与 run manifest，下载后可独立运行。
""",
                "api-contract.json": json_dumps(api_contract),
            }
        if role == "frontend":
            return self.frontend_bundle(name, "/api/courses", "/api/schedules/check-conflicts")
        if role == "backend":
            use_frontend_paths = alignment_mode == "align_to_frontend"
            courses_path = "/api/course-list" if use_frontend_paths else "/api/courses"
            conflict_path = "/api/schedule/check" if use_frontend_paths else "/api/schedules/check-conflicts"
            return self.backend_bundle(name, courses_path, conflict_path)
        if role == "qa":
            conflict_summary = "Conflict 已由 Human CTO 决策关闭。" if conflict else "未发现 open Conflict。"
            return {
                "qa_report.md": f"""# QA Report - {name}

## 测试范围
- Project 创建与 BuildRun 启动。
- PM / Architect / Frontend / Backend / QA Agent 编排。
- ArtifactHarness 文件结构校验、manifest 提取和 ZIP preflight。
- Frontend/Backend API mismatch Conflict。
- Human CTO 决策。

## 测试用例
1. Mock 模式无 LLM Key 完整跑通。
2. `force_api_conflict=true` 时 ContractChecker 创建 open Conflict。
3. CTO 选择以前端或以后端为准后，对应 AgentRun 以 `trigger_reason=conflict_resolution` 重跑。
4. QA 完成后 ZIP 可下载。
5. generated `frontend/` 和 `backend/` 均含 README 与启动入口。

## API契约验证
{conflict_summary}

## 冲突处理验证
- Conflict 引用了产生冲突的 Frontend/Backend AgentRun。
- 决策后保留原 attempt，并生成新的 resolution attempt。

## 风险与结论
v0.1 适合展示工程题主线。真实 LLM 输出质量、AST 级 API diff、浏览器级 generated app E2E 可后续增强。
"""
            }
        raise ValueError(f"unknown role: {role}")

    def frontend_bundle(self, name, courses_path, conflict_path):
        return {
            "frontend/README.md": f"""# {name} Frontend

Static frontend generated by AI Software Company MockProvider.

## Run

```bash
python3 server.py --port 5173
```

Open http://127.0.0.1:5173

If the generated backend is running on port 8000, open:

```text
http://127.0.0.1:5173?api=http://127.0.0.1:8000
```
""",
            "frontend/server.py": """#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import argparse
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    import os
    os.chdir(root)
    ThreadingHTTPServer(("0.0.0.0", args.port), SimpleHTTPRequestHandler).serve_forever()
""",
            "frontend/index.html": f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{name}</title><script defer src="./src/app.js"></script></head>
<body>
  <h1>{name}</h1>
  <button id="load">Load courses</button>
  <button id="check">Check conflicts</button>
  <pre id="result">Ready</pre>
</body>
</html>
""",
            "frontend/src/app.js": f"""const API_BASE_URL = new URLSearchParams(location.search).get("api") || "";
const API_SCHEMAS = {{
  "{conflict_path}": ["courseId", "teacherId"]
}};

function apiUrl(path) {{
  return API_BASE_URL + path;
}}

async function listCourses() {{
  return fetch(apiUrl("{courses_path}")).then((res) => res.json());
}}

async function checkScheduleConflicts(payload) {{
  return fetch(apiUrl("{conflict_path}"), {{
    method: "POST",
    headers: {{ "content-type": "application/json" }},
    // request keys: courseId, teacherId
    body: JSON.stringify(payload)
  }}).then((res) => res.json());
}}

document.getElementById("load").onclick = async () => {{
  document.getElementById("result").textContent = JSON.stringify(await listCourses(), null, 2);
}};

document.getElementById("check").onclick = async () => {{
  document.getElementById("result").textContent = JSON.stringify(await checkScheduleConflicts({{ courseId: "c1", teacherId: "t1" }}), null, 2);
}};
""",
            "frontend/manifest/run.json": json_dumps({"type": "static", "command": "python3 server.py --port 5173", "url": "http://127.0.0.1:5173"}),
        }

    def backend_bundle(self, name, courses_path, conflict_path):
        return {
            "backend/README.md": f"""# {name} Backend

Python stdlib backend generated by AI Software Company MockProvider.

## Run

```bash
python3 server.py --port 8000
```

Health: http://127.0.0.1:8000/health
""",
            "backend/server.py": f"""#!/usr/bin/env python3
import argparse
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROUTES = [
    ("GET", "{courses_path}"),
    ("GET", "/api/teachers"),
    ("GET", "/api/classrooms"),
    ("POST", "{conflict_path}"),
]

ROUTE_SCHEMAS = {{
    ("POST", "{conflict_path}"): ["courseId", "teacherId"],
}}

class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        super().end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json({{"ok": True}})
        elif self.path == "{courses_path}":
            self.send_json({{"items": [{{"id": "c1", "name": "Math"}}]}})
        elif self.path == "/api/teachers":
            self.send_json({{"items": [{{"id": "t1", "name": "Ada"}}]}})
        elif self.path == "/api/classrooms":
            self.send_json({{"items": [{{"id": "r1", "name": "Room 101"}}]}})
        else:
            self.send_json({{"error": "not found"}}, 404)

    def do_POST(self):
        if self.path == "{conflict_path}":
            self.send_json({{"conflicts": []}})
        else:
            self.send_json({{"error": "not found"}}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
""",
            "backend/manifest/run.json": json_dumps({"type": "python-http", "command": "python3 server.py --port 8000", "health": "http://127.0.0.1:8000/health"}),
        }


class OpenAICompatibleProvider(AgentProvider):
    name = "llm"

    REQUIRED_FILES = {
        "pm": ["prd.md"],
        "architect": ["architecture.md", "api-contract.json"],
        "frontend": ["frontend/README.md", "frontend/server.py", "frontend/index.html", "frontend/src/app.js"],
        "backend": ["backend/README.md", "backend/server.py"],
        "qa": ["qa_report.md"],
    }

    def run(self, project, build_run, role, previous, alignment_mode="none", conflict=None, retry_hint=None):
        config = llm_config_status()
        if not config["configured"]:
            raise ProviderConfigError(f"LLM config missing: {', '.join(config['missing'])}")
        payload = {
            "model": os.environ["LLM_MODEL"],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an OpenAI-compatible provider for a multi-agent software delivery platform. "
                        "Return JSON only. The JSON shape must be {\"files\": {\"relative/path\": \"file content\"}}. "
                        "Do not wrap the JSON in markdown fences."
                    ),
                },
                {
                    "role": "user",
                    "content": self.prompt(project, build_run, role, previous, alignment_mode, conflict, retry_hint),
                },
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            self.endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "authorization": f"Bearer {os.environ['LLM_API_KEY']}",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")[:500]
            except Exception:
                error_body = str(exc)
            if exc.code in (408, 409, 425, 429) or exc.code >= 500:
                raise ProviderTransientError(f"LLM request failed with retryable HTTP {exc.code}: {error_body}") from exc
            if exc.code in (400, 401, 403, 404):
                raise ProviderConfigError(f"LLM request failed with HTTP {exc.code}: {error_body}") from exc
            raise ProviderError(f"LLM request failed with HTTP {exc.code}: {error_body}", category="unknown", retryable=False) from exc
        except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead, http.client.RemoteDisconnected) as exc:
            raise ProviderTransientError(f"LLM request transient failure: {exc}") from exc

        content = self.message_content(body)
        return self.parse_files(content)

    def endpoint(self):
        base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        if not base_url:
            raise ProviderConfigError("LLM_BASE_URL is missing")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def prompt(self, project, build_run, role, previous, alignment_mode, conflict, retry_hint):
        required = ", ".join(self.REQUIRED_FILES.get(role, []))
        previous_preview = "\n\n".join(
            f"## {artifact['type']} v{artifact['version']}\n{artifact.get('content_preview') or ''}"
            for artifact in previous[-5:]
        )[:5000]
        conflict_text = json_dumps(conflict) if conflict else "none"
        role_contract = self.role_contract(role)
        api_policy = self.api_policy(role, bool(build_run["force_api_conflict"]), alignment_mode)
        return f"""Project: {project['name']}

Requirement:
{project['requirement']}

Role: {role}
Required files: {required}
Alignment mode: {alignment_mode}
Force API conflict scenario: {bool(build_run['force_api_conflict'])}
Conflict context: {conflict_text}
Retry hint from previous failed attempt: {retry_hint or 'none'}

Role-specific artifact contract:
{role_contract}

API alignment policy:
{api_policy}

Previous artifacts:
{previous_preview or 'none'}

Rules:
- Return JSON only with shape {{"files": {{"path": "content"}}}}.
- Include every required file for the role.
- Use exactly the required relative paths unless the role-specific contract says otherwise.
- Generated frontend and backend must be runnable with Python stdlib only.
- Generated frontend/server.py and backend/server.py must accept `--port <number>` and bind the requested port.
- Frontend must support a configurable backend base URL, preferably via `?api=http://127.0.0.1:8000` in the browser, so runtime smoke can start FE and BE on different ports.
- Frontend must expose concrete API calls so the harness can extract usages.
- Backend must expose concrete routes so the harness can extract routes.
- Do not decide BuildRun state, Conflict state, or retry behavior; only return candidate files.
"""

    def role_contract(self, role):
        if role == "pm":
            return """Create prd.md as Markdown.
It must include these exact headings:
## 产品目标
## 目标用户
## 核心功能列表
## 用户故事
## 验收标准
## 非目标范围
Use numbered items under 核心功能列表 so the harness can extract a feature manifest."""
        if role == "architect":
            return """Create architecture.md and api-contract.json.
api-contract.json must be strict valid JSON with an endpoints array.
The api-contract.json file content must use double quotes for every key and string value.
Do not use JavaScript object literal syntax, Python dict syntax, comments, trailing commas, or markdown fences inside api-contract.json.
Each endpoint should include method, path, summary, request, and response.
Use concrete API paths such as /api/courses and /api/schedules/check-conflicts."""
        if role == "frontend":
            return """Create frontend/README.md, frontend/server.py, frontend/index.html, and frontend/src/app.js.
frontend/server.py must use argparse, accept --port, and serve frontend/ from the requested port.
frontend/src/app.js must build API URLs from a configurable base, for example:
const API_BASE_URL = new URLSearchParams(location.search).get("api") || "";
function apiUrl(path) { return API_BASE_URL + path; }
frontend/src/app.js must contain literal fetch("/api/...") or fetch(apiUrl("/api/...")) calls.
Follow the API alignment policy for the exact paths.
For POST request schema extraction, include a mapping like "/api/schedules/check-conflicts": ["courseId", "teacherId"] or "/api/schedule/check": ["courseId", "teacherId"] in JavaScript.
For the canonical non-conflict path, include concrete calls equivalent to:
fetch(apiUrl("/api/courses"))
fetch(apiUrl("/api/teachers"))
fetch(apiUrl("/api/schedules/check-conflicts"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ courseId: "c1", teacherId: "t1" }) })"""
        if role == "backend":
            return """Create backend/README.md and backend/server.py.
backend/server.py must be runnable with Python stdlib only.
backend/server.py must use argparse, accept --port, bind that exact port, and set permissive CORS headers for browser demos.
Follow the API alignment policy for the exact paths.
For route extraction, include literal tuples such as ("GET", "/api/courses") and ("POST", "/api/schedules/check-conflicts"), or the conflict-resolution paths when instructed.
For POST request schema extraction, include a mapping like ("POST", "/api/schedules/check-conflicts"): ["courseId", "teacherId"] or ("POST", "/api/schedule/check"): ["courseId", "teacherId"] in Python."""
        if role == "qa":
            return """Create qa_report.md as Markdown.
It must include these exact headings:
## 测试范围
## 测试用例
## API契约验证
## 冲突处理验证
## 风险与结论"""
        return "No additional contract."

    def api_policy(self, role, force_conflict, alignment_mode):
        canonical = (
            'Canonical API set: GET /api/courses, GET /api/teachers, '
            'POST /api/schedules/check-conflicts with request keys courseId and teacherId.'
        )
        if role == "architect":
            return f"{canonical} Put this canonical API set in api-contract.json."
        if role == "frontend":
            if force_conflict and alignment_mode == "none":
                return (
                    f"{canonical} Frontend must call this canonical API set exactly. "
                    "Do not intentionally create the mismatch yourself; the platform ConflictScenarioHarness "
                    "will inject the deterministic mismatch when the scenario switch is enabled."
                )
            return f"{canonical} Frontend must call this canonical API set exactly."
        if role == "backend":
            if force_conflict and alignment_mode == "align_to_frontend":
                return (
                    "Resolve the conflict by aligning Backend to the exact Frontend mismatch paths listed in Conflict context. "
                    "For the standard demo mismatch, expose GET /api/course-list and POST /api/schedule/check "
                    "with request keys courseId and teacherId."
                )
            return f"{canonical} Backend must expose this canonical API set exactly."
        return canonical

    def message_content(self, body):
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderGenerationError("LLM response does not contain choices[0].message.content") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return str(content)

    def parse_files(self, content):
        text = content.strip()
        fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
        if fence:
            text = fence.group(1)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderGenerationError(f"LLM response is not valid JSON: {exc}") from exc
        files = payload.get("files") if isinstance(payload, dict) else None
        if isinstance(files, list):
            files = {item.get("path"): item.get("content", "") for item in files if isinstance(item, dict)}
        if not isinstance(files, dict) or not files:
            raise ProviderGenerationError("LLM response JSON must contain a non-empty files object")
        normalized = {}
        for path, content in files.items():
            if not path:
                continue
            normalized[ensure_safe_path(path)] = content if isinstance(content, str) else json_dumps(content)
        return normalized


class ArtifactHarness:
    REQUIRED_SECTIONS = {
        "pm": ["产品目标", "目标用户", "核心功能列表", "用户故事", "验收标准", "非目标范围"],
        "qa": ["测试范围", "测试用例", "API契约验证", "冲突处理验证", "风险与结论"],
    }

    def run(self, role, project, files):
        normalized = {}
        repairs = []
        for path, content in files.items():
            safe = ensure_safe_path(path)
            canonical = self.canonical_path(role, safe)
            if canonical != safe:
                repairs.append({"id": "path_normalized", "description": f"{safe} -> {canonical}", "files_changed": [canonical]})
            normalized[canonical] = content

        errors = []
        warnings = []
        manifests = {}
        if role == "pm":
            self.require_file(normalized, "prd.md", errors)
            self.ensure_markdown_title(normalized, "prd.md", f"PRD - {project['name']}", repairs)
            self.require_sections(normalized.get("prd.md", ""), self.REQUIRED_SECTIONS["pm"], errors)
            manifests["feature_manifest"] = {"features": self.extract_numbered_items(normalized.get("prd.md", ""))}
        elif role == "architect":
            self.require_file(normalized, "architecture.md", errors)
            self.require_file(normalized, "api-contract.json", errors)
            if "api-contract.json" in normalized:
                try:
                    contract = json.loads(normalized["api-contract.json"])
                    manifests["api_contract"] = contract
                except json.JSONDecodeError as exc:
                    errors.append(f"api-contract.json is invalid JSON: {exc}")
        elif role == "frontend":
            self.require_file(normalized, "frontend/README.md", errors)
            self.require_file(normalized, "frontend/server.py", errors)
            usages = self.extract_frontend_usages(normalized)
            if not usages:
                errors.append("frontend has no extractable fetch API usages")
            manifests["api_usages"] = usages
            normalized["frontend/manifest/api-usages.json"] = json_dumps({"usages": usages})
            normalized.setdefault("frontend/manifest/run.json", json_dumps({"command": "python3 server.py --port 5173"}))
        elif role == "backend":
            self.require_file(normalized, "backend/README.md", errors)
            self.require_file(normalized, "backend/server.py", errors)
            routes = self.extract_backend_routes(normalized)
            if not routes:
                errors.append("backend has no extractable routes")
            manifests["routes"] = routes
            normalized["backend/manifest/routes.json"] = json_dumps({"routes": routes})
            normalized.setdefault("backend/manifest/run.json", json_dumps({"command": "python3 server.py --port 8000"}))
        elif role == "qa":
            self.require_file(normalized, "qa_report.md", errors)
            self.ensure_markdown_title(normalized, "qa_report.md", f"QA Report - {project['name']}", repairs)
            self.require_sections(normalized.get("qa_report.md", ""), self.REQUIRED_SECTIONS["qa"], errors)

        status = "valid"
        if repairs:
            status = "repaired"
        if errors:
            status = "invalid_retryable"
        failure_category = self.failure_category(role, errors)
        report = {
            "role": role,
            "status": status,
            "checks": [{"id": "role_contract", "status": "failed" if errors else "passed", "message": "; ".join(errors) or "ok", "severity": "error" if errors else "info"}],
            "repairs": repairs,
            "warnings": warnings,
            "manifests": [{"type": key, "item_count": len(value if isinstance(value, list) else value.get("endpoints", value.get("usages", value.get("routes", []))))} for key, value in manifests.items()],
            "retry_recommendation": "retry" if errors else "none",
            "failure_category": failure_category,
        }
        return {"status": status, "files": normalized, "manifests": manifests, "report": report, "errors": errors}

    def failure_category(self, role, errors):
        if not errors:
            return None
        has_missing_required = any(error.startswith("missing required file") for error in errors)
        if role in ("frontend", "backend") and not has_missing_required:
            return "contract_parse_error"
        return "generation_invalid"

    def canonical_path(self, role, path):
        lower = path.lower()
        if role == "pm" and lower.endswith("prd.md"):
            return "prd.md"
        if role == "architect" and lower.endswith("architecture.md"):
            return "architecture.md"
        if role == "architect" and lower.endswith("api-contract.json"):
            return "api-contract.json"
        if role == "qa" and lower in ("qa.md", "qa_report.md"):
            return "qa_report.md"
        return path

    def require_file(self, files, path, errors):
        if path not in files or not files[path].strip():
            errors.append(f"missing required file: {path}")

    def ensure_markdown_title(self, files, path, title, repairs):
        if path in files and not files[path].lstrip().startswith("# "):
            files[path] = f"# {title}\n\n{files[path]}"
            repairs.append({"id": "markdown_title_added", "description": f"Added heading to {path}", "files_changed": [path]})

    def require_sections(self, content, sections, errors):
        for section in sections:
            if f"## {section}" not in content:
                errors.append(f"missing markdown section: {section}")

    def extract_numbered_items(self, content):
        return [{"title": item.strip()} for item in re.findall(r"^\d+\.\s+(.+)$", content, flags=re.MULTILINE)]

    def extract_frontend_usages(self, files):
        usages = []
        for path, content in files.items():
            if not path.startswith("frontend/") or not path.endswith((".js", ".ts", ".tsx")):
                continue
            schema_by_path = self.extract_js_api_schemas(content)

            def add_usage(method, api_path):
                usage = {"method": method.upper(), "path": api_path, "source": path}
                request_keys = schema_by_path.get(api_path)
                if request_keys:
                    usage["request_keys"] = request_keys
                usages.append(usage)

            patterns = [
                r"fetch\(\s*(?P<quote>[\"'`])(?P<path>[^\"'`]+)(?P=quote)(?:\s*,\s*\{(?P<opts>.*?)\})?",
                r"fetch\(\s*apiUrl\(\s*(?P<quote>[\"'`])(?P<path>[^\"'`]+)(?P=quote)\s*\)(?:\s*,\s*\{(?P<opts>.*?)\})?",
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, content, flags=re.DOTALL):
                    opts = match.group("opts") or ""
                    method_match = re.search(r"method\s*:\s*[\"'`]([A-Z]+)[\"'`]", opts, flags=re.IGNORECASE)
                    add_usage(method_match.group(1) if method_match else "GET", match.group("path"))
            for method, api_path in re.findall(r"axios\.(get|post|put|patch|delete)\(\s*(?:apiUrl\(\s*)?[\"'`]([^\"'`]+)[\"'`]", content, flags=re.IGNORECASE):
                add_usage(method, api_path)
            for match in re.finditer(r"axios\(\s*\{(?P<opts>.*?)\}\s*\)", content, flags=re.DOTALL):
                opts = match.group("opts") or ""
                url_match = re.search(r"(?:url|path)\s*:\s*[\"'`]([^\"'`]+)[\"'`]", opts)
                if not url_match:
                    continue
                method_match = re.search(r"method\s*:\s*[\"'`]([A-Z]+)[\"'`]", opts, flags=re.IGNORECASE)
                add_usage(method_match.group(1) if method_match else "GET", url_match.group(1))
        return usages

    def extract_js_api_schemas(self, content):
        schemas = {}
        for api_path, keys in re.findall(r"[\"'`]([^\"'`]+)[\"'`]\s*:\s*\[([^\]]*)\]", content):
            if not api_path.startswith("/"):
                continue
            parsed = re.findall(r"[\"'`]([^\"'`]+)[\"'`]", keys)
            if parsed:
                schemas[api_path] = parsed
        return schemas

    def extract_backend_routes(self, files):
        routes = []
        content = files.get("backend/server.py", "")
        schemas = self.extract_python_route_schemas(content)
        seen = set()
        for method, path in re.findall(r"\([\"']([A-Z]+)[\"']\s*,\s*[\"']([^\"']+)[\"']\)", content):
            if (method, path) in seen:
                continue
            seen.add((method, path))
            route = {"method": method, "path": path, "source": "backend/server.py"}
            request_keys = schemas.get((method, path))
            if request_keys:
                route["request_keys"] = request_keys
            routes.append(route)
        return routes

    def extract_python_route_schemas(self, content):
        schemas = {}
        for method, api_path, keys in re.findall(r"\([\"']([A-Z]+)[\"']\s*,\s*[\"']([^\"']+)[\"']\)\s*:\s*\[([^\]]*)\]", content):
            parsed = re.findall(r"[\"']([^\"']+)[\"']", keys)
            if parsed:
                schemas[(method, api_path)] = parsed
        return schemas


class ContractChecker:
    def compare(self, frontend_usages, backend_routes):
        route_keys = {(route["method"], route["path"]) for route in backend_routes}
        usage_keys = {(usage["method"], usage["path"]) for usage in frontend_usages}
        routes_by_key = {(route["method"], route["path"]): route for route in backend_routes}
        usages_by_key = {(usage["method"], usage["path"]): usage for usage in frontend_usages}
        routes_by_path = {}
        routes_by_method = {}
        for route in backend_routes:
            routes_by_path.setdefault(route["path"], []).append(route)
            routes_by_method.setdefault(route["method"], []).append(route)
        mismatches = []
        for method, path in sorted(usage_keys & route_keys):
            usage = usages_by_key[(method, path)]
            route = routes_by_key[(method, path)]
            usage_keys_set = set(usage.get("request_keys") or [])
            route_keys_set = set(route.get("request_keys") or [])
            if usage_keys_set and route_keys_set and usage_keys_set != route_keys_set:
                mismatches.append({
                    "kind": "request_keys_mismatch",
                    "method": method,
                    "frontend": usage,
                    "backend": route,
                    "reason": "Frontend request keys do not match backend route request keys.",
                    "frontend_keys": sorted(usage_keys_set),
                    "backend_keys": sorted(route_keys_set),
                })
        for method, path in sorted(usage_keys - route_keys):
            same_path = routes_by_path.get(path, [])
            if same_path:
                mismatches.append({
                    "kind": "method_mismatch",
                    "method": method,
                    "frontend": {"method": method, "path": path},
                    "backend": same_path,
                    "reason": "Frontend calls an existing backend path with a different HTTP method.",
                })
                continue
            candidates = routes_by_method.get(method, [])
            mismatches.append({
                "kind": "frontend_usage_missing_backend_route",
                "method": method,
                "frontend": {"method": method, "path": path},
                "backend_candidates": candidates,
                "reason": "Frontend calls an API route that backend does not expose.",
            })
        return mismatches


class ConflictScenarioHarness:
    PATH_REWRITES = [
        ("/api/schedules/check-conflicts", "/api/schedule/check"),
        ("/api/courses", "/api/course-list"),
    ]

    def run(self, project, frontend_artifact):
        files = store.read_bundle_files(frontend_artifact)
        patched, changes = self.patch_frontend_files(files)
        if not changes:
            usages = json_loads(frontend_artifact["manifest_json"], {}).get("api_usages", [])
            first_usage = next((usage for usage in usages if usage.get("path", "").startswith("/")), None)
            if first_usage:
                original_path = first_usage["path"]
                injected_path = f"{original_path.rstrip('/')}-scenario-conflict"
                patched, changes = self.patch_specific_path(files, original_path, injected_path)
        if not changes:
            return None
        result = harness.run("frontend", project, patched)
        result["report"]["checks"].append({
            "id": "scenario_conflict_injection",
            "status": "passed" if result["status"] in ("valid", "repaired") else "failed",
            "message": "Injected deterministic frontend API mismatch for the force_api_conflict scenario.",
            "severity": "info",
        })
        result["report"]["repairs"].append({
            "id": "scenario_api_conflict_injected",
            "description": "Platform rewrote selected frontend API usages after generation; LLM output was not trusted to create the scenario.",
            "files_changed": sorted({change["file"] for change in changes}),
            "changes": changes,
        })
        result["report"]["scenario"] = {
            "type": "forced_frontend_api_mismatch",
            "source_artifact_id": frontend_artifact["id"],
            "changes": changes,
        }
        return result

    def patch_frontend_files(self, files):
        patched = dict(files)
        changes = []
        for path, content in files.items():
            if not path.startswith("frontend/") or path.startswith("frontend/manifest/"):
                continue
            if not path.endswith((".js", ".ts", ".tsx", ".html", ".md")):
                continue
            updated = content
            for old_path, new_path in self.PATH_REWRITES:
                count = updated.count(old_path)
                if count:
                    updated = updated.replace(old_path, new_path)
                    changes.append({"file": path, "from": old_path, "to": new_path, "count": count})
            patched[path] = updated
        return patched, changes

    def patch_specific_path(self, files, old_path, new_path):
        patched = dict(files)
        changes = []
        for path, content in files.items():
            if not path.startswith("frontend/") or path.startswith("frontend/manifest/"):
                continue
            if not path.endswith((".js", ".ts", ".tsx", ".html", ".md")):
                continue
            count = content.count(old_path)
            if not count:
                continue
            patched[path] = content.replace(old_path, new_path)
            changes.append({"file": path, "from": old_path, "to": new_path, "count": count})
        return patched, changes


class RuntimeHarness:
    def run(self, frontend_artifact, backend_artifact):
        backend_routes = json_loads(backend_artifact["manifest_json"], {}).get("routes", [])
        frontend_usages = json_loads(frontend_artifact["manifest_json"], {}).get("api_usages", [])
        checks = []
        warnings = []
        process_outputs = []
        processes = []
        backend_port = self.free_port()
        frontend_port = self.free_port()

        def add_check(check_id, status, message, owner=None, severity=None):
            item = {
                "id": check_id,
                "status": status,
                "message": message,
                "severity": severity or ("error" if status == "failed" else "info"),
            }
            if owner:
                item["owner"] = owner
            checks.append(item)

        with tempfile.TemporaryDirectory(prefix="ai-company-runtime-") as tmp:
            tmp_root = Path(tmp)
            backend_source = DATA_DIR / backend_artifact["path"] / "backend"
            frontend_source = DATA_DIR / frontend_artifact["path"] / "frontend"
            backend_dir = tmp_root / "backend"
            frontend_dir = tmp_root / "frontend"

            if not backend_source.exists():
                add_check("backend_artifact_present", "failed", "backend/ directory is missing from the latest backend artifact.", "backend")
            else:
                shutil.copytree(backend_source, backend_dir)
                add_check("backend_artifact_present", "passed", "backend/ directory copied to runtime sandbox.", "backend")

            if not frontend_source.exists():
                add_check("frontend_artifact_present", "failed", "frontend/ directory is missing from the latest frontend artifact.", "frontend")
            else:
                shutil.copytree(frontend_source, frontend_dir)
                add_check("frontend_artifact_present", "passed", "frontend/ directory copied to runtime sandbox.", "frontend")

            if self.failed(checks):
                return self.result(False, checks, warnings, process_outputs, backend_port, frontend_port, frontend_usages, backend_routes)

            backend_proc = self.start_process(backend_dir, backend_port, {"PORT": str(backend_port)})
            processes.append(("backend", backend_proc))
            if self.wait_port(backend_proc, backend_port):
                add_check("backend_process_started", "passed", f"backend/server.py accepted --port and listened on {backend_port}.", "backend")
                self.check_backend_routes(backend_routes, backend_port, add_check)
            else:
                add_check("backend_process_started", "failed", f"backend/server.py did not listen on requested port {backend_port}.", "backend")

            frontend_proc = self.start_process(
                frontend_dir,
                frontend_port,
                {
                    "PORT": str(frontend_port),
                    "BACKEND_URL": f"http://127.0.0.1:{backend_port}",
                    "API_BASE_URL": f"http://127.0.0.1:{backend_port}",
                },
            )
            processes.append(("frontend", frontend_proc))
            if self.wait_port(frontend_proc, frontend_port):
                add_check("frontend_process_started", "passed", f"frontend/server.py accepted --port and listened on {frontend_port}.", "frontend")
                self.check_frontend_index(frontend_port, add_check)
            else:
                add_check("frontend_process_started", "failed", f"frontend/server.py did not listen on requested port {frontend_port}.", "frontend")

            config_warning = self.frontend_backend_config_warning(frontend_artifact, frontend_usages)
            if config_warning:
                warnings.append(config_warning)

            for name, proc in processes:
                process_outputs.append(self.stop_process(name, proc))

        passed = not self.failed(checks)
        return self.result(passed, checks, warnings, process_outputs, backend_port, frontend_port, frontend_usages, backend_routes)

    def start_process(self, cwd, port, extra_env):
        env = os.environ.copy()
        env.update(extra_env)
        return subprocess.Popen(
            [sys.executable, "server.py", "--port", str(port)],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait_port(self, proc, port, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def check_backend_routes(self, routes, port, add_check):
        seen = set()
        for route in routes:
            method = (route.get("method") or "GET").upper()
            path = route.get("path") or ""
            if not path.startswith("/") or (method, path) in seen:
                continue
            seen.add((method, path))
            payload = {key: f"sample-{key}" for key in route.get("request_keys") or []}
            if method == "POST" and not payload:
                payload = {"courseId": "c1", "teacherId": "t1"}
            status, body = self.http_request(method, f"http://127.0.0.1:{port}{path}", payload if method != "GET" else None)
            check_id = f"backend_route_{method}_{path.strip('/').replace('/', '_') or 'root'}"
            if status == 404:
                add_check(check_id, "failed", f"{method} {path} returned 404.", "backend")
            elif status >= 500:
                add_check(check_id, "failed", f"{method} {path} returned {status}: {body[:160]}", "backend")
            else:
                add_check(check_id, "passed", f"{method} {path} responded with HTTP {status}.", "backend")

    def check_frontend_index(self, port, add_check):
        status, body = self.http_request("GET", f"http://127.0.0.1:{port}/")
        if status == 404:
            add_check("frontend_index", "failed", "GET / returned 404.", "frontend")
        elif status >= 500:
            add_check("frontend_index", "failed", f"GET / returned {status}: {body[:160]}", "frontend")
        else:
            add_check("frontend_index", "passed", f"GET / responded with HTTP {status}.", "frontend")

    def frontend_backend_config_warning(self, frontend_artifact, frontend_usages):
        if not frontend_usages:
            return None
        files = store.read_bundle_files(frontend_artifact)
        frontend_text = "\n".join(
            content for path, content in files.items()
            if path.startswith("frontend/") and path.endswith((".js", ".ts", ".tsx", ".py", ".md"))
        )
        has_configurable_base = bool(re.search(r"API_BASE_URL|BACKEND_URL|URLSearchParams|apiUrl\s*\(", frontend_text))
        if has_configurable_base:
            return None
        return {
            "id": "frontend_backend_base_config",
            "status": "warning",
            "severity": "warning",
            "owner": "frontend",
            "message": "Frontend has API usages but no obvious configurable backend base URL. Demo may require manual code edits when FE/BE run on different ports.",
        }

    def http_request(self, method, url, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["content-type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return 599, str(exc)

    def stop_process(self, name, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=2)
        else:
            stdout, stderr = proc.communicate(timeout=2)
        return {
            "name": name,
            "exit_code": proc.returncode,
            "stdout_tail": (stdout or "")[-1200:],
            "stderr_tail": (stderr or "")[-1200:],
        }

    def free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def failed(self, checks):
        return any(check["status"] == "failed" for check in checks)

    def result(self, passed, checks, warnings, process_outputs, backend_port, frontend_port, frontend_usages, backend_routes):
        failed_checks = [check for check in checks if check["status"] == "failed"]
        summary = {
            "passed": passed,
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "frontend_usages_checked_by_contract": len(frontend_usages),
            "backend_routes_smoked": len(backend_routes),
            "checks": checks,
            "warnings": warnings,
            "process_outputs": process_outputs,
        }
        report = {
            "role": "runtime",
            "status": "valid" if passed else "invalid_retryable",
            "checks": checks,
            "repairs": [],
            "warnings": warnings,
            "manifests": [{"type": "runtime", "item_count": len(checks)}],
            "retry_recommendation": "none",
            "failure_category": None if passed else "runtime_validation",
        }
        reason = "; ".join(f"{check['id']}: {check['message']}" for check in failed_checks)[:1200]
        files = {
            "runtime_report.json": json_dumps(summary),
            "runtime_report.md": self.markdown_report(passed, checks, warnings, process_outputs, backend_port, frontend_port),
        }
        return {
            "passed": passed,
            "files": files,
            "manifests": {"runtime": summary},
            "report": report,
            "errors": [reason] if reason else [],
            "failure_reason": reason,
        }

    def markdown_report(self, passed, checks, warnings, process_outputs, backend_port, frontend_port):
        lines = [
            "# Runtime Harness Report",
            "",
            f"Status: {'PASSED' if passed else 'FAILED'}",
            f"Backend requested port: {backend_port}",
            f"Frontend requested port: {frontend_port}",
            "",
            "## Checks",
        ]
        for check in checks:
            lines.append(f"- {check['status'].upper()} `{check['id']}`: {check['message']}")
        if warnings:
            lines.extend(["", "## Warnings"])
            for warning in warnings:
                lines.append(f"- WARNING `{warning['id']}`: {warning['message']}")
        lines.extend(["", "## Process Output"])
        for output in process_outputs:
            lines.append(f"### {output['name']}")
            lines.append(f"- exit_code: {output['exit_code']}")
            if output["stderr_tail"]:
                lines.append("```text")
                lines.append(output["stderr_tail"])
                lines.append("```")
        return "\n".join(lines) + "\n"


providers = {
    "mock": MockProvider(),
    "llm": OpenAICompatibleProvider(),
}
harness = ArtifactHarness()
checker = ContractChecker()
conflict_scenario_harness = ConflictScenarioHarness()
runtime_harness = RuntimeHarness()


class Orchestrator:
    def provider_for(self, mode):
        return providers.get(mode or "mock") or providers["mock"]

    def create_project(self, payload):
        project_id = new_id("project")
        ts = now_iso()
        data = {
            "id": project_id,
            "name": payload.get("name") or "Untitled Project",
            "requirement": payload.get("requirement") or "Build a small demo application.",
            "status": "created",
            "active_build_run_id": None,
            "provider_mode_preference": payload.get("provider_mode", "mock"),
            "force_api_conflict": 1 if payload.get("force_api_conflict", True) else 0,
            "human_review_required": 1 if payload.get("human_review_required", True) else 0,
            "created_at": ts,
            "updated_at": ts,
        }
        repo.insert("projects", data)
        self.log(project_id, None, None, "info", "project_created", f"Project created: {data['name']}")
        return self.project_detail(project_id)

    def start_build(self, project_id, payload):
        project = repo.row("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise NotFound("project not found")
        provider_mode = payload.get("provider_mode") or project["provider_mode_preference"] or "mock"
        force_conflict = bool(payload.get("force_api_conflict", bool(project["force_api_conflict"])))
        review_required = bool(payload.get("human_review_required", bool(project["human_review_required"])))
        build_id = new_id("build")
        ts = now_iso()
        repo.insert("build_runs", {
            "id": build_id,
            "project_id": project_id,
            "parent_build_run_id": project["active_build_run_id"],
            "context_policy": payload.get("context_policy", "fresh"),
            "status": "running",
            "stage": "pm",
            "provider_mode_actual": provider_mode,
            "force_api_conflict": 1 if force_conflict else 0,
            "human_review_required": 1 if review_required else 0,
            "failure_category": None,
            "started_at": ts,
            "completed_at": None,
            "failed_reason": None,
        })
        repo.update("projects", project_id, {
            "status": "running",
            "active_build_run_id": build_id,
            "provider_mode_preference": provider_mode,
            "force_api_conflict": 1 if force_conflict else 0,
            "human_review_required": 1 if review_required else 0,
            "updated_at": ts,
        })
        self.log(project_id, build_id, None, "info", "build_run_started", f"BuildRun started with provider_mode={provider_mode}, force_api_conflict={force_conflict}.")
        llm_config = llm_config_status()
        if provider_mode == "llm" and not llm_config["configured"]:
            missing = ", ".join(llm_config["missing"])
            self.fail_build(build_id, "provider_config", f"LLM mode selected but required config is missing: {missing}.")
        else:
            self.run_initial_until_pause_or_done(build_id)
        return self.project_detail(project_id)

    def run_initial_until_pause_or_done(self, build_id):
        build = self.build(build_id)
        self.run_agent(build_id, "pm")
        if self.build(build_id)["status"] == "failed":
            return
        repo.update("build_runs", build_id, {"stage": "architect"})
        arch_agent = self.run_agent(build_id, "architect")
        if self.build(build_id)["status"] == "failed":
            return
        build = self.build(build_id)
        if build["human_review_required"]:
            gate_id = new_id("review")
            repo.insert("review_gates", {"id": gate_id, "build_run_id": build_id, "agent_run_id": arch_agent["id"], "status": "open", "created_at": now_iso(), "resolved_at": None})
            repo.update("build_runs", build_id, {"status": "paused_review", "stage": "architect"})
            repo.update("projects", build["project_id"], {"status": "awaiting_review", "updated_at": now_iso()})
            self.log(build["project_id"], build_id, arch_agent["id"], "info", "review_gate_opened", "Human CTO review gate opened after Architect artifact.")
            return
        self.continue_after_review(build_id)

    def approve_review(self, build_id):
        build = self.build(build_id)
        gate = repo.row("SELECT * FROM review_gates WHERE build_run_id=? AND status='open' ORDER BY created_at DESC LIMIT 1", (build_id,))
        if not gate:
            raise BadRequest("no open review gate")
        repo.update("review_gates", gate["id"], {"status": "approved", "resolved_at": now_iso()})
        self.log(build["project_id"], build_id, gate["agent_run_id"], "info", "review_gate_approved", "Human CTO approved the review gate.")
        self.continue_after_review(build_id)
        return self.project_detail(build["project_id"])

    def continue_after_review(self, build_id):
        build = self.build(build_id)
        repo.update("build_runs", build_id, {"status": "running", "stage": "implementation"})
        repo.update("projects", build["project_id"], {"status": "running", "updated_at": now_iso()})
        self.log(build["project_id"], build_id, None, "info", "parallel_agents_started", "Frontend and Backend AgentRuns scheduled in parallel.")
        self.run_parallel_agents(build_id, ["frontend", "backend"])
        if self.build(build_id)["status"] == "failed":
            return
        self.maybe_inject_conflict_scenario(build_id)
        if self.build(build_id)["status"] == "failed":
            return
        self.run_contract_check(build_id)

    def resolve_conflict(self, conflict_id, decision):
        conflict = repo.row("SELECT * FROM conflicts WHERE id=?", (conflict_id,))
        if not conflict:
            raise NotFound("conflict not found")
        if conflict["status"] != "open":
            raise BadRequest("conflict is not open")
        build = self.build(conflict["build_run_id"])
        resolution_agent_id = None
        repo.update("build_runs", build["id"], {"status": "running", "stage": "conflict_resolution"})
        repo.update("projects", build["project_id"], {"status": "running", "updated_at": now_iso()})
        repo.update("conflicts", conflict_id, {"status": "resolving", "decision": decision})
        if decision == "align_to_frontend":
            repo.update("agent_runs", conflict["backend_agent_run_id"], {"status": "superseded"})
            agent = self.run_agent(build["id"], "backend", trigger_reason="conflict_resolution", alignment_mode="align_to_frontend", resolves_conflict_id=conflict_id)
            resolution_agent_id = agent["id"]
        elif decision == "align_to_backend":
            repo.update("agent_runs", conflict["frontend_agent_run_id"], {"status": "superseded"})
            agent = self.run_agent(build["id"], "frontend", trigger_reason="conflict_resolution", alignment_mode="align_to_backend", resolves_conflict_id=conflict_id)
            resolution_agent_id = agent["id"]
        elif decision == "force_pass":
            resolution_agent_id = None
        else:
            raise BadRequest("decision must be align_to_frontend, align_to_backend, or force_pass")

        if self.build(build["id"])["status"] == "failed":
            return self.project_detail(build["project_id"])

        repo.update("conflicts", conflict_id, {
            "status": "forced" if decision == "force_pass" else "resolved",
            "decision": decision,
            "resolution_agent_run_id": resolution_agent_id,
            "resolved_by": "human_cto",
            "resolved_at": now_iso(),
        })
        self.log(build["project_id"], build["id"], resolution_agent_id, "info", "conflict_resolved", f"Human CTO decision: {decision}.")
        if decision == "force_pass":
            self.run_qa_and_complete(build["id"], conflict)
        else:
            self.run_contract_check(build["id"])
        return self.project_detail(build["project_id"])

    def run_contract_check(self, build_id):
        build = self.build(build_id)
        repo.update("build_runs", build_id, {"stage": "contract_check"})
        frontend_artifact = self.latest_artifact(build_id, "frontend")
        backend_artifact = self.latest_artifact(build_id, "backend")
        frontend_usages = json_loads(frontend_artifact["manifest_json"], {}).get("api_usages", [])
        backend_routes = json_loads(backend_artifact["manifest_json"], {}).get("routes", [])
        mismatches = checker.compare(frontend_usages, backend_routes)
        if mismatches:
            conflict_id = new_id("conflict")
            repo.insert("conflicts", {
                "id": conflict_id,
                "build_run_id": build_id,
                "status": "open",
                "frontend_agent_run_id": frontend_artifact["agent_run_id"],
                "backend_agent_run_id": backend_artifact["agent_run_id"],
                "frontend_api_usages": json_dumps(frontend_usages),
                "backend_routes": json_dumps(backend_routes),
                "mismatches": json_dumps(mismatches),
                "decision": None,
                "resolution_agent_run_id": None,
                "resolved_by": None,
                "created_at": now_iso(),
                "resolved_at": None,
            })
            repo.update("build_runs", build_id, {"status": "paused_conflict", "stage": "conflict_resolution"})
            repo.update("projects", build["project_id"], {"status": "conflict", "updated_at": now_iso()})
            self.log(build["project_id"], build_id, None, "warning", "conflict_opened", f"ContractChecker found {len(mismatches)} FE/BE API mismatches.")
        else:
            self.log(build["project_id"], build_id, None, "info", "contract_check_passed", "Frontend API usages match backend routes.")
            self.run_qa_and_complete(build_id)

    def run_qa_and_complete(self, build_id, conflict=None):
        build = self.build(build_id)
        repo.update("build_runs", build_id, {"status": "running", "stage": "runtime_validation"})
        frontend_artifact = self.latest_artifact(build_id, "frontend")
        backend_artifact = self.latest_artifact(build_id, "backend")
        runtime_result = runtime_harness.run(frontend_artifact, backend_artifact)
        runtime_artifact = self.save_platform_artifact(
            build_id,
            role="runtime",
            artifact_type="runtime",
            result=runtime_result,
            trigger_reason="runtime_validation",
            input_artifact_ids=[frontend_artifact["id"], backend_artifact["id"]],
            agent_status="completed" if runtime_result["passed"] else "failed",
        )
        if not runtime_artifact:
            return
        if not runtime_result["passed"]:
            self.fail_build(build_id, "runtime_validation", runtime_result["failure_reason"] or "generated application runtime validation failed")
            return
        self.log(build["project_id"], build_id, None, "info", "runtime_harness_passed", "Generated frontend and backend passed runtime smoke checks.")
        repo.update("build_runs", build_id, {"status": "running", "stage": "qa"})
        self.run_agent(build_id, "qa", conflict=conflict)
        if self.build(build_id)["status"] == "failed":
            return
        repo.update("build_runs", build_id, {"status": "completed", "stage": "ready_for_export", "completed_at": now_iso()})
        repo.update("projects", build["project_id"], {"status": "completed", "updated_at": now_iso()})
        self.log(build["project_id"], build_id, None, "info", "build_run_completed", "BuildRun completed. ZIP export is available.")

    def run_agent(self, build_id, role, trigger_reason="initial", alignment_mode="none", retry_of=None, resolves_conflict_id=None, conflict=None, retry_depth=0, retry_hint=None):
        build = self.build(build_id)
        project = repo.row("SELECT * FROM projects WHERE id=?", (build["project_id"],))
        previous = self.previous_artifacts(build_id)
        attempt_no = 1 + repo.row("SELECT COUNT(*) AS c FROM agent_runs WHERE build_run_id=? AND role=?", (build_id, role))["c"]
        agent_id = new_id("agent")
        ts = now_iso()
        repo.insert("agent_runs", {
            "id": agent_id,
            "build_run_id": build_id,
            "role": role,
            "status": "running",
            "attempt_no": attempt_no,
            "trigger_reason": trigger_reason,
            "provider_mode": build["provider_mode_actual"],
            "input_artifact_ids": json_dumps([artifact["id"] for artifact in previous]),
            "output_artifact_ids": "[]",
            "alignment_mode": alignment_mode,
            "failure_category": None,
            "retryable": 0,
            "retry_of_agent_run_id": retry_of,
            "resolves_conflict_id": resolves_conflict_id,
            "started_at": ts,
            "completed_at": None,
            "failed_reason": None,
        })
        self.log(project["id"], build_id, agent_id, "info", "agent_run_started", f"{role} AgentRun started, attempt_no={attempt_no}, trigger_reason={trigger_reason}.")
        try:
            files = self.provider_for(build["provider_mode_actual"]).run(project, build, role, previous, alignment_mode=alignment_mode, conflict=conflict, retry_hint=retry_hint)
            result = harness.run(role, project, files)
        except ProviderError as exc:
            return self.handle_agent_failure(
                build_id,
                role,
                agent_id,
                exc.category,
                str(exc),
                exc.retryable,
                trigger_reason,
                alignment_mode,
                resolves_conflict_id,
                conflict,
                retry_depth,
            )
        except Exception as exc:
            return self.handle_agent_failure(
                build_id,
                role,
                agent_id,
                "unknown",
                str(exc),
                False,
                trigger_reason,
                alignment_mode,
                resolves_conflict_id,
                conflict,
                retry_depth,
            )
        if result["status"] not in ("valid", "repaired"):
            category = result["report"].get("failure_category") or "generation_invalid"
            return self.handle_agent_failure(
                build_id,
                role,
                agent_id,
                category,
                f"{role} artifact invalid: {'; '.join(result['errors'])}",
                True,
                trigger_reason,
                alignment_mode,
                resolves_conflict_id,
                conflict,
                retry_depth,
            )

        artifact_type = "api_contract" if role == "architect" else role
        version = 1 + repo.row("SELECT COUNT(*) AS c FROM artifacts WHERE build_run_id=? AND type=?", (build_id, artifact_type))["c"]
        artifact_id = new_id("artifact")
        try:
            artifact_path = store.write_bundle(project["id"], build_id, agent_id, result["files"], result["manifests"], result["report"])
        except OSError as exc:
            return self.handle_agent_failure(
                build_id,
                role,
                agent_id,
                "artifact_io",
                f"failed to write artifact: {exc}",
                True,
                trigger_reason,
                alignment_mode,
                resolves_conflict_id,
                conflict,
                retry_depth,
            )
        repo.insert("artifacts", {
            "id": artifact_id,
            "project_id": project["id"],
            "build_run_id": build_id,
            "agent_run_id": agent_id,
            "type": artifact_type,
            "path": artifact_path,
            "content_preview": preview(result["files"]),
            "version": version,
            "manifest_json": json_dumps(result["manifests"]),
            "harness_report_json": json_dumps(result["report"]),
            "created_at": now_iso(),
        })
        repo.update("agent_runs", agent_id, {"status": "completed", "output_artifact_ids": json_dumps([artifact_id]), "completed_at": now_iso()})
        self.log(project["id"], build_id, agent_id, "info", "artifact_saved", f"{role} artifact saved with harness_status={result['status']}.")
        return repo.row("SELECT * FROM agent_runs WHERE id=?", (agent_id,))

    def maybe_inject_conflict_scenario(self, build_id):
        build = self.build(build_id)
        if not build["force_api_conflict"]:
            return
        existing_conflicts = repo.row("SELECT COUNT(*) AS c FROM conflicts WHERE build_run_id=?", (build_id,))["c"]
        if existing_conflicts:
            return
        project = repo.row("SELECT * FROM projects WHERE id=?", (build["project_id"],))
        frontend_artifact = self.latest_artifact(build_id, "frontend")
        backend_artifact = self.latest_artifact(build_id, "backend")
        frontend_usages = json_loads(frontend_artifact["manifest_json"], {}).get("api_usages", [])
        backend_routes = json_loads(backend_artifact["manifest_json"], {}).get("routes", [])
        if checker.compare(frontend_usages, backend_routes):
            self.log(build["project_id"], build_id, None, "info", "conflict_scenario_already_present", "force_api_conflict is enabled and generated artifacts already contain a detectable API mismatch.")
            return

        result = conflict_scenario_harness.run(project, frontend_artifact)
        if not result:
            self.fail_build(build_id, "generation_invalid", "force_api_conflict is enabled, but ConflictScenarioHarness could not rewrite any frontend API usage.")
            return
        if result["status"] not in ("valid", "repaired"):
            reason = "; ".join(result.get("errors") or ["ConflictScenarioHarness produced an invalid frontend artifact."])
            self.fail_build(build_id, result["report"].get("failure_category") or "generation_invalid", reason)
            return

        artifact = self.save_platform_artifact(
            build_id,
            role="frontend",
            artifact_type="frontend",
            result=result,
            trigger_reason="scenario_conflict_injection",
            input_artifact_ids=[frontend_artifact["id"], backend_artifact["id"]],
            provider_mode="platform",
        )
        if not artifact:
            return
        changes = result["report"].get("scenario", {}).get("changes", [])
        self.log(
            build["project_id"],
            build_id,
            artifact["agent_run_id"] if artifact else None,
            "info",
            "conflict_scenario_injected",
            f"ConflictScenarioHarness created frontend v{artifact['version']} with {len(changes)} deterministic API rewrite(s).",
        )

    def save_platform_artifact(
        self,
        build_id,
        role,
        artifact_type,
        result,
        trigger_reason,
        input_artifact_ids=None,
        provider_mode="platform",
        agent_status="completed",
    ):
        build = self.build(build_id)
        project = repo.row("SELECT * FROM projects WHERE id=?", (build["project_id"],))
        attempt_no = 1 + repo.row("SELECT COUNT(*) AS c FROM agent_runs WHERE build_run_id=? AND role=?", (build_id, role))["c"]
        agent_id = new_id("agent")
        ts = now_iso()
        repo.insert("agent_runs", {
            "id": agent_id,
            "build_run_id": build_id,
            "role": role,
            "status": "running",
            "attempt_no": attempt_no,
            "trigger_reason": trigger_reason,
            "provider_mode": provider_mode,
            "input_artifact_ids": json_dumps(input_artifact_ids or []),
            "output_artifact_ids": "[]",
            "alignment_mode": "none",
            "failure_category": None if agent_status == "completed" else result["report"].get("failure_category"),
            "retryable": 0,
            "retry_of_agent_run_id": None,
            "resolves_conflict_id": None,
            "started_at": ts,
            "completed_at": None,
            "failed_reason": None,
        })
        version = 1 + repo.row("SELECT COUNT(*) AS c FROM artifacts WHERE build_run_id=? AND type=?", (build_id, artifact_type))["c"]
        artifact_id = new_id("artifact")
        try:
            artifact_path = store.write_bundle(project["id"], build_id, agent_id, result["files"], result["manifests"], result["report"])
        except OSError as exc:
            repo.update("agent_runs", agent_id, {
                "status": "failed",
                "failure_category": "artifact_io",
                "completed_at": now_iso(),
                "failed_reason": f"failed to write platform artifact: {exc}",
            })
            self.fail_build(build_id, "artifact_io", f"failed to write platform artifact: {exc}")
            return None
        repo.insert("artifacts", {
            "id": artifact_id,
            "project_id": project["id"],
            "build_run_id": build_id,
            "agent_run_id": agent_id,
            "type": artifact_type,
            "path": artifact_path,
            "content_preview": preview(result["files"]),
            "version": version,
            "manifest_json": json_dumps(result["manifests"]),
            "harness_report_json": json_dumps(result["report"]),
            "created_at": now_iso(),
        })
        repo.update("agent_runs", agent_id, {
            "status": agent_status,
            "output_artifact_ids": json_dumps([artifact_id]),
            "completed_at": now_iso(),
            "failure_category": None if agent_status == "completed" else result["report"].get("failure_category"),
            "failed_reason": None if agent_status == "completed" else result.get("failure_reason"),
        })
        self.log(project["id"], build_id, agent_id, "info", "platform_artifact_saved", f"{artifact_type} platform artifact saved from {trigger_reason}.")
        return repo.row("SELECT * FROM artifacts WHERE id=?", (artifact_id,))

    def run_parallel_agents(self, build_id, roles):
        threads = []

        def worker(role):
            try:
                self.run_agent(build_id, role)
            except Exception as exc:
                build = self.build(build_id)
                self.fail_build(build_id, "unknown", f"{role} parallel execution failed: {exc}")

        for role in roles:
            thread = threading.Thread(target=worker, args=(role,), daemon=False)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()

    def handle_agent_failure(self, build_id, role, agent_id, category, reason, retryable, trigger_reason, alignment_mode, resolves_conflict_id, conflict, retry_depth):
        build = self.build(build_id)
        max_retries = MAX_RETRIES_BY_CATEGORY.get(category, 0)
        should_retry = bool(retryable) and retry_depth < max_retries
        repo.update("agent_runs", agent_id, {
            "status": "failed",
            "failure_category": category,
            "retryable": 1 if should_retry else 0,
            "completed_at": now_iso(),
            "failed_reason": reason,
        })
        self.log(build["project_id"], build_id, agent_id, "warning" if should_retry else "error", "agent_run_failed", f"{role} failed with {category}: {reason}")
        if should_retry:
            self.log(build["project_id"], build_id, agent_id, "info", "agent_retry_scheduled", f"Retrying {role}; retry {retry_depth + 1}/{max_retries}.")
            return self.run_agent(
                build_id,
                role,
                trigger_reason="retry",
                alignment_mode=alignment_mode,
                retry_of=agent_id,
                resolves_conflict_id=resolves_conflict_id,
                conflict=conflict,
                retry_depth=retry_depth + 1,
                retry_hint=reason,
            )
        self.fail_build(build_id, category, reason)
        return repo.row("SELECT * FROM agent_runs WHERE id=?", (agent_id,))

    def fail_build(self, build_id, category, reason):
        build = self.build(build_id)
        repo.update("build_runs", build_id, {"status": "failed", "failure_category": category, "failed_reason": reason, "completed_at": now_iso()})
        repo.update("projects", build["project_id"], {"status": "failed", "updated_at": now_iso()})
        self.log(build["project_id"], build_id, None, "error", "build_run_failed", f"{category}: {reason}")

    def previous_artifacts(self, build_id):
        return repo.rows("SELECT * FROM artifacts WHERE build_run_id=? ORDER BY created_at ASC", (build_id,))

    def latest_artifact(self, build_id, artifact_type):
        row = repo.row("SELECT * FROM artifacts WHERE build_run_id=? AND type=? ORDER BY version DESC LIMIT 1", (build_id, artifact_type))
        if not row:
            raise BadRequest(f"missing artifact: {artifact_type}")
        return row

    def build(self, build_id):
        build = repo.row("SELECT * FROM build_runs WHERE id=?", (build_id,))
        if not build:
            raise NotFound("build run not found")
        return build

    def log(self, project_id, build_id, agent_run_id, level, event_type, message):
        repo.insert("log_events", {
            "id": new_id("log"),
            "project_id": project_id,
            "build_run_id": build_id,
            "agent_run_id": agent_run_id,
            "level": level,
            "event_type": event_type,
            "message": message,
            "created_at": now_iso(),
        })

    def project_detail(self, project_id):
        project = repo.row("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise NotFound("project not found")
        build = None
        agent_runs = []
        artifacts = []
        conflicts = []
        review_gates = []
        logs = repo.rows("SELECT * FROM log_events WHERE project_id=? ORDER BY created_at DESC LIMIT 80", (project_id,))
        if project["active_build_run_id"]:
            build = repo.row("SELECT * FROM build_runs WHERE id=?", (project["active_build_run_id"],))
            agent_runs = repo.rows("SELECT * FROM agent_runs WHERE build_run_id=? ORDER BY started_at ASC", (build["id"],))
            artifacts = repo.rows("SELECT * FROM artifacts WHERE build_run_id=? ORDER BY created_at ASC", (build["id"],))
            conflicts = repo.rows("SELECT * FROM conflicts WHERE build_run_id=? ORDER BY created_at DESC", (build["id"],))
            review_gates = repo.rows("SELECT * FROM review_gates WHERE build_run_id=? ORDER BY created_at DESC", (build["id"],))
        for artifact in artifacts:
            artifact["manifest"] = json_loads(artifact.pop("manifest_json"), {})
            artifact["harness_report"] = json_loads(artifact.pop("harness_report_json"), {})
            artifact["files"] = store.list_files(artifact)
        for conflict in conflicts:
            conflict["frontend_api_usages"] = json_loads(conflict["frontend_api_usages"], [])
            conflict["backend_routes"] = json_loads(conflict["backend_routes"], [])
            conflict["mismatches"] = json_loads(conflict["mismatches"], [])
        return {"project": project, "active_build_run": build, "agent_runs": agent_runs, "artifacts": artifacts, "conflicts": conflicts, "review_gates": review_gates, "logs": logs}


orchestrator = Orchestrator()


class ApiError(Exception):
    status = HTTPStatus.BAD_REQUEST


class NotFound(ApiError):
    status = HTTPStatus.NOT_FOUND


class BadRequest(ApiError):
    status = HTTPStatus.BAD_REQUEST


class Handler(BaseHTTPRequestHandler):
    server_version = "AISoftwareCompany/0.1"

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/"):
                return self.handle_api(method, path, parse_qs(parsed.query))
            return self.serve_static(path)
        except ApiError as exc:
            self.send_json({"error": str(exc)}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api(self, method, path, query):
        if method == "GET" and path == "/api/health":
            return self.send_json({"ok": True, "data_dir": str(DATA_DIR)})
        if method == "GET" and path == "/api/config":
            return self.send_json({
                "provider_mode_default": os.environ.get("PROVIDER_MODE_DEFAULT", "mock"),
                "llm": llm_config_status(),
                "toolset": toolset_status(),
            })
        if method == "GET" and path == "/api/projects":
            rows = repo.rows(
                """
                SELECT p.*, b.stage AS active_stage, b.status AS build_status
                FROM projects p
                LEFT JOIN build_runs b ON p.active_build_run_id = b.id
                ORDER BY p.created_at DESC
                """
            )
            return self.send_json({"projects": rows})
        if method == "POST" and path == "/api/projects":
            return self.send_json(orchestrator.create_project(self.read_json()))

        match = re.fullmatch(r"/api/projects/([^/]+)", path)
        if method == "GET" and match:
            return self.send_json(orchestrator.project_detail(unquote(match.group(1))))

        match = re.fullmatch(r"/api/projects/([^/]+)/builds", path)
        if method == "POST" and match:
            return self.send_json(orchestrator.start_build(unquote(match.group(1)), self.read_json()))

        match = re.fullmatch(r"/api/build-runs/([^/]+)/review/approve", path)
        if method == "POST" and match:
            return self.send_json(orchestrator.approve_review(unquote(match.group(1))))

        match = re.fullmatch(r"/api/conflicts/([^/]+)/resolve", path)
        if method == "POST" and match:
            payload = self.read_json()
            return self.send_json(orchestrator.resolve_conflict(unquote(match.group(1)), payload.get("decision")))

        match = re.fullmatch(r"/api/artifacts/([^/]+)/file", path)
        if method == "GET" and match:
            artifact = repo.row("SELECT * FROM artifacts WHERE id=?", (unquote(match.group(1)),))
            if not artifact:
                raise NotFound("artifact not found")
            rel_path = query.get("path", [""])[0]
            return self.send_json({"path": rel_path, "content": store.read_file(artifact, rel_path)})

        match = re.fullmatch(r"/api/build-runs/([^/]+)/export", path)
        if method == "GET" and match:
            return self.export_zip(unquote(match.group(1)))

        raise NotFound("route not found")

    def export_zip(self, build_id):
        build = repo.row("SELECT * FROM build_runs WHERE id=?", (build_id,))
        if not build:
            raise NotFound("build run not found")
        if build["status"] != "completed":
            raise BadRequest("BuildRun is not completed; ZIP is not available")
        artifacts = repo.rows("SELECT * FROM artifacts WHERE build_run_id=? ORDER BY version ASC", (build_id,))
        latest = {}
        for artifact in artifacts:
            latest[artifact["type"]] = artifact
        required = ["pm", "api_contract", "frontend", "backend", "runtime", "qa"]
        missing = [kind for kind in required if kind not in latest]
        if missing:
            raise BadRequest(f"missing artifacts for export: {', '.join(missing)}")
        project_id = build["project_id"]
        out_dir = EXPORT_DIR / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"{build_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for artifact in latest.values():
                root = DATA_DIR / artifact["path"]
                for file_path in sorted(root.rglob("*")):
                    if not file_path.is_file():
                        continue
                    rel = file_path.relative_to(root)
                    if artifact["type"] == "pm" and rel.name == "prd.md":
                        arcname = "prd.md"
                    elif artifact["type"] == "api_contract" and rel.name in ("architecture.md", "api-contract.json"):
                        arcname = rel.name
                    elif artifact["type"] == "qa" and rel.name == "qa_report.md":
                        arcname = "qa_report.md"
                    else:
                        arcname = str(rel).replace("\\", "/")
                    zf.write(file_path, arcname)
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/zip")
        self.send_header("content-disposition", f'attachment; filename="{build_id}.zip"')
        self.send_header("content-length", str(zip_path.stat().st_size))
        self.end_headers()
        with zip_path.open("rb") as fh:
            shutil.copyfileobj(fh, self.wfile)

    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        safe = ensure_safe_path(path.lstrip("/"))
        target = (STATIC_DIR / safe).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/html"
        if target.suffix == ".css":
            content_type = "text/css"
        elif target.suffix == ".js":
            content_type = "text/javascript"
        elif target.suffix == ".json":
            content_type = "application/json"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", f"{content_type}; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json_dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI Software Company MVP v0.1 listening on http://{args.host}:{args.port}")
    print(f"DATA_DIR={DATA_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
