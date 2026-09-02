# Protocol Registration 2FA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable official ChatGPT TOTP setup after Python and Go protocol registration without launching a browser.

**Architecture:** Add a small protocol-only executor that reconstructs a first-party HTTP session from saved registration credentials and mirrors the reference project’s reauthentication, enroll, and activation sequence. Route page-less registration results to it while preserving the existing browser executor for live-page modes.

**Tech Stack:** Python 3.10+, curl-cffi session abstraction, pytest, existing local TOTP and account-storage services.

## Global Constraints

- Use only first-party ChatGPT and OpenAI endpoints.
- Do not launch a browser from Python or Go protocol registration.
- Keep successful registration successful when optional 2FA setup fails.
- Never expose raw session tokens, access tokens, or full TOTP secrets in logs or public results.
- Preserve existing uncommitted registration and headless-browser changes.

---

### Task 1: Protocol 2FA executor

**Files:**
- Create: `src/autotoken/services/chatgpt_2fa_protocol.py`
- Create: `tests/unit/test_chatgpt_2fa_protocol.py`

**Interfaces:**
- Consumes: protocol auth-session mappings, an email-code callback, an injectable HTTP-session factory, and the existing TOTP helpers.
- Produces: `ChatGPT2FAProtocolSetupExecutor.enable(email, session_data, progress=None)` returning `ChatGPT2FASetupResult`.

- [ ] Write tests for successful reauthentication/enroll/activation, OTP retry, and missing credentials.
- [ ] Run `python -m pytest tests/unit/test_chatgpt_2fa_protocol.py -q` and confirm the tests fail because the executor does not exist.
- [ ] Implement credential normalization, cookie reconstruction, OpenAI reauthentication, refreshed-token exchange, MFA enrollment, activation, metadata persistence, and masked public results.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Registration manager integration

**Files:**
- Modify: `src/autotoken/interfaces/manager.py`
- Create: `tests/unit/test_protocol_registration_2fa_integration.py`

**Interfaces:**
- Consumes: `ChatGPT2FAProtocolSetupExecutor` and the existing `ProtocolMailAdapter`.
- Produces: protocol registration results containing the same `two_factor` public shape as browser registration.

- [ ] Write tests proving page-less auth sessions use the protocol executor and live pages retain the UI executor.
- [ ] Run the integration tests and confirm the page-less case fails before production changes.
- [ ] Select the executor from `_enable_totp_mfa_after_auth_session` based on whether a live page exists.
- [ ] Pass a recent-auth email-code provider from the shared registration path.
- [ ] Run focused integration tests and confirm they pass.

### Task 3: Verification and rollback artifacts

**Files:**
- Create: `artifacts/protocol-registration-2fa-20260902/MODIFIED_FILE.py`
- Create: `artifacts/protocol-registration-2fa-20260902/DIFF_FILE.patch`
- Create: `artifacts/protocol-registration-2fa-20260902/VERIFICATION.txt`
- Create: `artifacts/protocol-registration-2fa-20260902/ROLLBACK.sh`

**Interfaces:**
- Consumes: the finished source and focused tests.
- Produces: reproducible baseline/modified/rollback evidence while leaving the workspace implementation changed.

- [ ] Run focused unit tests, relevant registration tests, and Ruff on changed Python files.
- [ ] Preserve the original manager hash, create the required modified copy and diff, and write an executable rollback script.
- [ ] Test rollback on a separate copy and verify the original hash is restored there.
- [ ] Reopen all four artifacts and record exact commands, outputs, and exit statuses in `VERIFICATION.txt`.

