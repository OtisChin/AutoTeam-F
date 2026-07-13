# Remove GoPay Pro Design

**Date:** 2026-07-13  
**Status:** Approved for implementation planning

## Goal

Remove every GoPay Pro feature and implementation from AutoTeam-F while preserving the ordinary GoPay binding and automatic wallet-signup flows.

## Scope

### Remove

- The complete `CNgopay/` subtree, including tracked source files and local untracked configuration, account pools, tokens, run history, generated binaries, and backups.
- Backend GoPay Pro configuration and task routes under `/api/gopay-pro/*`.
- GoPay Pro task orchestration, script execution, slot-state management, number-pool handling, event parsing, account-token extraction, task payloads, and task-group definitions.
- The GoPay Pro frontend page, sidebar entry, page key, API methods, task labels, and dashboard provider presentation.
- GoPay Pro environment variables, build exclusions, ignore rules, operational documentation, and obsolete design-plan references that present the subsystem as currently available.
- GoPay Pro-specific tests and GoPay Pro assertions embedded in shared tests.

### Preserve

- `/api/tasks/gopay-bind` and the ordinary GoPay binding workflow.
- GoPay automatic signup, OTP handling, wallet pooling, pending retry, balance polling, and Rekberinaja support used by ordinary GoPay.
- The ordinary GoPay tab in `web/src/components/BindCard.vue`.
- Shared payment, address, SMS, proxy, checkout, task-runtime, and PayPal functionality that still has non-Pro callers.
- Existing unrelated working-tree changes, especially the current PayPal changes.

## Current Architecture

GoPay Pro is implemented as an embedded subsystem with four layers:

1. `CNgopay/` supplies the standalone pool binaries, command wrappers, configuration, and the Node-based account registration helper.
2. FastAPI routes expose GoPay Pro configuration, status, number import, slot mutation, script tasks, and batch tasks.
3. `src/autotoken/interfaces/api.py` and `src/autotoken/services/gopay_pro_*.py` adapt the standalone subsystem into the shared task runtime.
4. Vue exposes a dedicated GoPay Pro page and supporting navigation, API, task-name, and dashboard mappings.

The ordinary GoPay implementation is separate and remains supported. It lives primarily in the GoPay bind route, `payments/gopay_*`, `services/gopay_*` modules that do not carry the `_pro` suffix, and the ordinary GoPay section of `BindCard.vue`.

## Removal Design

### Standalone subsystem

Delete `D:\code\OpenSource\AutoTeam-F\CNgopay` only after resolving and validating that exact absolute path. The deletion includes both Git-tracked files and untracked local data, as explicitly selected by the user.

### Backend modules and routing

Delete these dedicated modules:

- `src/autotoken/api_routes/gopay_pro_config.py`
- `src/autotoken/api_routes/gopay_pro_tasks.py`
- `src/autotoken/services/gopay_pro_accounts.py`
- `src/autotoken/services/gopay_pro_events.py`
- `src/autotoken/services/gopay_pro_pool.py`
- `src/autotoken/services/gopay_pro_task_payloads.py`

Remove their imports, aliases, constants, helpers, script runners, batch orchestrators, status builders, and router registrations from `src/autotoken/interfaces/api.py`. Remove `TASK_GROUP_GOPAY_PRO` and any task-runtime policy branches that exist only for that group.

Prune GoPay Pro-only branches from mixed modules, including API configuration, integrations, ordinary GoPay payment helpers, proxy runtime, task payloads, and protocol registration. A mixed helper is deleted only when a call-site search proves it has no ordinary GoPay, PayPal, or other remaining consumer.

No compatibility or tombstone router will remain. Requests to `/api/gopay-pro/*` will use FastAPI's normal `404` behavior.

### Frontend

Delete `web/src/components/GoPayProPage.vue`. Remove its import, render branch, page key, task-name mappings, sidebar navigation entry, and all GoPay Pro API methods.

Remove `gopay_pro` display mappings from the dashboard. If a browser still has the exact legacy page key `gopayPro` in local storage, the existing page validation behavior will reject it and fall back to the default dashboard. Ordinary identifiers such as `gopayProxy*` are unrelated and must remain.

### Configuration and documentation

Remove GoPay Pro and CNgopay entries from:

- `.env.example`
- `.gitignore`
- `.dockerignore`
- `pyproject.toml`
- Active architecture and Docker documentation
- Historical plan text that describes GoPay Pro as an available component

Git history itself is not rewritten. This approved removal design and its implementation plan remain as change records and are excluded from the removed-feature marker scan.

### Tests

Delete the dedicated `tests/unit/test_gopay_pro_*.py` files. Remove only GoPay Pro cases, fixtures, imports, and assertions from shared test files. Preserve and run ordinary GoPay coverage to detect accidental cross-feature deletion.

Add or update route-level coverage to prove that GoPay Pro endpoints are absent while the ordinary GoPay bind and automatic-signup configuration endpoints remain registered.

## Runtime Behavior After Removal

- The application starts without importing any GoPay Pro module.
- No GoPay Pro route, page, task launcher, status panel, configuration control, number-pool control, or slot mutation remains.
- Old GoPay Pro task records are not migrated. They are inert runtime data and cannot be launched or retried through the removed feature.
- The ordinary GoPay and PayPal flows continue to use their existing shared infrastructure.
- Missing GoPay Pro endpoints return the framework-standard `404` response.

## Error Handling and Safety Boundaries

- Remove wiring before deleting imported modules so intermediate changes remain diagnosable.
- Use call-site searches before pruning mixed helpers.
- Validate the resolved `CNgopay` deletion target equals the intended workspace child path before recursive deletion.
- Do not stage, revert, overwrite, or otherwise modify the unrelated PayPal working-tree changes.
- Treat failures in ordinary GoPay tests, application import, or frontend build as regressions that block completion.

## Verification

1. Confirm `D:\code\OpenSource\AutoTeam-F\CNgopay` does not exist.
2. Search the current checkout, excluding this removal design and its implementation plan, for the exact removed-feature markers:
   - `gopay_pro`
   - `gopay-pro`
   - exact JavaScript identifier/page key `gopayPro` using a word boundary so `gopayProxy*` is not matched
   - `GOPAY_PRO`
   - `CNGOPAY`
   - `CNgopay`
   - `GoPay Pro`
3. Verify `/api/gopay-pro/*` is absent and `/api/tasks/gopay-bind` remains present.
4. Run the ordinary GoPay route, runtime, wallet-pool, pending-retry, auto-register, Appium, payload, and bind-executor tests.
5. Run the complete Python test suite and Ruff checks.
6. Run the frontend build and existing frontend script tests.
7. Review the final Git diff and confirm the pre-existing PayPal modifications were not changed by this work.

## Acceptance Criteria

- No GoPay Pro functionality is reachable from the API or frontend.
- No GoPay Pro implementation module, standalone subsystem, behavior test, configuration entry, or documentation presenting it as available remains; only the approved removal design and implementation plan may retain historical references.
- The physical `CNgopay/` directory and its local data are deleted.
- Ordinary GoPay binding and automatic signup continue to pass their tests.
- The backend imports successfully, the full Python suite and lint checks pass, and the frontend builds successfully.
- Unrelated pre-existing changes remain intact.
