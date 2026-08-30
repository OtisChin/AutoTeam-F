# Apple-Inspired Frontend Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a faster, smoother, Apple-inspired frontend shell while fixing request, polling, drag, progress, and mobile-layout defects.

**Architecture:** Keep Vue 3 and Tailwind, split feature pages at the existing application boundary, and extract only the small runtime primitives that need deterministic tests. Preserve every page and backend contract.

**Tech Stack:** Vue 3.5, Vite 6, Tailwind CSS 3.4, Node assertion scripts.

## Global Constraints

- Preserve every current navigation destination and page-specific prop/event contract.
- Animate only compositor-friendly properties and honor reduced motion.
- Do not add runtime dependencies.
- Keep initial JavaScript at or below 250 KiB uncompressed.

## Task 1: Runtime safeguards

- [x] Add failing tests for single-flight execution, RAF event coalescing, HTTP timeout aborts, and numeric progress.
- [x] Implement focused runtime modules.
- [x] Integrate abortable fetch and typed timeouts into the API client.
- [x] Integrate single-flight completion-scheduled polling and RAF drag updates into `App.vue`.

## Task 2: Route splitting

- [x] Add a failing production bundle-budget test.
- [x] Convert feature page imports to cached async imports with loading and error states.
- [x] Prefetch a page when navigation intent is observed.
- [x] Build and verify the 148,976-byte entry bundle and 27 emitted asynchronous route chunks.

## Task 3: Apple-inspired shell

- [x] Add failing shell-contract tests.
- [x] Centralize navigation metadata and add semantic SVG icons.
- [x] Replace the mobile horizontal scroller with a dock and full navigation sheet.
- [x] Add the workspace title bar, global state indicator, and accessible progress announcements.
- [x] Render Dashboard account actions and secondary subscription/latest-mail dialogs through `Teleport`, with inert background boundaries, focus traps, Escape close, and focus restoration to the original row action.
- [x] Replace legacy tokens/layout with opaque layered materials, Apple semantic colors, fixed responsive geometry, and reduced-motion rules.

## Task 4: Regression and visual verification

- [x] Run all frontend Node regression scripts and fix relevant pre-existing failures.
- [x] Run a production build and bundle-budget verification.
- [x] Inspect desktop and mobile screenshots and correct glaring layout issues.
- [x] Request an independent code review and resolve critical/important findings.

## Task 5: Large-account transport and rendering

- [x] Add a Dashboard-only account loading lifecycle with abort, auth epoch, provider race, and `304` snapshot handling.
- [x] Define the ordered 44-field Dashboard DTO, including `monthly_window_seconds`, and compact quota-window fields in Python, and assert exact frontend benchmark parity.
- [x] Move route-specific gzip compression to a worker and return weak `ETag` plus correct `Vary`/CORS headers.
- [x] Cache unchanged snapshots by SQLite `data_version`, revalidate them with a weak `ETag`, and return `304` before account loading, sanitation, serialization, or compression work.
- [x] Release the source account/quota/sanitized collections after building the compact DTO so a 50,000-account response does not retain duplicate full-pool object graphs.
- [x] Add indexed/deferred search, indexed selection, scoped action derivation, `v-memo` rows, and a 50-row default render window with a hard maximum of 200.
- [x] Verify 20,000 and 50,000 realistic account records in Node, SQLite benchmarks, and a real browser.

## Task 6: Hidden-bug and recovery fixes

- [x] Give logs monotonic IDs and add `since_id` incremental polling plus `boot_id`/`since_boot_id` restart epochs so equal-timestamp entries and post-restart low IDs are retained.
- [x] Make Setup schema-driven for `generic-api` and `mail.com`, derive provider labels from schema options, associate labels and required semantics with controls, and keep the long form scrollable on short screens.
- [x] Synchronously activate and emit the saved Setup API key, fence duplicate saves, and mount authenticated pages only after the generated-key storage owner is ready.
- [x] Degrade cleanly when browser storage is unavailable, refusing ownerless startup/login/setup transitions without crashing the API module.
- [x] Validate login candidates with a non-committing probe, preserve the prior recovery owner on rejection/timeout, and perform owner rotation plus key activation before committing authenticated UI state.
- [x] Freeze API keys in a tab-local memory snapshot and advance the auth epoch on cross-tab key/owner changes so stale requests and UI cannot cross operator identities.
- [x] Restore Outlook `mailapi_url` in account credential export.
- [x] Make account credential, CPA, and Sub2API exports two-phase: generate/download first, then confirm `credentials_exported` in sequential 1,000-email batches, preserving already confirmed batches if a later acknowledgement fails.
- [x] Replace route-time `Query(...)` default objects with `Annotated` metadata.
- [x] Persist payment start acknowledgements before state-changing provider POSTs can repeat after remount.
- [x] Persist PayPal/iDEAL idempotency and unknown-outcome recovery across restart.
- [x] Recover PayPal Protocol and Pay153 cancel requests made before the start ACK by persisting cancel intent, accepting the eventual job ID, and polling/cancelling to a terminal state.
- [x] Prevent Pay153 duplicate creates after checkpoint failure or unresolved stale cancellation, and reset stale in-memory worker counts during rehydration.

## Task 7: Final verification

- [x] Make the default frontend gate discover and run every `test-*.mjs` script (61/61).
- [x] Verify the 20,000/50,000-account desktop view, 50-row first paint, filtering, indexed selection, pagination, action-dialog focus trap, Escape close, and focus restoration.
- [x] Verify the 390 x 844 mobile dock, navigation-sheet focus loop, Escape/button close, focus restoration, zero horizontal overflow, and a clean browser console.
- [x] Record the final 34-file Ruff gate, diff check, 545-test Python regression, 61/61 frontend regression, and desktop/mobile browser evidence after the last code edit.

## Task 8: Transaction evidence

- [x] Produce the modified-file snapshot, unified diff, verification record, and executable rollback script.
- [x] Run baseline and modified checks with exact captured output.
- [x] Run rollback against a separate disposable modified copy and verify baseline behavior and repository state are restored.
- [x] Reopen all four artifacts and leave the working branch plus `MODIFIED_FILE.zip` modified.
