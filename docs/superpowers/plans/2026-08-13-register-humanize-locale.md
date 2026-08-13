# Register Humanize And Locale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce registration risk signals by humanizing direct-register browser actions and aligning RoxyBrowser locale/timezone with the selected proxy country.

**Architecture:** Add small helper functions inside the existing direct registration manager for delays, typing, and click pauses without rewriting the flow. Add focused RoxyBrowser locale/timezone payload generation in the Roxy client and pass proxy country from register proxy metadata to profile creation.

**Tech Stack:** Python, Playwright sync API, RoxyBrowser HTTP API, pytest.

## Global Constraints

- Keep changes scoped to registration/RoxyBrowser paths.
- Preserve fallback behavior: if humanized typing fails, fall back to existing `.fill()` / click logic.
- Use environment flags: `REGISTER_HUMANIZE_BROWSER_ACTIONS`, `REGISTER_HUMANIZE_DELAY_FACTOR`, `REGISTER_PROXY_API_COUNTRY`.
- Tests must fail before implementation and pass after.

---

### Task 1: Roxy locale/timezone payload

**Files:**
- Modify: `src/autotoken/integrations/roxybrowser_client.py`
- Test: `tests/unit/test_roxybrowser_client.py`

**Interfaces:**
- Produces: `_roxybrowser_locale_fingerprint(country: str | None) -> dict[str, str]`
- Produces: `RoxyBrowserClient.launch(..., proxy_country: str | None = None)`
- Produces: `RoxyBrowserClient.browser_create(..., proxy_country: str | None = None)`

- [ ] Write failing tests for JP locale/timezone and payload injection.
- [ ] Run tests and verify failure.
- [ ] Implement mapping for JP/US/GB/DE/FR/NL/SG/HK/TW.
- [ ] Run tests and verify pass.

### Task 2: Pass proxy country from register flow to Roxy

**Files:**
- Modify: `src/autotoken/interfaces/manager.py`
- Test: `tests/unit/test_manager_auth_session.py`

**Interfaces:**
- Consumes: `RoxyBrowserClient.launch(proxy_country=...)`
- Produces: `_register_direct_once(..., proxy_country=None)`
- `cmd_register_accounts` passes `register_proxy_meta["proxy_api_country"]` or `REGISTER_PROXY_API_COUNTRY`.

- [ ] Write failing test showing `_register_direct_once` passes `proxy_country="JP"` to Roxy launch.
- [ ] Run test and verify failure.
- [ ] Add parameter plumbing and log fields.
- [ ] Run test and verify pass.

### Task 3: Humanized direct register actions

**Files:**
- Modify: `src/autotoken/interfaces/manager.py`
- Test: `tests/unit/test_codex_oauth_modes.py`

**Interfaces:**
- Produces: `_direct_humanize_enabled() -> bool`
- Produces: `_humanized_fill(page, locator, value: str, *, field_name: str = "") -> None`
- Produces: `_humanized_auth_click(page, anchor_locator, labels) -> None`

- [ ] Write failing tests for humanized fill using click + keyboard typing and fallback to fill.
- [ ] Run tests and verify failure.
- [ ] Implement helpers.
- [ ] Replace email/password/about-you name/age fill and primary button calls.
- [ ] Run tests and verify pass.

### Task 4: Regression verification

**Files:**
- Test: `tests/unit/test_roxybrowser_client.py`
- Test: `tests/unit/test_manager_auth_session.py`
- Test: `tests/unit/test_codex_oauth_modes.py`

- [ ] Run targeted tests.
- [ ] Confirm logs/payloads include locale/timezone and humanize remains fallback-safe.
