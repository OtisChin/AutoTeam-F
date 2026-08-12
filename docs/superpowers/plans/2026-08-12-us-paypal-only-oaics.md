# US PayPal Only OAICS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PayPal 提链 “仅 OAICS” option that skips accounts returning `cs_*` checkout sessions and only continues accounts returning `oaics_*`.

**Architecture:** Add a request/model flag, pass it into `PaypalJobConfig`, and let the payment core raise a typed skip exception when `cs_*` is returned while `only_oaics` is enabled. The batch route maps that typed skip to `skipped` instead of `failed`. The Vue form exposes a checkbox and submits `onlyOaics`.

**Tech Stack:** FastAPI + Pydantic backend, Python payment core, Vue frontend, pytest backend tests, Node static UI checks.

## Global Constraints

- Keep `cs_*` behavior unchanged when `onlyOaics=false`.
- `onlyOaics=true` skips `cs_*` accounts without marking failed/no-promo/success.
- Do not make real network requests in tests.
- Use TDD: failing tests before production changes.

---

### Task 1: Backend onlyOaics request and skip behavior

**Files:**
- Modify: `src/autotoken/payments/us_paypal.py`
- Modify: `src/autotoken/api_routes/us_paypal.py`
- Test: `tests/unit/test_us_paypal_routes.py`
- Test: `tests/unit/test_us_paypal_payment.py`

**Interfaces:**
- Produces: `PaypalOnlyOaicsSkipped(RuntimeError)` exception.
- Produces: `PaypalJobConfig.only_oaics: bool`.
- Produces: `UsPaypalStartRequest.only_oaics: bool = Field(False, alias="onlyOaics")`.

- [ ] Write failing tests:
  - request model parses `onlyOaics`.
  - `_run_batch_account()` maps `PaypalOnlyOaicsSkipped` to skipped/pending.
  - `generate_paypal_trial()` raises `PaypalOnlyOaicsSkipped` when `cfg.only_oaics=True` and checkout returns `cs_live_*`.
- [ ] Run failing tests.
- [ ] Add backend flag, config field, exception, and skip handling.
- [ ] Run tests green.

### Task 2: Frontend checkbox and payload

**Files:**
- Modify: `web/src/components/UsPaypalPage.vue`
- Test: `web/scripts/test-paypal-account-options.mjs`

**Interfaces:**
- Consumes backend request field: `onlyOaics`.
- Produces frontend form field: `form.onlyOaics`.

- [ ] Write failing static UI/API test assertions for `onlyOaics` field, checkbox text, and payload inclusion.
- [ ] Run failing static test.
- [ ] Add checkbox in PayPal 提链 input panel.
- [ ] Include `onlyOaics` in submission payload and status copy.
- [ ] Run static test green.

### Task 3: Verification

**Files:**
- All modified files.

- [ ] Run backend PayPal tests:
  - `.venv\Scripts\python.exe -m pytest tests\unit\test_us_paypal_routes.py tests\unit\test_us_paypal_payment.py tests\unit\test_us_paypal_oaics.py -q`
- [ ] Run frontend static test:
  - `cd web; npm run test:paypal-account-options`
- [ ] Run compile checks:
  - `.venv\Scripts\python.exe -m py_compile src\autotoken\payments\us_paypal.py src\autotoken\api_routes\us_paypal.py`
