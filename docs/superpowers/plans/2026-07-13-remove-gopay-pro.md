# Remove GoPay Pro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the complete GoPay Pro subsystem, API surface, Web UI, tests, configuration, documentation, and local `CNgopay/` data while keeping ordinary GoPay binding and automatic signup fully operational.

**Architecture:** First detach the account-plan verification and access-token normalization helpers that acquired GoPay Pro names but are still consumed by generic CPA export and bind-link APIs. Then remove the dedicated backend and frontend surfaces, delete the standalone `CNgopay/` subsystem and local data, and finish with route, marker, ordinary-GoPay, full-suite, lint, build, and pre-existing-change preservation checks.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, pytest, Ruff, Vue 3, Vite, Node.js, PowerShell, Git.

## Global Constraints

- Preserve `/api/tasks/gopay-bind`, GoPay automatic signup, OTP, reusable-wallet pooling, pending retry, balance polling, Rekberinaja support, and the ordinary GoPay UI.
- Do not retain compatibility routers, feature flags, hidden menu entries, or tombstone handlers for `/api/gopay-pro/*`; removed endpoints must use FastAPI's normal `404` behavior.
- Delete the physical `D:\code\OpenSource\AutoTeam-F\CNgopay` directory, including untracked configs, account pools, tokens, histories, generated binaries, backups, and run data.
- Validate the resolved absolute `CNgopay` target before every recursive deletion.
- Preserve the pre-existing PayPal working-tree changes. Never use `git checkout`, `git restore`, `git reset`, `git clean`, `git add .`, or `git add -A` at repository scope.
- `src/autotoken/interfaces/api.py` and `tests/unit/test_bind_task_api.py` already contain unrelated PayPal changes; stage only removal-specific hunks with `git add -p` and inspect the cached diff before committing.
- Ordinary identifiers such as `gopayProxy*`, `GOPAY_PROTOCOL*`, `GOPAY_PROVIDER*`, Rekberinaja GoPay product IDs, and ordinary `gopay_*` modules are not GoPay Pro markers and must remain.
- Git history is not rewritten. The approved removal design and this implementation plan remain as change records and are excluded from marker scans.
- The approved design is `docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md`.

## File Structure

### Create

- `src/autotoken/services/account_plan_verification.py` — neutral result and auth-refresh payload helpers required by generic CPA export.
- `tests/unit/test_account_plan_verification_service.py` — focused coverage for the neutral helper module.

### Modify

- `src/autotoken/core/normalization.py` — own shared access-token normalization.
- `tests/unit/test_core_normalization.py` — verify access-token cleanup independently of GoPay Pro.
- `src/autotoken/interfaces/api.py` — rename retained generic plan-verification helpers and remove all Pro imports, models, routers, state, script, and batch orchestration.
- `tests/unit/test_api_status.py` — retain generic auth-path/plan verification coverage under neutral names; remove Pro runtime tests.
- `tests/unit/test_bind_task_api.py` — wire CPA export tests to the neutral helper names without staging unrelated PayPal hunks.
- `src/autotoken/services/task_runtime.py` — remove the Pro task group and command mappings.
- `tests/unit/test_task_runtime_service.py` — use the remaining extended-progress `register` command in generic worker-context tests.
- `web/src/api.js` — remove Pro API methods.
- `web/src/App.vue` — remove Pro import, render branch, page key, and task labels.
- `web/src/components/Sidebar.vue` — remove Pro navigation.
- `web/src/components/Dashboard.vue` — remove Pro provider label and style mappings.
- `src/autotoken/_protocol_register/auth_flow.py` — replace the historical CNgopay-specific docstring with neutral flow wording.
- `.gitignore`, `.dockerignore`, `pyproject.toml` — remove exclusions that only exist for the deleted subtree.
- `docs/architecture.md`, `docs/docker.md`, `docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md` — remove statements presenting Pro/CNgopay as present.
- `tests/unit/test_rename_compat.py` — remove packaging and ignore assertions for a directory that no longer exists.
- `docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md` — retain the clarified scan exception for removal records.

### Delete

- `src/autotoken/api_routes/gopay_pro_config.py`
- `src/autotoken/api_routes/gopay_pro_tasks.py`
- `src/autotoken/services/gopay_pro_accounts.py`
- `src/autotoken/services/gopay_pro_events.py`
- `src/autotoken/services/gopay_pro_pool.py`
- `src/autotoken/services/gopay_pro_task_payloads.py`
- `tests/unit/test_gopay_pro_accounts_service.py`
- `tests/unit/test_gopay_pro_config_routes.py`
- `tests/unit/test_gopay_pro_events_service.py`
- `tests/unit/test_gopay_pro_pool_service.py`
- `tests/unit/test_gopay_pro_task_payloads_service.py`
- `tests/unit/test_gopay_pro_task_routes.py`
- `web/src/components/GoPayProPage.vue`
- `CNgopay/` in its entirety, including tracked and untracked contents.

---

### Task 1: Detach Generic Account Verification from GoPay Pro

**Files:**
- Create: `src/autotoken/services/account_plan_verification.py`
- Create: `tests/unit/test_account_plan_verification_service.py`
- Modify: `src/autotoken/core/normalization.py:1-7`
- Modify: `tests/unit/test_core_normalization.py:1-25`
- Modify: `src/autotoken/interfaces/api.py:1823-1824, 2937-3079, 4095-4108`
- Modify: `tests/unit/test_api_status.py:202-291, 635-636`
- Modify: `tests/unit/test_bind_task_api.py:5947-5963`

**Interfaces:**
- Consumes: `_valid_token_item_auth_file(item: dict[str, str]) -> str`, `_trusted_token_auth_path(path: str) -> Path | None`, `_update_account_cpa_auth_plan_type(email: str, *, account: dict | None, plan_type: str) -> dict`, `read_auth_json_file(path: Path) -> dict`.
- Produces: `normalize_access_token(value: Any) -> str`, `_verify_plus_plan(item: dict[str, str]) -> dict`, `_normalize_observed_auth_plan(email: str, auth_file: str, plan_type: str) -> None`, `_mark_account_plan_verification_failed(email: str, *, task_id: str, status: str, message: str, failure_stage: str) -> None`.
- Execution note: Test-first for the new neutral module and normalization helper; characterization/rename for the API wrappers.

- [ ] **Step 1: Snapshot every pre-existing tracked change before touching shared files**

