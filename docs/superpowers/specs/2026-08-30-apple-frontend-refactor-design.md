# Apple-Inspired Frontend Refactor Design

## Visual thesis

AutoTeam-F becomes a calm, dense operations workspace inspired by Apple platform conventions: opaque layered materials, precise separators, SF system typography, Apple semantic colors, restrained depth, and motion that explains state without competing with live data.

## Content plan

The desktop layout keeps a persistent grouped sidebar and adds a compact workspace title bar that always identifies the active tool and global task state. The main page remains the primary workspace. On narrow screens, a four-item dock exposes frequent destinations and a focused sheet exposes the complete navigation tree without forcing users through a 20-item horizontal scroller.

## Interaction plan

1. Route modules load on demand and are prefetched on navigation intent so first paint is small while page changes remain responsive.
2. Page entry and mobile-sheet transitions animate only opacity and transform for compositor-friendly motion, and all motion stops under `prefers-reduced-motion`.
3. Drag updates for the task panel are coalesced to one update per animation frame and use `translate3d`, avoiding repeated layout work.

## Architecture

- `navigation.js` owns navigation metadata shared by the shell and sidebar.
- `App.vue` remains the orchestration boundary but lazy-loads feature pages and serializes background refresh work.
- `runtimePerformance.js`, `request.js`, and `taskProgress.js` isolate testable runtime behavior.
- `sessionStorageScope.js` binds resumable browser state to an API-key fingerprint and fences late writes from superseded owners.
- `Sidebar.vue` owns desktop and mobile navigation presentation.
- `style.css` defines the Apple-inspired design tokens and the responsive shell.

## Performance and reliability

- Split every large feature page from the initial JavaScript entry.
- Replace overlapping `setInterval` polling with completion-scheduled `setTimeout` polling and single-flight guards.
- Pause network polling while the document is hidden or the browser is offline.
- Abort stalled HTTP calls with a typed timeout rather than leaving controls permanently busy.
- Normalize task counters numerically so string-valued API fields cannot corrupt progress.
- Remove full-workspace live backdrop blur and the 360 px mobile width cap.
- Load the account pool only while Dashboard is active. Abort stale requests on auth/provider changes and prevent an earlier response from committing into a newer session.
- Return a compact, ordered 44-field Dashboard account DTO, including `monthly_window_seconds`, with compact quota windows instead of serializing storage-only fields. Reuse snapshots with a weak `ETag`, expose it through CORS, and set `Vary: Authorization, Accept-Encoding` on both `200` and `304` responses.
- Key snapshots by the SQLite `data_version` and answer unchanged requests with `304` before loading, sanitizing, serializing, or compressing the account pool. Drop the source account/quota/sanitized collections once the compact DTO is built so large requests do not retain duplicate object graphs.
- Keep gzip work off the event loop by compressing the account response in a worker. Do not use application-wide synchronous gzip middleware for this high-volume route.
- Precompute Dashboard search text, defer query application by 120 ms, index email selection, derive actions only for the selected scope, memoize stable rows, and render a bounded 50-row page (maximum 200) rather than mounting the whole account pool.
- Bound live log and job snapshots. Increment backend log IDs and poll with `since_id`; pair the cursor with a process `boot_id`/`since_boot_id` epoch so a restart accepts the new process's low IDs instead of dropping them as duplicates.

## Setup and authentication reliability

- Drive the first-run provider form from the backend schema, including `generic-api` and `mail.com`, derive section labels from the selected provider option, and keep provider-only fields out of the common section.
- Keep the long Setup form vertically scrollable in short viewports. After a successful save, synchronously activate and emit the returned API key, reject duplicate saves, and mount authenticated operator pages only after the generated key owns resumable storage.
- Guard API-key and saved-page storage access. If browser storage is unavailable, the API module remains usable without throwing while the root application refuses to mount an ownerless authenticated session and presents a recoverable storage error.
- Validate a submitted login key with a `commit=false` probe. A rejected or indeterminate candidate leaves the prior recovery owner intact; a confirmed candidate rotates the owner, activates the key, and only then commits `authenticated` state.
- Freeze the active API key in a tab-local memory snapshot so another tab cannot silently change an in-flight request identity. An external API-key or owner storage event advances the auth epoch, aborts stale work, clears authenticated UI state, and requires an explicit re-entry.

