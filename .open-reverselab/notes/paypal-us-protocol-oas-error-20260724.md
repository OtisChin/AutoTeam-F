# PayPal US protocol local engine OAS_ERROR triage - 2026-07-24

## Symptom

Latest frontend task log shows OTP flow completed successfully, then `CreateMemberAccountMutation` returned `OAS_ERROR` at checkpoint `createMemberAccount`.

## Local evidence

The local headless signup-context diagnostic reported:

- observed: `identity_di_log`, `datadog_rum`, `observability`, `ddbm`
- missing: `fraudnet_p1`, `fraudnet_p2`, `fraudnet_w`, `tealeaf`
- blocked resource: `https://www.paypalobjects.com/webcaptcha/ngrlCaptcha.min.js` by allowlist policy

## Fix applied

- Allowlisted PayPal signup-context webcaptcha script in local headless network policy.
- Added a CreateMemberAccount preflight: signup-context browser-risk families must be present before submitting.
- If missing, the engine retries local headless once with a fresh session; if still incomplete, it stops before `CreateMemberAccount` with a clear error instead of consuming a BA into generic `OAS_ERROR`.
- Runner now classifies both preflight-block and backend `OAS_ERROR` messages for the frontend.

## Verification

- `py_compile` passed for modified Python files.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 33 passed.
- `npm run build` under `web/` => success.

## Sensitive data handling

No BA token, phone, proxy credential, SMS token, OTP, cookie, or auth material is recorded in this note.

## 2026-07-24 AutoTeam landing mismatch follow-up

User correctly pointed out that the research runner looked stable while AutoTeam-F runs had not succeeded. Re-checking evidence showed the two full local runner successes used `Proxy: disabled`, while the AutoTeam-F API/UI made proxy mandatory and the failing UI run used a SOCKS proxy. That changed the verified runtime tuple.

Applied fix:

- Backend protocol start no longer requires proxy.
- Job runner now passes an empty proxy URL through to the bundled engine, which emits `--no-proxy`.
- Frontend label/text changed from mandatory `US proxy` to optional proxy; default is the verified no-proxy tuple.
- Added route regression test to ensure protocol start accepts no proxy.

Verification after change:

- `py_compile` passed for PayPal API/service/engine files.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 34 passed.
- `npm run build` under `web/` => success.

## 2026-07-24 02:28 failed AutoTeam run follow-up

The pasted frontend log was the tail of the engine RESULT/risk JSON, not the original chronological engine log. The current local diagnostic file showed signup-context risk was complete:

- observed: `fraudnet_p3`, `fraudnet_p1`, `fraudnet_p2`, `fraudnet_w`, `identity_di_log`, `tealeaf`, `datadog_rum`, `observability`, `ddbm`
- missing: none
- required_missing: none

The visible blocker in the tail was `strict_blockers=["mtr_sealedResult_missing"]`. The web runner also misclassified the failure as authchallenge because the full output contained an earlier non-terminal authchallenge warning.

Applied runner fix:

- Pin `PAYPAL_STRICT_BROWSER_RISK=0` for AutoTeam-F web runner so research/lab strict mode cannot leak into production runs.
- Pin `PAYPAL_MTR_HEADLESS_WAIT_SECONDS=45` alongside the already-pinned risk wait.
- Fold the engine `RESULT` JSON in live logs; keep it in `protocol_result` only, so frontend logs preserve the real failure chronology.
- Prefer MTR/signup-context/OAS classifications before generic authchallenge classification.

Verification:

- `py_compile src/autotoken/services/paypal_protocol_local.py` passed.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 35 passed.
- `npm run build` under `web/` => success.

## 2026-07-24 02:33 AutoTeam real-run log follow-up

The latest AutoTeam-F web run used the verified no-proxy tuple and progressed further than prior failures:

- no proxy
- OTP initiated and confirmed
- signup-context browser risk complete (`missing=<none>`)
- `CreateMemberAccountMutation` succeeded and returned user/access token