```powershell
New-Item -ItemType Directory -Force .pytest_tmp | Out-Null
$sourceRoot = (Resolve-Path 'D:\code\OpenSource\AutoTeam-F').Path
$changed = git -C $sourceRoot diff --name-only HEAD
git -C $sourceRoot diff --binary HEAD -- $changed |
  Out-File -Encoding utf8NoBOM .pytest_tmp/remove-gopay-pro-preexisting.patch
Get-FileHash (Join-Path $sourceRoot 'docs/superpowers/plans/2026-07-13-paypal-gb-ba-extraction.md') -Algorithm SHA256 |
  Select-Object -ExpandProperty Hash |
  Set-Content -Encoding ascii .pytest_tmp/remove-gopay-pro-paypal-plan.sha256
```

Expected: `.pytest_tmp/remove-gopay-pro-preexisting.patch` is non-empty and the SHA-256 file contains one hash line.

- [ ] **Step 2: Write failing tests for neutral token and plan-verification helpers**

Update `tests/unit/test_core_normalization.py` imports and add:

```python
from autotoken.core.normalization import normalize_access_token, normalized_email


def test_normalize_access_token_handles_json_bearer_and_trailing_delimiters():
    assert normalize_access_token('{"accessToken":"json-token"}') == "json-token"
    assert normalize_access_token("Bearer bearer-token,") == "bearer-token"
    assert normalize_access_token("new-access,") == "new-access"
    assert normalize_access_token("token-ending-in-s") == "token-ending-in-s"
    assert normalize_access_token(None) == ""
```

Create `tests/unit/test_account_plan_verification_service.py`:

```python
from autotoken.services import account_plan_verification


def test_verification_failure_fields_are_provider_neutral():
    fields = account_plan_verification.verification_failure_update_fields(
        task_id="export-cpa-auths",
        status="pending_manual",
        message="plan not confirmed",
        failure_stage="export_plan_verify",
        marked_at=123.0,
    )

    assert fields == {
        "last_bind_status": "pending_manual",
        "last_bind_at": 123.0,
        "last_bind_task_id": "export-cpa-auths",
        "last_bind_message": "plan not confirmed",
        "last_bind_failure_stage": "export_plan_verify",
    }


def test_refreshed_auth_data_updates_compatible_token_fields():
    result = account_plan_verification.refreshed_auth_data(
        {"email": "user@example.com", "access_token": "old"},
        {
            "access_token": "Bearer new-token,",
            "refresh_token": "refresh-new",
            "id_token": "id-new",
            "expires_in": 60,
        },
        now=1000.0,
    )

    assert result["access_token"] == "new-token"
    assert result["accessToken"] == "new-token"
    assert result["refresh_token"] == "refresh-new"
    assert result["refreshToken"] == "refresh-new"
    assert result["id_token"] == "id-new"
    assert result["idToken"] == "id-new"
    assert result["expired"] == "1970-01-01T00:17:40Z"
    assert result["last_refresh"] == "1970-01-01T00:16:40Z"


def test_refreshed_auth_data_skips_missing_tokens_and_invalid_expiry():
    result = account_plan_verification.refreshed_auth_data(
        {"access_token": "old", "refresh_token": "old-refresh"},
        {"expires_in": "invalid"},
        now=0,
    )

    assert result["access_token"] == "old"
    assert result["refresh_token"] == "old-refresh"
    assert "expired" not in result
    assert result["last_refresh"] == "1970-01-01T00:00:00Z"


def test_usage_probe_result_helpers_keep_existing_response_contracts():
    assert account_plan_verification.usage_probe_missing_token_result() == {
        "status": "missing_token",
        "plan_type": "",
        "message": "缺少 access_token",
    }
    assert account_plan_verification.plus_plan_auth_file_read_error_result(ValueError("invalid json")) == {
        "ok": False,
        "plan_type": "",
        "message": "CPA auth 文件读取失败: invalid json",
    }
    assert account_plan_verification.usage_probe_exception_result(
        kind="网络异常",
        error=RuntimeError("timeout"),
    ) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 网络异常: timeout",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=401) == {
        "status": "auth_error",
        "plan_type": "",
        "message": "wham/usage token 无效 HTTP 401",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=429) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage 临时错误 HTTP 429",
    }
    assert account_plan_verification.usage_probe_http_result(status_code=418, text="x" * 200) == {
        "status": "network_error",
        "plan_type": "",
        "message": f"wham/usage 非预期 HTTP 418: {'x' * 160}",
    }
    assert account_plan_verification.usage_probe_json_error_result(ValueError("bad json")) == {
        "status": "network_error",
        "plan_type": "",
        "message": "wham/usage JSON 解析失败: bad json",
    }
    assert account_plan_verification.usage_probe_ok_result(" PLUS ") == {
        "status": "ok",
        "plan_type": "plus",
        "message": "wham/usage plan_type=plus",
    }
    assert account_plan_verification.usage_probe_ok_result("")["message"] == "wham/usage plan_type=unknown"


def test_plus_plan_result_helpers_keep_existing_response_contracts():
    assert account_plan_verification.plus_plan_verified_result(" PLUS ") == {
        "ok": True,
        "plan_type": "plus",
        "message": "OpenAI 已确认 plan_type=plus",
    }
    assert account_plan_verification.plus_plan_refresh_exception_probe(
        {"status": "", "message": "wham/usage plan_type=free"},
        plan_type=" FREE ",
        error=RuntimeError("refresh failed"),
    ) == {
        "status": "refresh_error",
        "plan_type": "free",
        "message": "wham/usage plan_type=free; refresh 异常: refresh failed",
    }
    assert account_plan_verification.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"status": "ok", "plan_type": "free", "message": "ignored"},
    ) == {
        "ok": False,
        "plan_type": "free",
        "message": "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效",
        "email": "user@example.com",
    }
    assert account_plan_verification.plus_plan_unverified_result(
        email="user@example.com",
        last_probe={"plan_type": "", "message": ""},
    ) == {
        "ok": False,
        "plan_type": "",
        "message": "OpenAI Plus 状态未确认",
        "email": "user@example.com",
    }
```

- [ ] **Step 3: Run the new tests and verify RED**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_core_normalization.py tests/unit/test_account_plan_verification_service.py -q
```

Expected: collection fails because `normalize_access_token` and `autotoken.services.account_plan_verification` do not exist.

- [ ] **Step 4: Add shared access-token normalization**

Replace `src/autotoken/core/normalization.py` with:

```python
"""Small normalization helpers shared across account and API code."""

import json
import re
from typing import Any


def normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_access_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and "accessToken" in raw:
        try:
            parsed = json.loads(raw)
            token = parsed.get("accessToken") if isinstance(parsed, dict) else ""
            if token:
                raw = str(token).strip()
        except Exception:
            pass
    raw = re.sub(r"^Bearer\s+", "", raw, flags=re.IGNORECASE).strip()
    return re.sub(r"^[\"']+|[\"',;\s]+$", "", raw).strip()
