# PayPal protocol SMS provider investigation — HeroSMS rent and OTP reuse

Date: 2026-07-24
Workspace: /Users/mac/code/my/AutoTeam-F

## Findings

- HeroSMS old SMS-Activate-compatible endpoint is valid for normal API-key calls such as `getBalance`, `getNumber`, `getStatus`, `setStatus`.
- HeroSMS web UI uses Nuxt chunks and REST endpoints under `/api/v1`:
  - `GET /api/v1/activations`
  - `GET /api/v1/activations/{id}`
  - `PATCH /api/v1/get-sms`
  - `POST /api/v1/activations/{id}/request-extra-sms`
  - `POST /api/v1/activations/{id}/finish`
  - prolong/reactivate endpoints under `/api/v1/activations/{id}/...`
- `.env` HeroSMS API key successfully reaches `handler_api.php?action=getBalance`.
- The same API key does **not** authenticate `/api/v1/activations` (`401 Unauthenticated`); HeroSMS web REST requires browser session cookie/bearer context.
- Old actions `getRentList` / `getRentStatus` are not valid for HeroSMS handler API in current production and should not be used by default.

## Implementation decisions

- `hero_sms_rent` remains a dedicated provider mode.
- Rent mode now resolves activation id through:
  1. inline input format `<phone>#<activation_id>` / `<phone>|<activation_id>`;
  2. env `PAYPAL_HERO_SMS_RENT_ACTIVATION_ID` / aliases;
  3. local reusable activation cache matching phone/country;
  4. optional HeroSMS web REST lookup when `PAYPAL_HERO_SMS_COOKIE` or bearer token is configured.
- Normal automatic HeroSMS/SMSBower mode now keeps activations reusable by default:
  - success no longer calls `setStatus(6)` unless `PAYPAL_SMS_FINALIZE_ON_SUCCESS=1`;
  - successful confirmation calls/request status `3` to keep/request next SMS;
  - stale OTP codes are ignored on reused activations via `last_code` cache.
- Reuse controls:
  - `PAYPAL_SMS_REUSE_ENABLED` default `true`
  - `PAYPAL_SMS_REUSE_MAX_USES` default `5`
  - `PAYPAL_SMS_FINALIZE_ON_SUCCESS` default `false`
  - `PAYPAL_SMS_CANCEL_ON_ABANDON` default `false` for SMS-Activate-compatible auto mode

## Verification

- `handler_api.php?action=getBalance`: HTTP 200 with `ACCESS_BALANCE` prefix (key not logged).
- `/api/v1/activations` with API key only: HTTP 401 `Unauthenticated`, confirming REST is cookie/session based.
- `hero_sms_rent` without cache/id/cookie now fails with an actionable configuration error instead of BAD_ACTION.
- Unit tests: `tests/unit/test_paypal_protocol_local_service.py tests/unit/test_us_paypal_routes.py` => 40 passed.
- Ruff: passed for touched Python files.
- Frontend build: `cd web && npm run build` passed.

## Sensitive data handling

- No API key, OTP, full phone, BA token, proxy credential, cookie, or private PayPal log is written here.
- Raw Nuxt chunks are saved under `.open-reverselab/exports/hero-sms-nuxt/` as reverse-analysis evidence.

## GB auto-number payment failure at 14:11

Observed log summary:

- HeroSMS automatic number mode was not the final failure point.
- Provider selected `hero_sms`, `service=ts`, `country=16`.
- The flow reused/acquired GB numbers, initiated OTP, received OTP, and PayPal returned `CONFIRMED`.
- Final failure happened later in `SignUpNewMemberMutation` with `RESIDENTIAL_ADDRESS_NOT_FOUND`.
- The generated GB address normalized to a landmark/non-residential address (`10 Downing Street / SW1A 2AA`), which PayPal rejected after OTP confirmation.

Fix applied:

- Replaced GB address fixtures with non-landmark residential-style addresses.
- Added retry handling for signup address validation errors: `RESIDENTIAL_ADDRESS_NOT_FOUND`, `ADDRESS_NOT_FOUND`, `INVALID_BILLING_ADDRESS`, `BILLING_ADDRESS_INVALID`.
- On address validation failure, the engine rotates the billing address, resets address autocomplete state, and retries signup in-place while preserving the already confirmed phone session.
