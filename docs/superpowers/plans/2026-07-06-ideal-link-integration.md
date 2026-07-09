# iDEAL Link Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Payments → 荷兰iDEAL page in AutoTeam-F and integrate the GPT-Hacker/gpthel- iDEAL link extraction flow.

**Architecture:** Copy the source iDEAL extraction implementation into an internal legacy adapter package, expose a narrow AutoTeam-F API router under `/api/ideal/*`, and build a Vue page that calls the new endpoints and renders logs, long link, and QR code. The UI follows the existing AutoToken dark dashboard system.

**Tech Stack:** FastAPI, Pydantic v2, Python requests/curl_cffi, qrcode[pil], Vue 3, Vite, Tailwind utility classes.

## Global Constraints

- Do not depend on `D:\code\OpenSource\GPT-Hacker\gpthel-` at runtime.
- Keep the front-end scope to the iDEAL link extraction page only.
- Access Token/session JSON is submitted to the API but not stored in local task history.
- Preserve source behavior for `/api/long-link/start`, polling job status, proxy chain choices, and QR generation, but expose them under AutoTeam-F `/api/ideal/*` endpoints.
- Follow existing AutoTeam-F route/component patterns.

---

### Task 1: Backend contract tests

**Files:**
- Create: `tests/unit/test_ideal_link_routes.py`

**Interfaces:**
- Produces expected route behavior for `create_ideal_link_router()`:
  - `POST /api/ideal/long-link/start` returns `{job_id}`.
  - `GET /api/ideal/long-link/jobs/{job_id}` returns job status.
  - `POST /api/ideal/qr` returns image/png.

- [ ] Write tests using FastAPI TestClient and monkeypatch the legacy adapter.
- [ ] Run `python -m pytest tests/unit/test_ideal_link_routes.py -q` and verify missing module/route failure.

### Task 2: Backend adapter and routes

**Files:**
- Create: `src/autotoken/integrations/gpthel_ideal/__init__.py`
- Create: `src/autotoken/integrations/gpthel_ideal/app.py`
- Create: `src/autotoken/integrations/gpthel_ideal/stripe_fingerprint.py`
- Create: `src/autotoken/integrations/gpthel_ideal/account_pool.py`
- Create: `src/autotoken/integrations/gpthel_ideal/mail_pool.py`
- Create: `src/autotoken/api_routes/ideal_link.py`
- Modify: `src/autotoken/interfaces/api.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `create_ideal_link_router() -> APIRouter`
- Routes proxy to legacy functions while keeping endpoint paths namespaced as `/api/ideal/*`.

- [ ] Copy source files from `D:\code\OpenSource\GPT-Hacker\gpthel-\app` into internal package and rewrite absolute local imports to package-relative imports.
- [ ] Add router with namespaced endpoints and QR streaming.
- [ ] Add `qrcode[pil]` dependency.
- [ ] Include router in main API.
- [ ] Run backend route tests and fix until green.

### Task 3: Frontend page and navigation

**Files:**
- Create: `web/src/components/IdealLinkPage.vue`
- Modify: `web/src/api.js`
- Modify: `web/src/components/Sidebar.vue`
- Modify: `web/src/App.vue`

**Interfaces:**
- API methods:
  - `startIdealLongLink(payload)`
  - `getIdealLongLinkJob(jobId)`
  - `getIdealQrBlob(value)`
  - `testIdealProxyChain(payload)`

- [ ] Add API helpers.
- [ ] Add `IdealLinkPage.vue` with token input, settings, log panel, QR/result panel, copy/download/open actions.
- [ ] Add Payments nav item label `荷兰iDEAL` and page key `ideal`.
- [ ] Wire App route and persisted page key.

### Task 4: Verification

**Files:**
- Verify only.

- [ ] Run `python -m pytest tests/unit/test_ideal_link_routes.py -q`.
- [ ] Run `npm run build` from `web`.
- [ ] Run any relevant targeted tests if import or API surface changes affect existing modules.
- [ ] Inspect diff and ensure no secrets from source fixed-proxy script were copied.