```

- [ ] **Step 5: Create the neutral plan-verification helper module**

Create `src/autotoken/services/account_plan_verification.py`:

```python
"""Provider-neutral account-plan verification payload helpers."""

from __future__ import annotations

import time
from typing import Any

from autotoken.core.normalization import normalize_access_token


def verification_failure_update_fields(
    *,
    task_id: str,
    status: str,
    message: str,
    failure_stage: str,
    marked_at: float,
) -> dict[str, Any]:
    return {
        "last_bind_status": status,
        "last_bind_at": marked_at,
        "last_bind_task_id": task_id,
        "last_bind_message": message,
        "last_bind_failure_stage": failure_stage,
    }


def refreshed_auth_data(auth_data: dict[str, Any], refreshed: dict[str, Any], *, now: float) -> dict[str, Any]:
    next_data = dict(auth_data)
    access_token = normalize_access_token(refreshed.get("access_token") or "")
    refresh_token = str(refreshed.get("refresh_token") or "").strip()
    id_token = str(refreshed.get("id_token") or "").strip()
    if access_token:
        next_data["access_token"] = access_token
        next_data["accessToken"] = access_token
    if refresh_token:
        next_data["refresh_token"] = refresh_token
        next_data["refreshToken"] = refresh_token
    if id_token:
        next_data["id_token"] = id_token
        next_data["idToken"] = id_token
    try:
        expires_at = now + max(0, int(refreshed.get("expires_in") or 0))
    except Exception:
        expires_at = 0
    if expires_at:
        next_data["expired"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at))
    next_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    return next_data


def usage_probe_missing_token_result() -> dict[str, str]:
    return {"status": "missing_token", "plan_type": "", "message": "缺少 access_token"}


def plus_plan_auth_file_read_error_result(error: Any) -> dict[str, Any]:
    return {"ok": False, "plan_type": "", "message": f"CPA auth 文件读取失败: {error}"}


def usage_probe_exception_result(*, kind: str, error: Any) -> dict[str, str]:
    return {"status": "network_error", "plan_type": "", "message": f"wham/usage {kind}: {error}"}


def usage_probe_http_result(*, status_code: int, text: str = "") -> dict[str, str]:
    if status_code in (401, 403):
        return {"status": "auth_error", "plan_type": "", "message": f"wham/usage token 无效 HTTP {status_code}"}
    if status_code == 429 or 500 <= status_code < 600:
        return {"status": "network_error", "plan_type": "", "message": f"wham/usage 临时错误 HTTP {status_code}"}
    return {
        "status": "network_error",
        "plan_type": "",
        "message": f"wham/usage 非预期 HTTP {status_code}: {str(text or '')[:160]}",
    }


def usage_probe_json_error_result(error: Any) -> dict[str, str]:
    return {"status": "network_error", "plan_type": "", "message": f"wham/usage JSON 解析失败: {error}"}


def usage_probe_ok_result(plan_type: str) -> dict[str, str]:
    normalized_plan_type = str(plan_type or "").strip().lower()
    return {
        "status": "ok",
        "plan_type": normalized_plan_type,
        "message": f"wham/usage plan_type={normalized_plan_type or 'unknown'}",
    }


def plus_plan_verified_result(plan_type: str) -> dict[str, Any]:
    normalized_plan_type = str(plan_type or "").strip().lower()
    return {
        "ok": True,
        "plan_type": normalized_plan_type,
        "message": f"OpenAI 已确认 plan_type={normalized_plan_type}",
    }


def plus_plan_refresh_exception_probe(last_probe: dict[str, Any], *, plan_type: str, error: Any) -> dict[str, Any]:
    return {
        "status": last_probe.get("status") or "refresh_error",
        "plan_type": str(plan_type or "").strip().lower(),
        "message": f"{last_probe.get('message')}; refresh 异常: {error}",
    }


def plus_plan_unverified_result(*, email: str, last_probe: dict[str, Any]) -> dict[str, Any]:
    plan_type = str(last_probe.get("plan_type") or "").strip().lower()
    message = (
        "OpenAI wham/usage 仍返回 plan_type=free，未确认 Plus 生效"
        if plan_type == "free"
        else str(last_probe.get("message") or "OpenAI Plus 状态未确认")
    )
    return {"ok": False, "plan_type": plan_type, "message": message, "email": email}
```

- [ ] **Step 6: Rename the retained API helpers and detach them from Pro services**

Add these imports in `src/autotoken/interfaces/api.py`:

```python
from autotoken.core.normalization import normalize_access_token as _core_normalize_access_token
from autotoken.services import account_plan_verification as account_plan_verification_service
```

Keep the existing `_normalize_access_token` compatibility entry point but change its body:

```python
def _normalize_access_token(raw_value: str) -> str:
    return _core_normalize_access_token(raw_value)
```

Rename the retained functions and update their bodies to use the neutral service:

```python
def _mark_account_plan_verification_failed(
    email: str,
    *,
    task_id: str,
    status: str,
    message: str,
    failure_stage: str,
) -> None:
    from autotoken.storage.accounts import update_account

    normalized = _normalized_email(email)
    if not normalized:
        return
    update_account(
        normalized,
        **account_plan_verification_service.verification_failure_update_fields(
            task_id=task_id,
            status=status,
            message=message,
            failure_stage=failure_stage,
            marked_at=time.time(),
        ),
    )


def _probe_openai_plan(access_token: str, account_id: str = "", *, timeout: float = 25.0) -> dict:
    token = _normalize_access_token(access_token)
    if not token:
        return account_plan_verification_service.usage_probe_missing_token_result()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    account_id = str(account_id or "").strip()
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id
    try:
        response = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            params={"account_id": account_id} if account_id else None,
            timeout=max(5.0, float(timeout or 25.0)),
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="网络异常", error=exc)
    except requests.exceptions.RequestException as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="请求异常", error=exc)
    except Exception as exc:
        return account_plan_verification_service.usage_probe_exception_result(kind="未知异常", error=exc)
    if response.status_code != 200:
        return account_plan_verification_service.usage_probe_http_result(
            status_code=response.status_code,
            text=response.text,
        )
    try:
        payload = response.json()
    except Exception as exc:
        return account_plan_verification_service.usage_probe_json_error_result(exc)
    return account_plan_verification_service.usage_probe_ok_result(
        str((payload or {}).get("plan_type") or "").strip().lower()
    )


