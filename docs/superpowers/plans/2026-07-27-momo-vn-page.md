# MoMo VN Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增越南 MoMo 提链页面与后端链路，支持“仅检测资格”和“完整提链”两种模式，并区分“有资格 / 无资格 / 提链失败”状态。

**Architecture:** 以后端独立 `momo_vn` 模块承载资格检测和完整提链流程，前端新增独立 MoMo 页面，交互和布局参考 Kakao Pay 页面。资格检测先于提链执行；只有检测到 `momo` 支付方式的账号才会进入 promo / 0 元 / confirm / approve / poll 提链流程。

**Tech Stack:** FastAPI, Python, Vue 3, existing request helpers, pytest, Node script assertions

## Global Constraints

- 前端页面风格与交互尽量对齐现有 `KakaoPayPage.vue`
- 后端状态必须区分：`pending` / `eligible` / `ineligible` / `running` / `failed` / `success` / `paid`
- `qualificationOnly=true` 时只做资格检测，不提取链接
- 没有 `momo` 支付方式时直接标记 `ineligible`
- 有 `momo` 但后续提链失败时标记 `failed`
- 继续沿用当前项目的 JSON 文件存储与后台 job 结构

---

### Task 1: 先补后端资格/状态流测试

**Files:**
- Create: `tests/unit/test_momo_vn_routes.py`
- Create: `tests/unit/test_momo_vn_payment.py`
- Modify: `src/autotoken/interfaces/api.py`

**Interfaces:**
- Consumes: `create_momo_vn_router()`, `MomoVnStartRequest`, `MomoVnBatchStartRequest`, `generate_momo_vn_trial()`, `detect_momo_eligibility()`
- Produces: 覆盖资格检测、完整提链、状态写回、接口挂载的失败测试

- [ ] **Step 1: Write the failing route tests**
- [ ] **Step 2: Run `pytest tests/unit/test_momo_vn_routes.py -v` and verify import/route failures**
- [ ] **Step 3: Write the failing payment tests**
- [ ] **Step 4: Run `pytest tests/unit/test_momo_vn_payment.py -v` and verify symbol/behavior failures**

### Task 2: 实现 MoMo 支付核心

**Files:**
- Create: `src/autotoken/payments/momo_vn.py`
- Test: `tests/unit/test_momo_vn_payment.py`

**Interfaces:**
- Consumes: `build_chatgpt_session`, `build_stripe_session`, `warm_chatgpt_checkout_context`, existing proxy helpers
- Produces:
  - `MomoVnJobConfig`
  - `detect_momo_eligibility(cfg, log) -> dict[str, Any]`
  - `generate_momo_vn_trial(cfg, log) -> dict[str, Any]`

- [ ] **Step 1: Implement the minimum helpers required by the failing payment tests**
- [ ] **Step 2: Run `pytest tests/unit/test_momo_vn_payment.py -v` until green**
- [ ] **Step 3: Refactor helper extraction only after tests are green**

### Task 3: 实现 MoMo 后端路由与状态模型

**Files:**
- Create: `src/autotoken/api_routes/momo_vn.py`
- Modify: `src/autotoken/interfaces/api.py`
- Test: `tests/unit/test_momo_vn_routes.py`

**Interfaces:**
- Consumes: `detect_momo_eligibility`, `generate_momo_vn_trial`, account store helpers, auth token loading, FastAPI router patterns from Kakao/PayPal
- Produces:
  - `/api/momo-vn/accounts`
  - `/api/momo-vn/start`
  - `/api/momo-vn/batch/start`
  - `/api/momo-vn/jobs/{job_id}`
  - `/api/momo-vn/jobs/{job_id}/cancel`
  - `/api/momo-vn/links`
  - `/api/momo-vn/links/delete`
  - `/api/momo-vn/links/clear`

- [ ] **Step 1: Make route tests import the new router and fail on missing behavior**
- [ ] **Step 2: Implement status constants and persistence helpers**
- [ ] **Step 3: Implement qualification-only batch flow**
- [ ] **Step 4: Implement full extraction batch flow**
- [ ] **Step 5: Run `pytest tests/unit/test_momo_vn_routes.py -v` until green**

### Task 4: 接前端 API 和 MoMo 页面

**Files:**
- Modify: `web/src/api.js`
- Modify: `web/src/App.vue`
- Modify: `web/src/components/Sidebar.vue`
- Modify: `web/src/components/Dashboard.vue`
- Create: `web/src/components/MomoPage.vue`
- Create: `web/scripts/test-momo-page.mjs`

**Interfaces:**
- Consumes: `/api/momo-vn/*` endpoints, page-switching conventions, Kakao page UI patterns
- Produces:
  - `api.getMomoVnAccounts()`
  - `api.startMomoVnBatch()`
  - `api.getMomoVnJob()`
  - 其他 links/account delete helpers
  - MoMo 页面与“仅检测资格”按钮

- [ ] **Step 1: Write failing UI script assertions for page registration and qualification button**
- [ ] **Step 2: Run `node web/scripts/test-momo-page.mjs` and verify failures**
- [ ] **Step 3: Implement API bindings and page registration**
- [ ] **Step 4: Implement `MomoPage.vue` with Kakao-style layout and qualification-only button**
- [ ] **Step 5: Run `node web/scripts/test-momo-page.mjs` until green**

### Task 5: 回归验证与收尾

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/architecture.md`
- Test: `tests/unit/test_momo_vn_routes.py`
- Test: `tests/unit/test_momo_vn_payment.py`
- Test: `web/scripts/test-momo-page.mjs`

**Interfaces:**
- Consumes: all previous tasks
- Produces: 文档与最终验证结果

- [ ] **Step 1: 更新 API / 架构文档中的 MoMo 页面说明**
- [ ] **Step 2: Run `pytest tests/unit/test_momo_vn_routes.py tests/unit/test_momo_vn_payment.py -v`**
- [ ] **Step 3: Run `node web/scripts/test-momo-page.mjs`**
- [ ] **Step 4: Run any adjacent regression tests that fail due to page registration or imports**
