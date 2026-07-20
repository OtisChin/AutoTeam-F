# India UPI Placeholder Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent India UPI page under the Payments sidebar with Pix-like extraction UI and stable placeholder backend APIs.

**Architecture:** Add a focused FastAPI router for `/api/india-upi` placeholder contracts, then wire a new Vue page through the existing sidebar, app router, and API helper layer. Keep Brazil PIX code unchanged and isolate UPI state in UPI-specific files and localStorage keys.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, Vue 3 `<script setup>`, existing `web/src/api.js` fetch wrapper, Tailwind utility classes.

## Global Constraints

- Left sidebar `Payments` must show `印度UPI` immediately after `巴西Pix`.
- Main page key must be `indiaUpi`; backend route prefix must be `/api/india-upi`.
- UPI page must be independent from `BrazilPixPage.vue`; do not refactor or change Pix behavior.
- Backend core extraction functionality remains empty by design and must return a stable placeholder job instead of a 404.
- Placeholder job result must expose `implemented: false` and the message `印度UPI 后端核心提链功能待接入`.
- Use UPI account fields: `upi_status`, `upi_status_text`, `upi_error`, `upi_status_updated_at`, `upi_selectable`.
- Data files are `data/india_upi_links.json` and `data/india_upi_account_status.json`.
- Do not add new runtime dependencies.

---

## File Structure

- Create `src/autotoken/api_routes/india_upi.py`: UPI request models, in-memory jobs, account/link JSON helpers, `create_india_upi_router()`.
- Modify `src/autotoken/interfaces/api.py`: import and mount `create_india_upi_router()`.
- Create `tests/unit/test_india_upi_routes.py`: router contract tests.
- Modify `web/src/api.js`: UPI helper methods.
- Create `web/src/components/IndiaUpiPage.vue`: Pix-like UPI extraction workspace.
- Modify `web/src/App.vue`: add `IndiaUpiPage` render branch and `PAGE_KEYS` entry.
- Modify `web/src/components/Sidebar.vue`: add `印度UPI` item below `巴西Pix`.

---

### Task 1: Backend India UPI Placeholder Router

**Files:**
- Create: `src/autotoken/api_routes/india_upi.py`
- Create: `tests/unit/test_india_upi_routes.py`

**Interfaces:**
- Produces: `create_india_upi_router() -> fastapi.APIRouter`
- Produces models: `IndiaUpiStartRequest`, `IndiaUpiBatchStartRequest`, `IndiaUpiDeleteLinksRequest`
- Produces: `JOBS: dict[str, dict[str, Any]]`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_india_upi_routes.py`:

```python
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

from autotoken.api_routes import india_upi


def _app():
    app = FastAPI()
    app.include_router(india_upi.create_india_upi_router())
    return app


def _endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"missing route {method} {path}")


@pytest.fixture(autouse=True)
def isolated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(india_upi, "LINKS_FILE", tmp_path / "india_upi_links.json")
    monkeypatch.setattr(india_upi, "ACCOUNT_STATUS_FILE", tmp_path / "india_upi_account_status.json")
    india_upi.JOBS.clear()
    yield
    india_upi.JOBS.clear()


def test_accounts_default_to_pending_upi_status(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [
        {"email": "user@example.com", "status": "active", "account_type": "free", "ttl_seconds": 3600},
        {"email": "plus@example.com", "status": "active", "account_type": "plus", "ttl_seconds": 7200},
    ])

    result = _endpoint(app, "/api/india-upi/accounts", "GET")()

    assert [row["email"] for row in result["accounts"]] == ["user@example.com", "plus@example.com"]
    assert result["accounts"][0]["upi_status"] == "pending"
    assert result["accounts"][0]["upi_status_text"] == "未提链"
    assert result["accounts"][0]["upi_selectable"] is True


def test_batch_start_creates_not_implemented_job(monkeypatch):
    app = _app()
    monkeypatch.setattr(india_upi.account_store, "load_accounts", lambda: [{"email": "user@example.com"}])

    result = _endpoint(app, "/api/india-upi/batch/start", "POST")(
        india_upi.IndiaUpiBatchStartRequest.model_validate({
            "accountEmails": ["user@example.com"],
            "proxies": "host:port:user:pass",
            "concurrency": 2,
        })
    )
    job = _endpoint(app, "/api/india-upi/jobs/{job_id}", "GET")(result["job_id"])

    assert job["status"] == "not_implemented"
    assert job["total"] == 1
    assert job["completed"] == 0
    assert job["result"]["implemented"] is False
    assert "印度UPI 后端核心提链功能待接入" in "\n".join(job["logs"])


