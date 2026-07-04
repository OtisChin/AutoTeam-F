# PayPal Pro Design

Date: 2026-07-04

## Goal

Add a new PayPal Pro module to AutoTeam-F that extracts PayPal BA/checkout links with three-stage proxy control, batch racing, and amount checks, then hands successful pre-extracted results into the existing PayPal binding flow.

The module should reuse the existing AutoTeam-F backend task system, account/auth-session storage, PayPal protocol extraction code, PayPal binding executor, task history, and frontend visual patterns.

## Non-Goals

- Do not port the external Tkinter GUI wholesale.
- Do not duplicate existing PayPal binding browser automation.
- Do not add OpenAI registration, Outlook mailbox collection, phone authorization, Apple Pay, GoPay, or Chrome extension payment-window automation to this module.
- Do not replace the existing PayPal page.

## User Workflow

1. Open the new `PayPal Pro` item in the left sidebar under `Payments`.
2. Choose one or more GPT accounts from the existing account pool, or paste access tokens for direct use.
3. Configure PayPal Pro extraction:
   - PayPal BA mode: `eu` or `us`.
   - Payment method country.
   - Create proxy pool for ChatGPT checkout creation.
   - Follow-up proxy pool for Stripe init, payment method, confirm, and redirect polling.
   - Approve proxy pool for ChatGPT checkout approve.
   - Per-account max attempts.
   - Per-account race concurrency.
   - Optional target amount.
4. Start the PayPal Pro task.
5. Watch live task logs, extracted links, amount-check status, and downstream PayPal binding status.
6. Copy extracted links or let successful pre-extracted BA results continue into the existing PayPal binding flow.

## Frontend Design

Add `PayPalProPage.vue` using the same dark operations-console style as `PayPalPage.vue`, `PayPalIcePage.vue`, and `GoPayProPage.vue`.

Layout:

- Header with four stat cards: total, extracted, bound, failed.
- Left configuration column:
  - account/token source selector;
  - account picker using existing account list API with session stubs;
  - PayPal extraction options;
  - three proxy pool textareas;
  - retry/race/amount controls;
  - start/cancel buttons.
- Main results column:
  - active task selector;
  - live progress/log view;
  - per-account result table with email/token label, extraction status, amount status, approve URL, checkout URL, binding status, and error.

Integration points:

- Add `paypalPro` to `PAGE_KEYS` in `App.vue`.
- Import and render `PayPalProPage`.
- Add sidebar item `{ key: 'paypalPro', group: 'Payments', glyph: 'P+', label: 'PayPal Pro' }`.
- Add API client methods for status, config save, task start, and task cancellation/status reuse.

## Backend Design

Add a focused PayPal Pro backend layer instead of expanding the existing PayPal route directly.

New modules:

- `src/autotoken/api_routes/paypal_pro.py`
- `src/autotoken/services/paypal_pro_proxy.py`
- `src/autotoken/services/paypal_pro_task_payloads.py`
- `src/autotoken/services/paypal_pro_results.py`

API surface:

- `GET /api/paypal-pro/status`
  Returns latest PayPal Pro tasks and saved lightweight config.
- `PUT /api/paypal-pro/config`
  Saves non-secret defaults such as concurrency, max attempts, BA mode, and target amount.
- `POST /api/paypal-pro/task`
  Starts a PayPal Pro task.

Task request fields:

- `account_emails: list[str]`
- `access_tokens_text: str`
- `source: "accounts" | "tokens"`
- `paypal_ba_mode: "eu" | "us"`
- `payment_method_country: str`
- `create_proxy_pool_text: str`
- `followup_proxy_pool_text: str`
- `approve_proxy_pool_text: str`
- `reuse_create_proxy: str`
- `reuse_followup_proxy: str`
- `reuse_approve_proxy: str`
- `max_attempts: int`
- `race_concurrency: int`
- `target_amount: str`
- downstream PayPal binding options needed by the existing PayPal flow.

## Task Flow

For each account or token item:

