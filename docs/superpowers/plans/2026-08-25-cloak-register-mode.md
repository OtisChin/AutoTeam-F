# Cloak Register Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third CloakBrowser-backed headless registration option alongside protocol registration and RoxyBrowser registration.

**Architecture:** Keep the change minimal: add a `use_cloakbrowser` API flag and front-end checkbox, make it mutually exclusive with protocol/Roxy, and route standard registration through a new Cloak launch branch inside the existing Playwright page flow. Reuse current direct-registration page automation and auth_session capture instead of porting Selenium code.

**Tech Stack:** Python/FastAPI/Pydantic, Playwright-compatible `cloakbrowser`, Vue 3.

## Global Constraints

- Do not alter existing protocol or Roxy behavior.
- Cloak is valid only for `registration_flow=standard`; `phone_cpa` keeps existing protocol flow.
- Cloak defaults to headless and supports optional proxy forwarding.
- Preserve backward compatibility for existing `protocol_register` and `use_roxybrowser` payloads.
- Do not stage or commit because the working tree already contains unrelated changes.

---

### Task 1: API accepts mutually exclusive Cloak flag

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/api_routes/account_register_task.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_account_register_task_routes.py`

**Interfaces:**
- Consumes: existing `ManualRegisterParams` request model and `post_add` route.
- Produces: `use_cloakbrowser: bool` passed to `cmd_register_accounts`; `task_params["use_cloakbrowser"]`; `register_mode == "cloak"` when selected.

- [ ] Add failing route test that posts `{use_cloakbrowser: true, protocol_register: true, use_roxybrowser: true}` and asserts Cloak wins with `register_mode="cloak"`, `use_cloakbrowser=True`, `use_roxybrowser=False`.
- [ ] Run the test and verify it fails because `use_cloakbrowser` is not present.
- [ ] Add `use_cloakbrowser` Pydantic field, derive exclusivity, and pass it through `task_params`, `cmd_register_accounts`, and `start_task` metadata.
- [ ] Run the route test and verify it passes.

### Task 2: Manager runs Cloak branch through existing Playwright flow

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/src/autotoken/interfaces/manager.py`
- Create: `D:/code/OpenSource/AutoTeam-F/src/autotoken/integrations/cloakbrowser_runtime.py`
- Test: `D:/code/OpenSource/AutoTeam-F/tests/unit/test_account_register_task_routes.py`

**Interfaces:**
- Consumes: `use_cloakbrowser: bool` passed from router to `cmd_register_accounts` to `create_account_direct` to `_register_direct_once`.
- Produces: `launch_cloakbrowser_context(proxy_url: str | None) -> CloakBrowserRuntime` where runtime has `browser`, `context`, `page`, `close()`.

- [ ] Add failing test that confirms `cmd_register_accounts` receives `use_cloakbrowser=True` from the route.
- [ ] Run the test and verify it fails before implementation.
- [ ] Add `cloakbrowser_runtime.py` helper with env-driven launch settings and clear missing-dependency error.
- [ ] Add `use_cloakbrowser` arguments through manager functions and branch before local Playwright launch.
- [ ] Run targeted route tests and manager import checks.

### Task 3: Frontend exposes minimal checkbox

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`

**Interfaces:**
- Consumes: existing `registerForm` state and payload builder.
- Produces: `registerForm.useCloakBrowser`, localStorage persistence, payload `use_cloakbrowser`.

- [ ] Add checkbox labeled `使用 Cloak 无头模式` under the existing Roxy checkbox.
- [ ] Make protocol/Roxy/Cloak mutually exclusive via existing `@change` handlers.
- [ ] Update behavior summary to display `Cloak 无头注册`.
- [ ] Include `useCloakBrowser` in save/load and request payload.

### Task 4: Configuration and dependency docs

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/pyproject.toml`
- Modify: `D:/code/OpenSource/AutoTeam-F/.env.example`
- Modify: `D:/code/OpenSource/AutoTeam-F/docs/configuration.md`

**Interfaces:**
- Produces env vars: `CLOAK_HEADLESS`, `CLOAK_HUMANIZE`, `CLOAK_GEOIP`, `CLOAK_USE_PROXY`, `CLOAK_LOCALE`, `CLOAK_TIMEZONE`, `CLOAK_LICENSE_KEY`, `CLOAK_FINGERPRINT_SEED`, `CLOAK_USER_DATA_DIR`, `CLOAK_KEEP_BROWSER_OPEN`.

- [ ] Add dependency `cloakbrowser[geoip]>=0.4.10`.
- [ ] Add env examples with safe defaults.
- [ ] Add a short configuration section explaining Cloak mode.
- [ ] Run Python tests relevant to route/model changes.