The actual failure was Phase 4:

- `ApproveMemberPaymentMutation` returned errors at checkpoint `createCheckoutSession` and `approveMemberPayment` was null.
- The engine then incorrectly continued to guest/Hagrid fallback.
- Hagrid authorize returned `PAYER_INVALID_FOR_PAYMENT` with `errors[0].data` as a string.
- `_has_buyer_not_set()` assumed `errors[*].data` was a dict and crashed with `'str' object has no attribute 'get'`, hiding the real approve failure.

Applied fix:

- `_has_buyer_not_set()` now handles non-dict `data` safely.
- US create-member-no-FI Phase 4 now stops on member approve failure and returns that real failure instead of trying incompatible guest/Hagrid fallbacks.
- Runner message classification now reports member approve failure clearly.

Verification:

- `py_compile` passed for modified files.
- Isolated import check confirms `_has_buyer_not_set()` handles string `data`.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 36 passed.
- `npm run build` under `web/` => success.

## 2026-07-24 02:39 repeated BA run follow-up

The latest AutoTeam-F web run used the same masked BA suffix and same EC observed in the 02:33 run. It again reached:

- OTP confirmed
- signup-context risk complete (`missing=<none>`)
- `CreateMemberAccountMutation` success

It failed at the same Phase 4 point:

- `ApproveMemberPaymentMutation` HTTP 200 with errors
- checkpoint: `createCheckoutSession`
- `approveMemberPayment` returned null

This confirms the current BA/EC is terminal/non-fresh for the local no-FI approval path, and repeated runs waste SMS/account attempts.

Applied fix:

- Added local hashed BA terminal registry: `data/paypal_protocol_terminal_ba.json`.
- If a BA has reached CreateMemberAccount and then failed member approve, subsequent runs are blocked before launching the engine unless `PAYPAL_PROTOCOL_ALLOW_TERMINAL_BA_RETRY=1` is explicitly set.
- The registry stores only SHA-256 digest plus masked suffix/reason; it does not store full BA tokens.
- Seeded the currently repeated BA into the registry from the local link store by suffix, storing only the hash/masked value.

Verification:

- `ruff check src/autotoken/services/paypal_protocol_local.py tests/unit/test_paypal_protocol_local_service.py` => passed.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 37 passed.
- `npm run build` under `web/` => success.

## 2026-07-24 02:42 fresh BA actual success but AutoTeam runner false negative

The fresh BA run was not a PayPal failure. Evidence in the frontend log:

- `ConfirmRiskBasedTwoFactorPhoneConfirmationMutation` => `CONFIRMED`
- signup-context risk => `missing=<none>`
- `CreateMemberAccountMutation` succeeded
- `ApproveMemberPaymentMutation` HTTP 200 returned `approveMemberPayment.state=APPROVED`
- engine log: `=== Flow completed successfully ===`

AutoTeam-F still displayed failure because the wrapper classified the run from raw output text after failing/losing the structured RESULT parse. The output contained historical diagnostic text `mtr_sealedResult_missing` inside `risk_runtime.strict_blockers`, so the wrapper treated a successful run as failed.

Applied fix:

- Added robust success fallback in `paypal_protocol_local.py`: if child exit code is 0 and output has `Flow completed successfully` plus `APPROVED`/success status evidence, the job is success even if RESULT JSON parsing is unavailable.
- Failure classification is now skipped once success is detected, so diagnostic `strict_blockers` cannot override a successful PayPal approval.
- Added regression tests for malformed/missing RESULT JSON and success RESULT containing `mtr_sealedResult_missing` diagnostics.

Verification:

- `ruff check src/autotoken/services/paypal_protocol_local.py tests/unit/test_paypal_protocol_local_service.py` => passed.
- `pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q` => 39 passed.
- `npm run build` under `web/` => success.