1. Resolve an access token.
   - Account source reads the stored auth session context when available.
   - Token source uses the pasted access token and an empty session context.
2. Build proxy triples:
   - create proxy: ChatGPT checkout creation;
   - follow-up proxy: Stripe/payment provider steps;
   - approve proxy: ChatGPT approve;
   - missing follow-up reuses create;
   - missing approve reuses follow-up.
3. Precheck/canonicalize proxy triples.
   - Keep this scoped to parse/normalize and lightweight connectivity checks already present in the project.
   - Cache successful proxy summaries for task logs.
4. Run attempts up to `max_attempts`.
   - If `race_concurrency` is 1, try proxy triples sequentially.
   - If `race_concurrency` is greater than 1, launch that many extraction attempts for the same account and stop account-level retries when one succeeds.
5. Call existing PayPal BA extraction:
   - Use the internal `_paypal_extract_ba_link` behavior through a small service wrapper.
   - Pass create/follow-up/approve proxy values into the existing extraction kwargs.
   - Preserve existing `paypal_ba_mode`, `payment_method_country`, session context, and cancellation handling.
6. Apply amount check.
   - If `target_amount` is empty, record `skipped`.
   - If the extracted result exposes an amount and it differs from `target_amount`, mark extraction failed and do not start PayPal binding.
   - If no amount is exposed, record `unknown` and continue only when the user did not set a target amount.
7. On extraction success, start the existing PayPal binding path with direct BA/link fields:
   - `paypal_approve_url`
   - `paypal_ba_token`
   - `paypal_checkout_session_id`
   - `paypal_checkout_url`
   - `paypal_hosted_checkout_url`
   - `paypal_payment_method_id`
   - `checkout_url`
8. Store progress events and result summaries in the existing task progress model.

## Proxy Rules

Proxy grouping mirrors the external tool but uses AutoTeam-F task conventions.

- If no create proxies are supplied and no follow-up/approve proxies are supplied, run direct or through the configured local/default proxy.
- If follow-up or approve proxies are supplied without create proxies, treat the proxy configuration as invalid.
- If one create proxy is supplied, it can be reused across attempts unless a separate pool exists.
- Follow-up defaults to create.
- Approve defaults to follow-up.
- Failed proxy triples are removed from future attempts unless that stage uses an explicit reuse proxy.
- Race attempts for the same account use distinct proxy triples when available.

## Result Shape

Each per-account result should include:

- `email`
- `status`
- `approve_url`
- `ba_token`
- `checkout_url`
- `hosted_checkout_url`
- `checkout_session_id`
- `payment_method_id`
- `paypal_ba_mode`
- `create_proxy_summary`
- `followup_proxy_summary`
- `approve_proxy_summary`
- `target_amount`
- `actual_amount`
- `amount_check`
- `binding_task_id`
- `binding_status`
- `failure_stage`
- `message`

## Error Handling

- Token invalidation stops retries for that account and marks it as non-retryable.
- Amount mismatch stops retries for that account and skips downstream binding.
- Proxy exhaustion marks the account as `proxy_exhausted`.
- Extraction success with downstream PayPal failure keeps the extracted link visible.
- Cancellation should stop pending attempts and avoid starting new downstream binding tasks.

## Testing

Backend unit tests:

- Proxy triple generation and fallback behavior.
- Invalid proxy pool combinations.
- Race batching stops after success.
- Amount check passed, skipped, unknown, and failed cases.
- Successful extraction builds the existing PayPal direct BA/link payload.
- Token invalidated and amount mismatch are non-retryable.
- Route starts a `paypal-pro` task with normalized params.

Frontend checks:

- `npm run build` succeeds.
- Page renders with no selected accounts.
- Account picker persists selected accounts.
- Start button sends normalized request payload.
- Result rows display extracted links and binding status.

## Rollout

Implement behind the new sidebar entry only. Existing PayPal, PayPal ICE, and GoPay Pro pages should keep their current behavior. The first version should support PayPal BA extraction plus downstream PayPal binding; Apple Pay and GoPay links remain outside PayPal Pro.