## Durable operation recovery

- Persist request identity and start acknowledgements before payment pages can repeat a state-changing POST after remount.
- Treat a successful remote create followed by a failed local checkpoint as `unknown_outcome`; retries must reconcile rather than create a duplicate remote payment.
- Refuse a new Pay153 create while cancellation of a stale remote task remains unconfirmed.
- Preserve cancel intent when PayPal Protocol or Pay153 cancellation is requested before the start ACK arrives; once the ACK supplies a job ID, recover terminal polling and issue/confirm cancellation instead of losing the remote job.
- Reset process-local worker counts during restart recovery so an `unknown_outcome` can be released by explicit reconciliation after the original worker no longer exists.
- Classify `400/401/403/409/422` polling failures as permanent, retry `408/425/429`, `5xx`, and network failures with a five-failure budget, and preserve remote job/checkpoint/account or phone occupancy whenever recovery pauses.
- Bound Pay153 cancellation/cleanup to 360 seconds, block new Pay153 mutations during that window, and discard every manual/automatic polling write that returns after component unmount.
- Generate account credential, CPA, and Sub2API downloads without mutating export state; after the browser accepts the download, acknowledge exported emails sequentially in batches of 1,000 so partial acknowledgement remains truthful and retryable.

## Accessibility

- Navigation and account-action dialogs expose dialog semantics, move initial focus inside, trap `Tab`/`Shift+Tab`, close with Escape, restore focus to the opener, and make the background inert while open. Dashboard action and secondary subscription/latest-mail dialogs render through body-level `Teleport`; a secondary dialog atomically replaces the first inert boundary and restores focus to the original row action when it closes.
- The mobile dock stays reachable at 390 px without horizontal overflow. The complete navigation sheet locks background scroll while it is open.
- Setup labels are programmatically associated with their controls, required fields expose native and ARIA-required semantics, and save success/failure is announced through live status/alert roles.
- SVG icons are semantic components rather than text glyphs, active state is announced, and reduced-motion removes nonessential transitions.

## Testing

Runtime tests cover single-flight execution, animation-frame coalescing, request aborts, auth/session isolation, durable polling recovery, numeric progress, render windows, and bounded snapshots. Source-contract tests cover responsive layout, active navigation semantics, reduced motion, focus management, and shell structure. A production bundle budget enforces route splitting. `run-frontend-tests.mjs` discovers every `test-*.mjs` script so a new regression cannot silently remain outside the default gate.

The production verification fixture returns 20,000 realistic accounts with the same 44 Dashboard fields and full quota-window shape. Its field order is derived from the Python DTO constants and compared with the browser benchmark to prevent backend/frontend contract drift. The accepted measurements are:

- initial entry JavaScript: 147,326 bytes uncompressed; 27 asynchronous chunks;
- 20,000-account compact payload: 20,719,248 bytes versus 36,758,426 bytes for the legacy object shape;
- compact parse and preparation: approximately 65-70 ms; preparation alone approximately 30-33 ms;
- filter p95: approximately 1 ms; indexed selection p95: approximately 0.01 ms; scoped account-action derivation p95: approximately 8 ms;
- first rendered page: 50 rows;
- real SQLite cold response: approximately 534 ms for 20,000 accounts and 1.36 seconds for 50,000; unchanged `304` median approximately 0.087 ms;
- 50,000-account Python pipeline peak: approximately 410 MB before source-release optimization and 338 MB after it, a reduction of approximately 72 MB;
- real browser DOM: 50 account rows and no mobile horizontal overflow at 390 x 844;
- all 61 discovered frontend regression scripts pass after the production build.