def _save_refreshed_auth_file(auth_file: str, auth_data: dict, refreshed: dict) -> None:
    path = _trusted_token_auth_path(auth_file)
    if not path or not isinstance(auth_data, dict) or not isinstance(refreshed, dict):
        return
    next_data = account_plan_verification_service.refreshed_auth_data(auth_data, refreshed, now=time.time())
    path.write_text(json.dumps(next_data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from autotoken.storage.auth_index import upsert_codex_auth_file
        from autotoken.storage.auth_storage import ensure_auth_file_permissions

        ensure_auth_file_permissions(path)
        upsert_codex_auth_file(path, next_data, main=path.name.startswith("codex-main-"))
    except Exception as exc:
        logger.warning("[account-plan] refreshed CPA auth index update failed: %s", exc)


def _verify_plus_plan(item: dict[str, str]) -> dict:
    email = str(item.get("email") or "").strip()
    auth_file = _valid_token_item_auth_file(item)
    auth_data: dict[str, Any] = {}
    if auth_file:
        try:
            auth_path = _trusted_token_auth_path(auth_file)
            if auth_path:
                auth_data = read_auth_json_file(auth_path)
        except Exception as exc:
            return account_plan_verification_service.plus_plan_auth_file_read_error_result(exc)
    access_token = _normalize_access_token(
        item.get("access_token") or auth_data.get("access_token") or auth_data.get("accessToken") or ""
    )
    refresh_token = str(
        item.get("refresh_token") or auth_data.get("refresh_token") or auth_data.get("refreshToken") or ""
    ).strip()
    account_id = str(item.get("account_id") or auth_data.get("account_id") or auth_data.get("accountId") or "").strip()
    attempts = max(1, int(_env_float("OPENAI_PLAN_VERIFY_ATTEMPTS", 3)))
    wait_seconds = max(0.0, _env_float("OPENAI_PLAN_VERIFY_INTERVAL_SECONDS", 5.0))
    refreshed_once = False
    last_probe: dict = account_plan_verification_service.usage_probe_missing_token_result()

    for attempt in range(1, attempts + 1):
        last_probe = _probe_openai_plan(access_token, account_id)
        plan_type = str(last_probe.get("plan_type") or "").strip().lower()
        if plan_type in {"plus", "pro"}:
            return account_plan_verification_service.plus_plan_verified_result(plan_type)
        if refresh_token and not refreshed_once:
            refreshed_once = True
            try:
                from autotoken.auth.codex_auth import refresh_access_token

                refreshed = refresh_access_token(refresh_token)
            except Exception as exc:
                refreshed = None
                last_probe = account_plan_verification_service.plus_plan_refresh_exception_probe(
                    last_probe,
                    plan_type=plan_type,
                    error=exc,
                )
            if refreshed and refreshed.get("access_token"):
                access_token = _normalize_access_token(refreshed.get("access_token") or access_token)
                refresh_token = str(refreshed.get("refresh_token") or refresh_token)
                _save_refreshed_auth_file(auth_file, auth_data, refreshed)
                continue
        if attempt < attempts and wait_seconds > 0:
            time.sleep(wait_seconds)
    return account_plan_verification_service.plus_plan_unverified_result(email=email, last_probe=last_probe)


def _normalize_observed_auth_plan(email: str, auth_file: str, plan_type: str) -> None:
    observed_plan = str(plan_type or "").strip().lower()
    if observed_plan not in {"free", "plus", "pro", "team"}:
        return
    try:
        _update_account_cpa_auth_plan_type(
            email,
            account={"auth_file": auth_file},
            plan_type=observed_plan,
        )
    except Exception:
        logger.warning(
            "[account-plan] observed auth plan sync failed: email=%s plan=%s",
            _safe_email_summary(email),
            observed_plan,
            exc_info=True,
        )
```

Update the generic CPA router wiring to:

```python
        verify_plus_plan=_verify_plus_plan,
        normalize_observed_auth_plan=_normalize_observed_auth_plan,
        mark_failed_account=_mark_account_plan_verification_failed,
```

Until Task 2 deletes the Pro batch block, update its internal calls to the same neutral names so the module imports during the transition.

- [ ] **Step 7: Rename the retained API tests and environment keys**

Apply this exact mapping in `tests/unit/test_api_status.py` and `tests/unit/test_bind_task_api.py`:

```text
_gopay_pro_probe_openai_plan              -> _probe_openai_plan
_gopay_pro_save_refreshed_auth_file       -> _save_refreshed_auth_file
_gopay_pro_verify_plus_plan               -> _verify_plus_plan
_gopay_pro_normalize_observed_auth_plan   -> _normalize_observed_auth_plan
_mark_gopay_pro_failed_account            -> _mark_account_plan_verification_failed
GOPAY_PRO_PLUS_VERIFY_ATTEMPTS             -> OPENAI_PLAN_VERIFY_ATTEMPTS
GOPAY_PRO_PLUS_VERIFY_INTERVAL_SECONDS     -> OPENAI_PLAN_VERIFY_INTERVAL_SECONDS
```

Rename the four retained test functions to `test_verify_plus_plan_*` and `test_save_refreshed_auth_file_*`. Do not rename or preserve Pro script, pool, slot, batch, event, or success-account tests; Task 2 deletes those.

- [ ] **Step 8: Run focused tests and verify GREEN**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_core_normalization.py tests/unit/test_account_plan_verification_service.py tests/unit/test_api_status.py -k "normalize_access_token or verify_plus_plan or save_refreshed_auth_file" -q
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_task_api.py -k "export_account_cpa_auths" -q
.venv\Scripts\ruff.exe check src/autotoken/core/normalization.py src/autotoken/services/account_plan_verification.py src/autotoken/interfaces/api.py tests/unit/test_core_normalization.py tests/unit/test_account_plan_verification_service.py tests/unit/test_api_status.py tests/unit/test_bind_task_api.py
```

Expected: all selected tests pass and Ruff reports no errors in the changed code.

- [ ] **Step 9: Commit only the neutralization changes**

```powershell
git add -- src/autotoken/core/normalization.py src/autotoken/services/account_plan_verification.py tests/unit/test_core_normalization.py tests/unit/test_account_plan_verification_service.py tests/unit/test_api_status.py
git add -p -- src/autotoken/interfaces/api.py tests/unit/test_bind_task_api.py
git diff --cached --check
git diff --cached
git commit -m "refactor(accounts): detach plan verification from GoPay Pro"
```

Expected cached diff: neutral account/token changes only; no PayPal GB, billing-agreement, proxy, or PayPal UI hunks.

---

### Task 2: Remove the GoPay Pro Backend and Task Runtime

**Files:**
- Delete: `src/autotoken/api_routes/gopay_pro_config.py`
- Delete: `src/autotoken/api_routes/gopay_pro_tasks.py`
- Delete: `src/autotoken/services/gopay_pro_accounts.py`
- Delete: `src/autotoken/services/gopay_pro_events.py`
- Delete: `src/autotoken/services/gopay_pro_pool.py`
- Delete: `src/autotoken/services/gopay_pro_task_payloads.py`
- Delete: `tests/unit/test_gopay_pro_accounts_service.py`
- Delete: `tests/unit/test_gopay_pro_config_routes.py`
- Delete: `tests/unit/test_gopay_pro_events_service.py`
- Delete: `tests/unit/test_gopay_pro_pool_service.py`
- Delete: `tests/unit/test_gopay_pro_task_payloads_service.py`
- Delete: `tests/unit/test_gopay_pro_task_routes.py`
- Modify: `src/autotoken/interfaces/api.py:1-305, 2469-4068`
- Modify: `src/autotoken/services/task_runtime.py:17-48`
- Modify: `tests/unit/test_api_status.py:168-199, 473-884`
- Modify: `tests/unit/test_task_runtime_service.py:986-1080`

**Interfaces:**
- Consumes: neutral `_verify_plus_plan`, `_normalize_observed_auth_plan`, `_mark_account_plan_verification_failed`, and `_normalize_access_token` produced by Task 1.
- Produces: a backend with no Pro imports, models, routers, task groups, script runners, batch orchestration, or dedicated services; ordinary GoPay routes remain registered.
- Execution note: Characterization-first deletion. Existing ordinary GoPay and generic account tests are the regression boundary.

- [ ] **Step 1: Record the current route boundary and run ordinary GoPay characterization tests**

```powershell
@'
from autotoken.interfaces.api import app

paths = {getattr(route, "path", "") for route in app.routes}
assert "/api/gopay-pro/status" in paths
assert "/api/gopay-pro/batch" in paths
assert "/api/tasks/gopay-bind" in paths
assert "/api/config/gopay-auto-signup" in paths
print("pre-removal route characterization passed")
'@ | .venv\Scripts\python.exe -

.venv\Scripts\python.exe -m pytest tests/unit/test_gopay_auto_signup_config_routes.py tests/unit/test_gopay_runtime_service.py tests/unit/test_gopay_wallet_pool_service.py tests/unit/test_gopay_pending_retry_service.py tests/unit/test_gopay_task_payloads_service.py -q
```

Expected: route characterization and ordinary GoPay service tests pass before deletion.

- [ ] **Step 2: Remove all Pro imports, exported models, and service aliases from `api.py`**

Delete:

```text
_GoPayProConfigParams
_GoPayProNumbersParams
_GoPayProSlotParams
_GoPayProTaskParams
_GoPayProBatchParams
create_gopay_pro_config_router
create_gopay_pro_tasks_router
gopay_pro_accounts_service
gopay_pro_events_service
gopay_pro_pool_service
gopay_pro_task_payloads_service
GoPayProConfigParams
GoPayProNumbersParams
GoPayProSlotParams
GoPayProTaskParams
GoPayProBatchParams
```

Remove the top-level `subprocess` import and the five `autotoken.core.files` imports (`active_non_comment_lines`, `append_unique_non_comment_lines`, `read_json_file`, `read_lines_file`, `write_json_atomic`) after confirming Ruff sees no remaining callers.

- [ ] **Step 3: Delete the complete Pro composition and orchestration surface from `api.py`**

Delete every definition and router alias whose name starts with one of these prefixes:

```text
_GOPAY_PRO_
_gopay_pro_
_mark_gopay_pro_
_run_gopay_pro_
start_gopay_pro_
get_gopay_pro_
update_gopay_pro_
import_gopay_pro_
```

Also delete the Pro-only helpers `_read_json_file`, `_write_json_atomic`, `_read_lines_file`, `_active_pool_lines`, `_append_unique_pool_lines`, `_mark_gopay_pro_success_account`, and `_gopay_pro_account_token_items`.

Retain the neutral Task 1 functions and keep the generic CPA router registration in this final shape:

```python
app.include_router(
    create_account_cpa_auths_router(
        normalize_email=_normalized_email,
        resolve_codex_auth_file=_resolve_codex_auth_file,
        update_account_cpa_auth_plan_type=_update_account_cpa_auth_plan_type,
        convert_account_auth_session_to_cpa_auth=_convert_account_auth_session_to_cpa_auth,
        is_main_account_email=_is_main_account_email,
        verify_plus_plan=_verify_plus_plan,
        normalize_observed_auth_plan=_normalize_observed_auth_plan,
        mark_failed_account=_mark_account_plan_verification_failed,
        safe_email_summary=_safe_email_summary,
        current_time=time.time,
    )
)
```

- [ ] **Step 4: Remove Pro task-runtime classification**

In `src/autotoken/services/task_runtime.py`, remove `TASK_GROUP_GOPAY_PRO` and the two command mappings, leaving:

```python
TASK_GROUP_GOPAY = "gopay"
TASK_GROUP_PAYPAL = "paypal"

COMMAND_TASK_GROUP = {
    "register": TASK_GROUP_REGISTER,
    "add": TASK_GROUP_REGISTER,
    "bind-card": TASK_GROUP_BIND_CARD,
    "gopay-bind": TASK_GROUP_GOPAY,
    "paypal": TASK_GROUP_PAYPAL,
    "login": TASK_GROUP_OAUTH,
    "login-batch": TASK_GROUP_OAUTH,
    "refresh-quota": TASK_GROUP_QUOTA,
    "check": TASK_GROUP_QUOTA,
    "rotate": TASK_GROUP_TEAM,
    "replace": TASK_GROUP_TEAM,
    "fill": TASK_GROUP_TEAM,
    "fill-personal": TASK_GROUP_TEAM,
    "cleanup": TASK_GROUP_TEAM,
}

EXTENDED_PROGRESS_COMMANDS = {"register"}
```

- [ ] **Step 5: Delete dedicated modules and behavior tests**

Delete the six dedicated source modules and six dedicated test modules listed in this task's Files section.

From `tests/unit/test_api_status.py`, delete exactly these Pro-only definitions:

```text
test_gopay_pro_account_token_items_ignores_session_file_outside_session_dir
test_gopay_pro_paths_uses_default_pool_paths_for_oversized_config
_write_gopay_pro_root
test_gopay_pro_script_runner_supports_new_maintenance_commands
test_gopay_pro_script_args_reject_command_interpreter_characters
test_gopay_pro_register_detects_waf_and_sets_cooldown
test_gopay_pro_register_ratelimit_moves_number_to_cooldown
test_gopay_pro_checkout_401_is_terminal_event
test_gopay_pro_midtrans_charge_202_marks_slot
test_gopay_pro_harvest_progress_prints_email_for_success
test_gopay_pro_batch_aborts_after_register_waf_without_harvest
test_gopay_pro_batch_runs_refresh_and_fix_failed_before_harvest
test_mark_gopay_pro_success_account_ignores_auth_file_outside_auth_dir
test_mark_gopay_pro_success_account_accepts_auth_file_inside_auth_dir
```

Keep the neutral `test_verify_plus_plan_*`, `test_save_refreshed_auth_file_*`, and `test_normalize_access_token_*` coverage from Task 1.

In the three generic worker-context tests in `tests/unit/test_task_runtime_service.py`, replace only the sample command value:

```python
"command": "gopay-pro"
```

with:

```python
"command": "register"
```

- [ ] **Step 6: Verify the removed route surface and retained ordinary routes**

```powershell
@'
from autotoken.interfaces.api import app

paths = {getattr(route, "path", "") for route in app.routes}
assert not any(path.startswith("/api/gopay-pro") for path in paths)
assert "/api/tasks/gopay-bind" in paths
assert "/api/config/gopay-auto-signup" in paths
assert "/api/tasks/gopay/runtime-control" in paths
print("removed routes absent; ordinary GoPay routes retained")
'@ | .venv\Scripts\python.exe -

.venv\Scripts\python.exe -m pytest tests/unit/test_core_normalization.py tests/unit/test_account_plan_verification_service.py tests/unit/test_api_status.py tests/unit/test_task_runtime_service.py -q
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_task_api.py -k "gopay or export_account_cpa_auths" -q
.venv\Scripts\python.exe -m pytest tests/unit/test_gopay_auto_signup_config_routes.py tests/unit/test_gopay_runtime_service.py tests/unit/test_gopay_wallet_pool_service.py tests/unit/test_gopay_pending_retry_service.py tests/unit/test_gopay_task_payloads_service.py -q
.venv\Scripts\ruff.exe check src/autotoken/interfaces/api.py src/autotoken/services/task_runtime.py src/autotoken/services/account_plan_verification.py tests/unit/test_api_status.py tests/unit/test_task_runtime_service.py
```

Expected: the import smoke prints success, all selected tests pass, and Ruff reports no errors.

- [ ] **Step 7: Commit only backend-removal hunks**

```powershell
git add -- src/autotoken/services/task_runtime.py src/autotoken/services/account_plan_verification.py tests/unit/test_api_status.py tests/unit/test_task_runtime_service.py
git add -u -- src/autotoken/api_routes/gopay_pro_config.py src/autotoken/api_routes/gopay_pro_tasks.py src/autotoken/services/gopay_pro_accounts.py src/autotoken/services/gopay_pro_events.py src/autotoken/services/gopay_pro_pool.py src/autotoken/services/gopay_pro_task_payloads.py tests/unit/test_gopay_pro_accounts_service.py tests/unit/test_gopay_pro_config_routes.py tests/unit/test_gopay_pro_events_service.py tests/unit/test_gopay_pro_pool_service.py tests/unit/test_gopay_pro_task_payloads_service.py tests/unit/test_gopay_pro_task_routes.py
git add -p -- src/autotoken/interfaces/api.py
git diff --cached --check
git diff --cached
git commit -m "refactor(api): remove GoPay Pro backend"
```

Expected cached diff: no PayPal changes; all deleted modules are Pro-dedicated; ordinary GoPay modules remain.

---

### Task 3: Remove the GoPay Pro Web Surface

**Files:**
- Delete: `web/src/components/GoPayProPage.vue`
- Modify: `web/src/api.js:173-178`
- Modify: `web/src/App.vue:60-64, 145-173, 315-320`
- Modify: `web/src/components/Sidebar.vue:68-74`
- Modify: `web/src/components/Dashboard.vue:1854-1882`

**Interfaces:**
- Consumes: current Vue page validation based on `PAGE_KEYS`.
- Produces: no Pro component, API method, page key, task label, navigation entry, or dashboard provider mapping; stale saved page values fall back to `dashboard`.
- Execution note: Characterization-first deletion with a production build and exact source scan.

- [ ] **Step 1: Build the current frontend before deleting the page**

```powershell
npm --prefix web run build
node web/scripts/test-gopay-board.mjs
```

Expected: Vite build and the ordinary GoPay board script pass before removal.

- [ ] **Step 2: Delete the component and remove every caller**

Delete `web/src/components/GoPayProPage.vue`.

Remove these methods from the exported `api` object in `web/src/api.js`:

```javascript
getGoPayProStatus
saveGoPayProConfig
importGoPayProNumbers
updateGoPayProSlot
startGoPayProTask
startGoPayProBatch
```

In `web/src/App.vue`:

- Delete the `GoPayProPage` import.
- Delete the `currentPage === 'gopayPro'` render branch.
- Remove `'gopayPro'` from `PAGE_KEYS`.
- Delete the `'gopay-pro'` and `'gopay-pro-batch'` entries from the task-name map.

The surrounding render sequence must become:

```vue
<BindCard v-else-if="currentPage === 'gopay'" key="gopay" initial-tab="gopay" standalone @refresh="refresh" />
<IdealLinkPage v-else-if="currentPage === 'ideal'" />
```

In `web/src/components/Sidebar.vue`, delete only:

```javascript
{ key: 'gopayPro', group: 'Payments', glyph: 'G+', label: 'GoPay Pro', mobileLabel: 'GoPay Pro' },
```

In `web/src/components/Dashboard.vue`, delete only the `gopay_pro` entries from the provider-name and provider-class maps. Keep the ordinary `gopay` entries.

- [ ] **Step 3: Verify no Web source references remain and rebuild**

```powershell
$pattern = '(?i)gopay_pro(?:_|\b)|gopay-pro(?:-|\b)|GoPay Pro'
$hits = rg -n --pcre2 $pattern web/src
if ($LASTEXITCODE -eq 0) { throw "removed Web markers remain:`n$hits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
$camelHits = rg -n --pcre2 'GoPayPro[A-Z]|\bgopayPro\b' web/src
if ($LASTEXITCODE -eq 0) { throw "removed Web camel-case markers remain:`n$camelHits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }

npm --prefix web run build
node web/scripts/test-gopay-board.mjs
node web/scripts/test-bind-link-payload.mjs
```

Expected: both marker scans return no matches, the production build succeeds, and both existing Node scripts pass.

- [ ] **Step 4: Commit the Web removal**

```powershell
git add -- web/src/api.js web/src/App.vue web/src/components/Sidebar.vue web/src/components/Dashboard.vue
git add -u -- web/src/components/GoPayProPage.vue
git diff --cached --check
git diff --cached
git commit -m "refactor(web): remove GoPay Pro UI"
```

Expected cached diff: only Pro UI/API presentation is removed; ordinary GoPay and PayPal pages remain.

---

### Task 4: Delete CNgopay Data and Remove Packaging, Ignore, Test, and Documentation Residue

**Files:**
- Delete: `CNgopay/**`
- Modify: `.gitignore:78-81`
- Modify: `.dockerignore:68-93`
- Modify: `pyproject.toml:43`
- Modify: `src/autotoken/_protocol_register/auth_flow.py:1033-1035`
- Modify: `docs/architecture.md:82-86`
- Modify: `docs/docker.md:72-76`
- Modify: `docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md` at every exact removed-feature marker line
- Modify: `tests/unit/test_rename_compat.py:651-697, 976-1011, 1057-1157, 1350-1385`

**Interfaces:**
- Consumes: the backend and Web no longer reference the standalone directory after Tasks 2 and 3.
- Produces: no physical `CNgopay/` directory, no packaging/ignore rule for it, no current architecture claim, and no obsolete compatibility-test expectation.
- Execution note: Pure deletion/configuration work. Use exact-path safety checks rather than test-first code changes.

- [ ] **Step 1: Remove CNgopay-specific packaging and ignore entries**

Delete:

```text
.gitignore: CNgopay/runs/, CNgopay/**/node_modules/, CNgopay/**/.vite/, CNgopay/**/*.tsbuildinfo
.dockerignore: the complete contiguous CNgopay block from CNgopay/runs/ through CNgopay/codex_register/bundle/
pyproject.toml: the "/CNgopay" sdist exclusion
```

Do not remove root-level binary ignore rules such as `pool.exe`, `pool-linux-x64`, `pool-mac-arm64`, or `pool-mac-intel`; those are separate local-artifact guards.

- [ ] **Step 2: Remove CNgopay expectations from rename/package safety tests**

In `tests/unit/test_rename_compat.py`:

- Remove `"/CNgopay"` from the expected Hatch sdist exclusion set.
- Remove the `CNgopay/codex_register/dist/` and `CNgopay/codex_register/bundle/` tracked-file offender patterns.
- Remove every `CNgopay/...` path from the Git-ignore probe list.
- Remove every `CNgopay/...` entry from the required `.dockerignore` pattern set.
- Remove `r"(^|/)CNgopay/"` from built-artifact forbidden patterns.
- Keep the generic secret/runtime/log/database/node_modules and root-binary checks.

- [ ] **Step 3: Clean source and documentation references**

Replace the docstring in `src/autotoken/_protocol_register/auth_flow.py` with:

```python
"""Bind an email during Codex OAuth after the phone verification step."""
```

Delete the two CNgopay rows from `docs/architecture.md`. Rewrite the Docker sentence as:

```markdown
`.dockerignore` 已排除本地密钥、日志、输出、账号池、`node_modules` 和本地构建产物。构建镜像前仍建议检查：
```

Remove every full bullet line in `docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md` that matches the exact removed-feature markers. Use this deterministic PowerShell transform:

```powershell
$path = 'docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md'
$pattern = '(?i)gopay_pro(?:_|\b)|gopay-pro(?:-|\b)|CNGOPAY(?:_|\b)|CNgopay|GoPay Pro'
$kept = Get-Content -LiteralPath $path | Where-Object { $_ -notmatch $pattern }
[IO.File]::WriteAllLines((Resolve-Path -LiteralPath $path), $kept, [Text.UTF8Encoding]::new($false))
```

Expected: removal/change-record documents still mention the removed subsystem; the older architecture plan no longer presents or inventories it.

- [ ] **Step 4: Physically delete every active CNgopay directory using verified absolute paths**

```powershell
$roots = @((Resolve-Path .).Path, (Resolve-Path 'D:\code\OpenSource\AutoTeam-F').Path) |
  Select-Object -Unique

foreach ($root in $roots) {
  $rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\')
  $candidate = Join-Path $rootFull 'CNgopay'
  if (-not (Test-Path -LiteralPath $candidate)) { continue }

  $resolved = (Resolve-Path -LiteralPath $candidate).Path.TrimEnd('\')
  $expected = [IO.Path]::GetFullPath($candidate).TrimEnd('\')
  $parent = [IO.Path]::GetFullPath((Split-Path -Parent $resolved)).TrimEnd('\')

  if (-not [StringComparer]::OrdinalIgnoreCase.Equals($resolved, $expected)) {
    throw "Refusing unexpected target: $resolved"
  }
  if (-not [StringComparer]::OrdinalIgnoreCase.Equals($parent, $rootFull)) {
    throw "Refusing target outside workspace root: $resolved"
  }

  Remove-Item -LiteralPath $resolved -Recurse -Force
  if (Test-Path -LiteralPath $resolved) {
    throw "CNgopay deletion failed: $resolved"
  }
}
```

Expected: `Test-Path D:\code\OpenSource\AutoTeam-F\CNgopay` returns `False`; if execution uses a linked worktree, its tracked `CNgopay/` copy is also absent.

- [ ] **Step 5: Run packaging and residue-focused checks**

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_rename_compat.py -q
.venv\Scripts\ruff.exe check src/autotoken/_protocol_register/auth_flow.py tests/unit/test_rename_compat.py
git diff --check

$pattern = '(?i)gopay_pro(?:_|\b)|gopay-pro(?:-|\b)|CNGOPAY(?:_|\b)|CNgopay|GoPay Pro'
$hits = rg -n --pcre2 --hidden --glob '!**/.git/**' --glob '!**/.pytest_tmp*/**' --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/build/**' --glob '!logs/**' --glob '!outputs/**' --glob '!data/**' --glob '!auths/**' --glob '!tmp/**' --glob '!.tmp/**' --glob '!docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md' --glob '!docs/superpowers/plans/2026-07-13-remove-gopay-pro.md' $pattern .
if ($LASTEXITCODE -eq 0) { throw "removed markers remain:`n$hits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
$camelHits = rg -n --pcre2 --hidden --glob '!**/.git/**' --glob '!**/.pytest_tmp*/**' --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/build/**' --glob '!logs/**' --glob '!outputs/**' --glob '!data/**' --glob '!auths/**' --glob '!tmp/**' --glob '!.tmp/**' --glob '!docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md' --glob '!docs/superpowers/plans/2026-07-13-remove-gopay-pro.md' 'GoPayPro[A-Z]|\bgopayPro\b' .
if ($LASTEXITCODE -eq 0) { throw "removed camel-case markers remain:`n$camelHits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
```

Expected: rename/package tests pass, Ruff passes, whitespace is clean, and both marker scans return no matches outside the two removal records.

- [ ] **Step 6: Commit subsystem/data/config/document deletion**

```powershell
git add -- .gitignore .dockerignore pyproject.toml src/autotoken/_protocol_register/auth_flow.py docs/architecture.md docs/docker.md docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md tests/unit/test_rename_compat.py
git add -A -- CNgopay
git diff --cached --check
git diff --cached --stat
git commit -m "chore: remove GoPay Pro subsystem and artifacts"
```

Expected cached diff: the complete tracked `CNgopay/` subtree is deleted and no unrelated runtime or PayPal file is staged.

---

### Task 5: Run Full Regression, Build, Marker, and Preservation Gates

**Files:**
- Verify only; do not edit unless a failure is directly caused by the removal.

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: evidence that ordinary GoPay remains functional, the removed surface is absent, builds pass, and pre-existing PayPal work remains applied.
- Execution note: Verification-before-completion is mandatory.

- [ ] **Step 1: Run the complete ordinary GoPay regression set**

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/unit/test_gopay_appium.py `
  tests/unit/test_gopay_auto_register.py `
  tests/unit/test_gopay_auto_signup_config_routes.py `
  tests/unit/test_gopay_pending_retry_service.py `
  tests/unit/test_gopay_runtime_service.py `
  tests/unit/test_gopay_task_payloads_service.py `
  tests/unit/test_gopay_wallet_pool_service.py `
  -q
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_executor.py -k gopay -q
.venv\Scripts\python.exe -m pytest tests/unit/test_bind_task_api.py -k gopay -q
node web/scripts/test-gopay-board.mjs
```

Expected: all selected tests and the GoPay board script pass.

- [ ] **Step 2: Verify the final API route inventory**

```powershell
@'
from autotoken.interfaces.api import app

paths = {getattr(route, "path", "") for route in app.routes}
assert not any(path.startswith("/api/gopay-pro") for path in paths)
required = {
    "/api/tasks/gopay-bind",
    "/api/config/gopay-auto-signup",
    "/api/tasks/gopay/runtime-control",
}
missing = sorted(required - paths)
assert not missing, missing
print("final API route gate passed")
'@ | .venv\Scripts\python.exe -
```

Expected: `final API route gate passed`.

- [ ] **Step 3: Run the project-wide Python quality gates**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\python.exe -m compileall -q src/autotoken
```

Expected: full pytest, Ruff lint, Ruff format check, and compileall pass.

- [ ] **Step 4: Run the frontend quality gates**

```powershell
npm --prefix web run build
node web/scripts/test-bind-link-payload.mjs
node web/scripts/test-gopay-board.mjs
```

Expected: Vite production build and both Node scripts pass.

- [ ] **Step 5: Re-run the repository marker and directory gates**

```powershell
if (Test-Path -LiteralPath 'D:\code\OpenSource\AutoTeam-F\CNgopay') {
  throw 'physical CNgopay directory still exists'
}

$pattern = '(?i)gopay_pro(?:_|\b)|gopay-pro(?:-|\b)|CNGOPAY(?:_|\b)|CNgopay|GoPay Pro'
$hits = rg -n --pcre2 --hidden --glob '!**/.git/**' --glob '!**/.pytest_tmp*/**' --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/build/**' --glob '!logs/**' --glob '!outputs/**' --glob '!data/**' --glob '!auths/**' --glob '!tmp/**' --glob '!.tmp/**' --glob '!docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md' --glob '!docs/superpowers/plans/2026-07-13-remove-gopay-pro.md' $pattern .
if ($LASTEXITCODE -eq 0) { throw "removed markers remain:`n$hits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
$camelHits = rg -n --pcre2 --hidden --glob '!**/.git/**' --glob '!**/.pytest_tmp*/**' --glob '!**/.venv/**' --glob '!**/node_modules/**' --glob '!**/dist/**' --glob '!**/build/**' --glob '!logs/**' --glob '!outputs/**' --glob '!data/**' --glob '!auths/**' --glob '!tmp/**' --glob '!.tmp/**' --glob '!docs/superpowers/specs/2026-07-13-remove-gopay-pro-design.md' --glob '!docs/superpowers/plans/2026-07-13-remove-gopay-pro.md' 'GoPayPro[A-Z]|\bgopayPro\b' .
if ($LASTEXITCODE -eq 0) { throw "removed camel-case markers remain:`n$camelHits" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
```

Expected: directory check and both exact marker scans pass. Ordinary `gopayProxy`, `GOPAY_PROTOCOL`, and `GOPAY_PROVIDER` identifiers may remain.

- [ ] **Step 6: Prove the pre-existing PayPal changes are still applied**

```powershell
$sourceRoot = (Resolve-Path 'D:\code\OpenSource\AutoTeam-F').Path
$patchPath = (Resolve-Path .pytest_tmp/remove-gopay-pro-preexisting.patch).Path
git -C $sourceRoot apply --reverse --check $patchPath
$expectedHash = (Get-Content .pytest_tmp/remove-gopay-pro-paypal-plan.sha256 -Raw).Trim()
$actualHash = (
  Get-FileHash (Join-Path $sourceRoot 'docs/superpowers/plans/2026-07-13-paypal-gb-ba-extraction.md') -Algorithm SHA256
).Hash
if ($actualHash -ne $expectedHash) {
  throw 'pre-existing PayPal plan changed during GoPay Pro removal'
}
git -C $sourceRoot status --short
git diff --check
```

Expected: reverse patch check succeeds, the PayPal plan hash matches, the pre-existing PayPal modifications remain visible but unstaged/uncommitted by this work, and whitespace checks pass.

- [ ] **Step 7: Review the final branch diff**

```powershell
git log --oneline --decorate -5
git diff abb5426..HEAD --stat
git diff abb5426..HEAD -- src/autotoken web/src tests/unit .gitignore .dockerignore pyproject.toml docs/architecture.md docs/docker.md docs/plans/2026-06-06-001-refactor-autotoken-architecture-plan.md
```

Expected: the branch contains the neutral shared-helper extraction and complete Pro removal only. No ordinary GoPay, Rekberinaja, PayPal, or unrelated account functionality is deleted.

## Requirements Trace

- Complete standalone subsystem and local-data deletion: Task 4 Steps 4 and 6; Task 5 Step 5.
- Backend routes, tasks, services, and task group removal: Task 2.
- Generic account-plan and bind-link behavior preservation: Task 1 and Task 5 Steps 2-3.
- Frontend page/navigation/API/provider removal and stale-page fallback: Task 3.
- Packaging, ignore, compatibility-test, and documentation cleanup: Task 4.
- Ordinary GoPay preservation: Tasks 2 and 5.
- Unrelated PayPal change preservation: Task 1 Steps 1 and 9, Task 2 Step 7, Task 5 Step 6.
