# PayPal GB BA Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GB extraction mode that reliably returns a valid `BA-*` token through the live-proven GB/JP staged flow.

**Architecture:** Extend the existing PayPal BA executor. Each GB attempt derives two stable identities: GB for checkout/approve and JP for checkout update/Stripe/poll. Existing EU/US/BR behavior and the strict shared BA-success predicate remain unchanged.

**Tech Stack:** Python, FastAPI/Pydantic, pytest, Vue 3, Vite.

## Global Constraints

- Success remains `status == "success"` plus a token beginning `BA-`.
- GB checkout and approve share one sticky GB identity.
- JP update, Stripe init, PM, confirm, and poll share one different sticky JP identity.
- Rotate `sid-*` when supported; never log credentials, access tokens, or full BA values.
- Preserve EU, US, and BR behavior.

---

### Task 1: GB mode and proxy semantics

**Files:**
- Modify: `src/autotoken/services/paypal_billing_agreement.py`
- Modify: `src/autotoken/services/paypal_proxy.py`
- Modify: `src/autotoken/services/proxy_runtime.py`
- Test: `tests/unit/test_paypal_billing_agreement_service.py`
- Test: `tests/unit/test_paypal_proxy_service.py`

**Interfaces:**
- Produces: `paypal_ba_extract_mode("GB") == "gb"`.
- Produces: GB defaults `GB/GBP/custom` with JP payment/billing.
- Produces: region and `sid` proxy derivation without altering credentials/host/port.
- Produces: `prepare_paypal_proxy_runtime(..., paypal_ba_mode="gb")` with GB checkout and JP provider regions.

- [ ] **Step 1: Write failing tests**

```python
def test_paypal_ba_extract_mode_accepts_gb():
    assert paypal_billing_agreement.paypal_ba_extract_mode("GB") == "gb"


def test_paypal_ba_payment_method_country_defaults_to_jp_for_gb():
    assert paypal_billing_agreement.paypal_ba_payment_method_country(
        override="", protocol_no_card=True, paypal_country="JP", paypal_ba_mode="gb"
    ) == "JP"
```

Add a proxy-runtime test asserting a JP template becomes a GB checkout proxy while `provider_proxy_region == "JP"`.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_paypal_billing_agreement_service.py tests/unit/test_paypal_proxy_service.py -q
```

Expected: GB normalization/default/runtime assertions fail.

- [ ] **Step 3: Implement minimal service changes**

Accept `gb`, default its PM country to JP, add `paypal_ba_mode` to proxy-runtime preparation, and add a tested helper that replaces `region-XX` plus an existing or appended `sid-*` for username-routed proxies.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 command; expect all selected tests to pass.

---

### Task 2: Authenticated GB/JP executor flow

**Files:**
- Modify: `src/autotoken/payments/paypal_bind_executor.py`
- Test: `tests/unit/test_bind_executor.py`

**Interfaces:**
- Produces: `_paypal_pplink_checkout_config("gb")` as GB/GBP/custom with JP billing.
- Produces: authenticated `/backend-api/payments/checkout/update` call using the JP session.
- Consumes: distinct stable GB and JP proxies from Task 1.

- [ ] **Step 1: Write failing executor tests**

Assert the GB config and this exact request order:

```text
GB POST ChatGPT checkout
JP POST ChatGPT checkout/update
JP POST Stripe payment method
JP POST Stripe confirm
GB POST ChatGPT approve
JP GET  Stripe poll
```

Assert update JSON contains `checkout_session_id`, returned `processor_entity`, `chatgptplusplan`, monthly interval, one seat, no discount, and `plus-1-month-free`. The fake redirect must resolve to a `BA-*` token.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_executor.py -k "gb and paypal" -q
```

Expected: GB config/update/stage-routing tests fail.

- [ ] **Step 3: Implement minimal executor changes**

For GB only: derive distinct GB/JP identities; create checkout on GB; update on authenticated JP; run Stripe init/PM/confirm/poll on JP; use JP billing; approve on the original GB session; return only through the strict BA resolver. Return `extract_ba_link_checkout_update` for update transport, HTTP, or `{success: false}` failures.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 command; expect all GB tests to pass.

---

### Task 3: API and UI wiring

**Files:**
- Modify: `src/autotoken/interfaces/api.py`
- Modify: `web/src/components/PayPalPage.vue`
- Test: `tests/unit/test_bind_task_api.py`
- Test: `tests/unit/test_paypal_frontend_options.py`

**Interfaces:**
- API passes `paypal_ba_mode` into proxy-runtime preparation.
- UI exposes `GB 模式（GB/GBP/custom，JP 支付侧）` and forces JP payment country.

- [ ] **Step 1: Write failing tests**

API test assertions:

```python
assert captured["paypal_ba_mode"] == "gb"
assert "region-GB" in captured["proxy_url"]
assert "region-JP" in captured["provider_proxy_url"]
assert captured["payment_method_country"] == "JP"
```

Frontend source test requires the GB option, `gb` cache validation, GB help text, JP option, and watcher assignment to JP.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_task_api.py -k "gb and paypal" tests/unit/test_paypal_frontend_options.py -q
```

- [ ] **Step 3: Implement minimal API/UI changes**

Pass the mode to proxy preparation; add GB selection/help; accept cached `gb`; expose and force JP for GB.

- [ ] **Step 4: Build and verify GREEN**

```powershell
npm --prefix web run build
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_task_api.py -k "gb and paypal" tests/unit/test_paypal_frontend_options.py -q
```

---

### Task 4: Regression and live smoke

**Files:**
- Verify only; do not persist credentials, checkout IDs, proxy IPs, or BA values.

- [ ] **Step 1: Run regression tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_paypal_billing_agreement_service.py tests/unit/test_paypal_proxy_service.py tests/unit/test_bind_executor.py tests/unit/test_bind_task_api.py tests/unit/test_paypal_frontend_options.py -q
```

- [ ] **Step 2: Run lint and whitespace checks**

```powershell
.venv\Scripts\ruff.exe check src/autotoken/services/paypal_billing_agreement.py src/autotoken/services/paypal_proxy.py src/autotoken/services/proxy_runtime.py src/autotoken/payments/paypal_bind_executor.py src/autotoken/interfaces/api.py
git diff --check
```

- [ ] **Step 3: Run one credential-safe live smoke**

Expected summary only:

```text
CHECKOUT_GB ok
UPDATE_JP ok
INIT_JP amount=0 paypal=true
CONFIRM_JP requires_approval
APPROVE_GB approved
POLL_JP redirect=true
RESULT success ba_present=true
```

- [ ] **Step 4: Process 20 real accounts**

After one implemented-path smoke succeeds, run bounded concurrency and report counts only: BA success, non-zero checkout, invalid auth, and other failures.