def test_start_requires_selected_account():
    app = _app()

    with pytest.raises(HTTPException) as exc:
        _endpoint(app, "/api/india-upi/batch/start", "POST")(
            india_upi.IndiaUpiBatchStartRequest.model_validate({"accountEmails": [], "concurrency": 1})
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bad_body"


def test_cancel_marks_non_terminal_job_cancelled():
    app = _app()
    india_upi.JOBS["job-1"] = {
        "id": "job-1", "status": "queued", "logs": [], "result": None, "error": None,
        "created_at": 1.0, "finished_at": None, "account_email": "", "total": 1,
        "completed": 0, "concurrency": 1, "cancel_requested": False,
        "running_count": 0, "skipped": [], "account_statuses": {},
    }

    result = _endpoint(app, "/api/india-upi/jobs/{job_id}/cancel", "POST")("job-1")

    assert result["ok"] is True
    assert result["status"] == "cancelled"
    assert india_upi.JOBS["job-1"]["cancel_requested"] is True
    assert india_upi.JOBS["job-1"]["finished_at"] is not None


def test_links_delete_and_clear_use_upi_file():
    app = _app()
    india_upi.LINKS_FILE.write_text(json.dumps([
        {"id": "keep", "upi_link": "upi://keep"},
        {"id": "remove", "upi_link": "upi://remove"},
    ]), encoding="utf-8")

    deleted = _endpoint(app, "/api/india-upi/links/delete", "POST")(india_upi.IndiaUpiDeleteLinksRequest(ids=["remove", "missing"]))
    cleared = _endpoint(app, "/api/india-upi/links/clear", "POST")()

    assert deleted["deleted"] == 1
    assert [item["id"] for item in deleted["links"]] == ["keep"]
    assert cleared == {"deleted": 1, "links": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/unit/test_india_upi_routes.py -q
```

Expected: FAIL on import because `india_upi` is not present.

- [ ] **Step 3: Implement router**

Create `src/autotoken/api_routes/india_upi.py` with:

```python
"""India UPI placeholder extraction routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from autotoken import account_store
from autotoken.paths import PROJECT_ROOT

LINKS_FILE = PROJECT_ROOT / "data" / "india_upi_links.json"
ACCOUNT_STATUS_FILE = PROJECT_ROOT / "data" / "india_upi_account_status.json"
MAX_BATCH_CONCURRENCY = 10
UPI_STATUS_PENDING = "pending"
UPI_STATUS_PAID = "paid"
UPI_STATUS_TEXT = {"pending": "未提链", "running": "提链中", "success": "已提链", "failed": "提链失败", "paid": "已支付"}
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
TERMINAL_STATUSES = {"success", "error", "cancelled", "not_implemented"}


class IndiaUpiStartRequest(BaseModel):
    account_email: str = Field("", alias="accountEmail")
    proxies: str = ""
    concurrency: int = 1
    local_proxy: str = Field("", alias="localProxy")
    kookeey_endpoint: str = Field("gate.kookeey.info:1000", alias="kookeeyEndpoint")
    kookeey_user: str = Field("", alias="kookeeyUser")
    kookeey_pass: str = Field("", alias="kookeeyPass")
    model_config = {"populate_by_name": True}


class IndiaUpiBatchStartRequest(IndiaUpiStartRequest):
    account_emails: list[str] = Field(default_factory=list, alias="accountEmails")
    max_accounts: int | None = Field(None, alias="maxAccounts")

    @field_validator("account_emails", mode="before")
    @classmethod
    def _clean_account_emails(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("accountEmails must be a list")
        seen: set[str] = set()
        emails: list[str] = []
        for item in value:
            email = str(item or "").strip()
            key = email.lower()
            if email and key not in seen:
                seen.add(key)
                emails.append(email)
        return emails


class IndiaUpiDeleteLinksRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_links() -> list[dict[str, Any]]:
    data = _read_json(LINKS_FILE, [])
    return data if isinstance(data, list) else []


def _save_links(items: list[dict[str, Any]]) -> None:
    _write_json(LINKS_FILE, items)


def _load_account_statuses() -> dict[str, dict[str, Any]]:
    data = _read_json(ACCOUNT_STATUS_FILE, {})
    return data if isinstance(data, dict) else {}


def _iter_auth_accounts_with_upi_status() -> list[dict[str, Any]]:
    statuses = _load_account_statuses()
    rows: list[dict[str, Any]] = []
    for account in account_store.load_accounts():
        email = str(account.get("email") or "").strip()
        if not email:
            continue
        item = statuses.get(email.lower()) if isinstance(statuses.get(email.lower()), dict) else {}
        status = str(item.get("status") or UPI_STATUS_PENDING)
        if status not in UPI_STATUS_TEXT:
            status = UPI_STATUS_PENDING
        rows.append({**account, "upi_status": status, "upi_status_text": str(item.get("status_text") or UPI_STATUS_TEXT[status]), "upi_error": str(item.get("error") or ""), "upi_status_updated_at": item.get("updated_at"), "upi_selectable": status != UPI_STATUS_PAID})
    return rows


def _new_job(account_emails: list[str], concurrency: int) -> str:
    job_id = uuid.uuid4().hex[:12]
    created = time.time()
    message = "印度UPI 后端核心提链功能待接入"
    skipped = [{"email": email, "reason": message} for email in account_emails]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "status": "not_implemented", "logs": ["任务已创建", message],
            "result": {"batch": True, "implemented": False, "message": message, "successes": [], "errors": [], "skipped": skipped},
            "error": None, "created_at": created, "finished_at": created,
            "account_email": account_emails[0] if len(account_emails) == 1 else "",
            "total": len(account_emails), "completed": 0,
            "concurrency": max(1, min(MAX_BATCH_CONCURRENCY, int(concurrency or 1))),
            "cancel_requested": False, "running_count": 0, "skipped": skipped, "account_statuses": {},
        }
    return job_id


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"id": job["id"], "status": job["status"], "logs": list(job["logs"]), "result": job["result"], "error": job["error"], "created_at": job["created_at"], "finished_at": job["finished_at"], "account_email": job.get("account_email") or "", "total": job.get("total") or 0, "completed": job.get("completed") or 0, "concurrency": job.get("concurrency") or 1, "running_count": job.get("running_count") or 0, "cancel_requested": bool(job.get("cancel_requested")), "skipped": job.get("skipped") or [], "account_statuses": job.get("account_statuses") or {}}


def create_india_upi_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/india-upi/accounts")
    def get_india_upi_accounts() -> dict[str, Any]:
        return {"accounts": _iter_auth_accounts_with_upi_status()}

    @router.post("/api/india-upi/start")
    def start_india_upi(req: IndiaUpiStartRequest) -> dict[str, str]:
        email = str(req.account_email or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        return {"job_id": _new_job([email], req.concurrency)}

    @router.post("/api/india-upi/batch/start")
    def start_india_upi_batch(req: IndiaUpiBatchStartRequest) -> dict[str, str]:
        emails = list(req.account_emails)
        if req.max_accounts and req.max_accounts > 0:
            emails = emails[: int(req.max_accounts)]
        if not emails:
            raise HTTPException(status_code=400, detail={"ok": False, "code": "bad_body", "message": "请选择要提链的账号"})
        return {"job_id": _new_job(emails, req.concurrency)}

    @router.get("/api/india-upi/jobs/{job_id}")
    def get_india_upi_job(job_id: str) -> dict[str, Any]:
        return _job_snapshot(job_id)

    @router.post("/api/india-upi/jobs/{job_id}/cancel")
    def cancel_india_upi_job(job_id: str) -> dict[str, Any]:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job.get("status") not in TERMINAL_STATUSES:
                job["status"] = "cancelled"
                job["cancel_requested"] = True
                job["finished_at"] = time.time()
            return {"ok": True, "job_id": job_id, "status": job.get("status"), "cancel_requested": bool(job.get("cancel_requested"))}

    @router.get("/api/india-upi/links")
    def get_india_upi_links() -> dict[str, Any]:
        return {"links": _load_links()}

    @router.post("/api/india-upi/links/delete")
    def delete_india_upi_links(req: IndiaUpiDeleteLinksRequest) -> dict[str, Any]:
        ids = {str(item) for item in req.ids if str(item)}
        items = _load_links()
        kept = [item for item in items if str(item.get("id") or "") not in ids] if ids else items
        if ids:
            _save_links(kept)
        return {"deleted": len(items) - len(kept), "links": kept}

    @router.post("/api/india-upi/links/clear")
    def clear_india_upi_links() -> dict[str, Any]:
        count = len(_load_links())
        _save_links([])
        return {"deleted": count, "links": []}

    return router
```

- [ ] **Step 4: Run backend tests**

Run:

```powershell
python -m pytest tests/unit/test_india_upi_routes.py -q
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit backend router**

```powershell
git add -- src/autotoken/api_routes/india_upi.py tests/unit/test_india_upi_routes.py
git commit -m "feat: add India UPI placeholder routes"
```

---

### Task 2: Mount Backend Router and Add API Helpers

**Files:**
- Modify: `src/autotoken/interfaces/api.py`
- Modify: `web/src/api.js`
- Modify: `tests/unit/test_india_upi_routes.py`

**Interfaces:**
- Consumes: `create_india_upi_router()`
- Produces: `api.getIndiaUpiAccounts`, `api.startIndiaUpi`, `api.startIndiaUpiBatch`, `api.getIndiaUpiJob`, `api.cancelIndiaUpiJob`, `api.getIndiaUpiLinks`, `api.deleteIndiaUpiLinks`, `api.clearIndiaUpiLinks`

- [ ] **Step 1: Add failing mount test**

Append:

```python
def test_main_api_mounts_india_upi_router():
    from autotoken.interfaces.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/india-upi/accounts" in paths
    assert "/api/india-upi/batch/start" in paths
    assert "/api/india-upi/jobs/{job_id}" in paths
    assert "/api/india-upi/links" in paths
```

- [ ] **Step 2: Verify it fails**

```powershell
python -m pytest tests/unit/test_india_upi_routes.py::test_main_api_mounts_india_upi_router -q
```

Expected: FAIL because router is not mounted.

- [ ] **Step 3: Mount router**

In `src/autotoken/interfaces/api.py`, add:

```python
from autotoken.api_routes.india_upi import create_india_upi_router
```

Then near the payment router includes:

```python
app.include_router(create_brazil_pix_router())
app.include_router(create_india_upi_router())
app.include_router(create_ideal_link_router())
```

- [ ] **Step 4: Add API helpers**

In `web/src/api.js` after Brazil Pix helpers:

```javascript
  getIndiaUpiAccounts: () => request('GET', '/india-upi/accounts'),
  startIndiaUpi: (payload) => request('POST', '/india-upi/start', payload),
  startIndiaUpiBatch: (payload) => request('POST', '/india-upi/batch/start', payload),
  getIndiaUpiJob: (jobId) => request('GET', `/india-upi/jobs/${encodeURIComponent(jobId)}`),
  cancelIndiaUpiJob: (jobId) => request('POST', `/india-upi/jobs/${encodeURIComponent(jobId)}/cancel`),
  getIndiaUpiLinks: () => request('GET', '/india-upi/links'),
  deleteIndiaUpiLinks: (ids) => request('POST', '/india-upi/links/delete', { ids }),
  clearIndiaUpiLinks: () => request('POST', '/india-upi/links/clear'),
```

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest tests/unit/test_india_upi_routes.py -q
git add -- src/autotoken/interfaces/api.py web/src/api.js tests/unit/test_india_upi_routes.py
git commit -m "feat: wire India UPI API surface"
```

Expected: tests PASS, 6 tests.

---

### Task 3: Sidebar and App Routing

**Files:**
- Modify: `web/src/components/Sidebar.vue`
- Modify: `web/src/App.vue`
- Create: `web/src/components/IndiaUpiPage.vue`

**Interfaces:**
- Produces page key: `indiaUpi`
- Produces component: `IndiaUpiPage`

- [ ] **Step 1: Create minimal component**

Create `web/src/components/IndiaUpiPage.vue`:

```vue
<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <p class="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-400">India UPI</p>
      <h2 class="mt-1 text-2xl font-bold text-white">印度UPI 提链</h2>
      <p class="mt-2 text-sm text-gray-400">印度 UPI 提链页面加载成功，后端核心功能待接入。</p>
    </section>
  </div>
</template>
```

- [ ] **Step 2: Wire App.vue**

Add:

```javascript
import IndiaUpiPage from './components/IndiaUpiPage.vue'
```

Add render branch after `BrazilPixPage`:

```vue
<IndiaUpiPage v-else-if="currentPage === 'indiaUpi'" />
```

Add `indiaUpi` after `brazilPix` in `PAGE_KEYS`.

- [ ] **Step 3: Wire Sidebar.vue**

Add after `brazilPix`:

```javascript
{ key: 'indiaUpi', group: 'Payments', glyph: 'UP', label: '印度UPI', mobileLabel: 'UPI' },
```

- [ ] **Step 4: Build and commit**

```powershell
npm --prefix web run build
git add -- web/src/App.vue web/src/components/Sidebar.vue web/src/components/IndiaUpiPage.vue
git commit -m "feat: add India UPI page navigation"
```

Expected: build PASS.

---

### Task 4: Implement Pix-like India UPI Extraction UI

**Files:**
- Modify: `web/src/components/IndiaUpiPage.vue`

**Interfaces:**
- Consumes all UPI API helpers from Task 2.
- Uses localStorage keys: `autotoken_india_upi_form`, `autotoken_india_upi_job`.

- [ ] **Step 1: Replace placeholder with full UI**

Implement `IndiaUpiPage.vue` as a focused Vue component with:

```javascript
const form = ref({ proxies: '', concurrency: 1, localProxy: '', kookeeyEndpoint: 'gate.kookeey.info:1000', kookeeyUser: '', kookeeyPass: '' })
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const busy = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
```

The template must include these sections with the same rounded dark-card visual style as Pix:

```text
顶部状态卡: India UPI / 印度UPI 提链 / 本地服务在线
任务输入: IN 代理列表, 并发数, 高级设置, 开始提链, 取消提链, 刷新账号/链接, 保存代理
账号池选择: 搜索账号邮箱, 全部状态 filter, 全选当前, 清空选择, columns 邮箱/有效期/提链状态
执行日志: logs rows from job.logs
最近一次任务: currentResult.message and skipped rows
链接管理: 已提取 UPI 链接, 刷新, 导出 JSON, 删除选中, 清空, columns 时间/账号/金额/操作/UPI 链接
```

Implement these functions exactly by name because the template depends on them:

```javascript
async function refreshAccounts() {
  const data = await api.getIndiaUpiAccounts()
  accounts.value = Array.isArray(data.accounts) ? data.accounts : []
}

async function refreshLinks() {
  const data = await api.getIndiaUpiLinks()
  links.value = Array.isArray(data.links) ? data.links : []
}

async function start() {
  if (!selectedEmails.value.length) {
    statusText.value = '请先选择要提链的账号。'
    statusError.value = true
    return
  }
  busy.value = true
  const data = await api.startIndiaUpiBatch({ ...form.value, accountEmails: selectedEmails.value })
  await pollJob(data.job_id)
}

async function pollJob(jobId) {
  const job = await api.getIndiaUpiJob(jobId)
  currentJob.value = job
  logs.value = Array.isArray(job.logs) ? job.logs : []
  currentResult.value = job.result || null
  busy.value = !['success', 'error', 'cancelled', 'not_implemented'].includes(String(job.status || ''))
  statusText.value = job.error || currentResult.value?.message || '任务状态已更新。'
}
```

Also implement `reloadAll`, `cancelJob`, `deleteSelectedLinks`, `clearLinks`, `exportLinks`, `copy`, `ttlText`, `accountStatusText`, `accountStatusClass`, `accountStatusError`, `accountSelectable`, `toggleAccount`, `selectAllFiltered`, `clearSelectedAccounts`, `toggleLink`, and localStorage persistence. Keep the implementation local to this file and do not import from `BrazilPixPage.vue`.

- [ ] **Step 2: Build and run backend tests**

```powershell
npm --prefix web run build
python -m pytest tests/unit/test_india_upi_routes.py -q
```

Expected: build PASS and tests PASS.

- [ ] **Step 3: Commit full UI**

```powershell
git add -- web/src/components/IndiaUpiPage.vue
git commit -m "feat: add India UPI extraction workspace"
```

---

### Task 5: Final Verification

**Files:**
- Verify: `src/autotoken/api_routes/india_upi.py`
- Verify: `src/autotoken/interfaces/api.py`
- Verify: `web/src/api.js`
- Verify: `web/src/App.vue`
- Verify: `web/src/components/Sidebar.vue`
- Verify: `web/src/components/IndiaUpiPage.vue`
- Verify: `tests/unit/test_india_upi_routes.py`

**Interfaces:**
- Consumes all previous tasks.

- [ ] **Step 1: Run targeted backend tests**

```powershell
python -m pytest tests/unit/test_india_upi_routes.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 3: Inspect git status**

```powershell
git status --short
```

Expected: no unstaged source changes except ignored build artifacts.

- [ ] **Step 4: Manual smoke check**

```text
Payments shows 巴西Pix then 印度UPI.
Click 印度UPI.
Title says 印度UPI 提链.
Click 刷新账号/链接; no 404 appears.
Select one account and click 开始提链.
Logs show 印度UPI 后端核心提链功能待接入.
最近一次任务 shows placeholder result.
```

- [ ] **Step 5: Commit verification fixes if any**

```powershell
git add -- <fixed-source-files>
git commit -m "fix: stabilize India UPI placeholder page"
```

Expected: skip this commit when no source fix is needed.

---

## Self-Review

- Spec coverage: sidebar entry, page key, Vue page, API helpers, backend placeholder router, placeholder job behavior, link management, and tests are covered.
- Placeholder scan: “placeholder/待接入” terms are intentional product behavior; no unresolved requirement remains.
- Type consistency: frontend helper names match component usage; backend route prefix and response fields match tests and UI.
