# Apple Light Theme and Full UI Redesign Design

## Status

Approved in conversation on 2026-08-30 for branch `codex/apple-light-theme-ui`.

## Context

AutoTeam-F already has an Apple-inspired dark shell, lazy-loaded Vue pages, responsive navigation, and performance-oriented polling and rendering behavior. The visual layer is not a real theme system: `style.css` fixes `color-scheme: dark`, `index.html` fixes dark body classes, and business pages contain thousands of dark-oriented Tailwind utilities, transparent variants, status colors, and several fixed dark gradients.

This project adds a first-class `system | light | dark` appearance model and deeply redesigns every frontend page without changing backend APIs or business state machines. Work proceeds in four checkpoints on one isolated branch so the theme foundation is stable before page-level composition changes.

The current production baseline at `f0a222f` builds successfully with 68 transformed modules and a 133.12 KiB entry chunk. The existing 43 frontend regression scripts currently report 32 passing and 11 failing; phase one must restore that baseline suite rather than treating the failures as theme regressions.

## Decisions

- Cover every frontend page, including login, setup, modal, task-panel, mobile dock, and mobile-sheet states.
- Provide three persistent preferences: follow system, light, and dark.
- Put a compact switcher in the workspace title bar and a full appearance selector in Settings; login and initial setup also expose the switcher.
- Allow deep information and interaction redesign while preserving business workflows, API contracts, polling semantics, and stored task state.
- Use semantic design tokens plus a Tailwind RGB-variable compatibility layer, then migrate each page archetype to shared semantic primitives.
- Implement in this order: theme and shell, operations workspace, payment and registration flows, settings/support and final verification.

## Visual Thesis

AutoTeam-F becomes a calm, precise operations environment modeled after Apple platform conventions. Light mode uses a quiet `#f5f5f7` canvas, white content layers, thin separators, restrained shadows, SF system typography, and a focused blue accent. Dark mode keeps its existing hierarchy while reducing heavy black surfaces and excessive borders. Both themes prioritize dense operational data, readable state, and obvious primary actions over decorative cards.

Motion explains state without adding work: only switcher, popover, sheet, and page-presence transitions animate, using opacity and transform. Theme changes do not animate every background or text node.

## Theme Architecture

### First-paint bootstrap

`index.html` runs a small synchronous bootstrap before the application module and stylesheet-dependent content paint. It:

1. Reads `autotoken_theme` from local storage inside `try/catch`.
2. Normalizes the value to `system`, `light`, or `dark`, falling back to `system`.
3. Resolves `system` with `matchMedia('(prefers-color-scheme: dark)')`.
4. Sets `document.documentElement.dataset.themePreference`.
5. Sets `document.documentElement.dataset.theme` to the resolved light or dark value.
6. Updates `color-scheme` and the document theme-color metadata.

This prevents an initial dark frame when the resolved theme is light.

### Theme controller

A pure JavaScript `themePreference.js` module owns theme behavior and exposes a small controller API. It validates preferences, resolves system appearance, applies root attributes, persists explicit preference, reacts to media-query changes only while following the system, synchronizes storage events across tabs, and removes all listeners on disposal.

Storage read/write failures and missing browser capabilities degrade to an in-memory `system` preference without interrupting application startup. Theme changes update only root attributes and metadata; the controller never traverses the page DOM.

### Theme switcher

`ThemeSwitcher.vue` presents a compact resolved-theme button and a radio-style three-option selector:

- Follow system
- Light
- Dark

The control exposes the preference and resolved theme in its accessible name, supports Enter, Space, arrows, Escape, outside-click close, and focus return, and uses an icon, label, and selected mark rather than color alone. Desktop uses a compact popover; narrow viewports use an accessible sheet with a 44 px minimum target.

The title-bar instance is always available in an authenticated workspace. Login and initial setup place the compact control at the upper-right. Settings mirrors the same controller with a larger appearance group rather than maintaining separate state.

## Design Tokens

The root theme defines semantic variables rather than page-specific colors:

- Surfaces: base, sidebar, window, panel, strong panel, inset, muted, hover, pressed.
- Separators: standard and strong.
- Text: primary, secondary, muted, faint, placeholder, and on-accent.
- Accent: fill, hover, strong/text, soft fill, and focus ring.
- Status: success, warning, danger, and paired soft fills.
- Depth: window, panel, and popover shadows.
- Environment: scrim, scrollbar thumb, scrollbar hover, and page gradients.

The light baseline uses:

```text
surface-base          #f5f5f7
surface-sidebar       #f2f2f7
surface-window        #ffffff
surface-panel         #ffffff
surface-panel-strong  #f2f2f7
surface-muted         #e5e5ea
surface-line          rgba(60, 60, 67, 0.18)
surface-line-strong   rgba(60, 60, 67, 0.28)
text-main             #1d1d1f
text-secondary        #424245
text-muted            #6e6e73
accent-fill           #0071e3
accent-text           #0066cc
danger                #d70015
warning               #8a4b00
success               #197a32
```

`text-on-accent` remains white in both themes so a global mapping of `text-white` cannot produce dark text on blue controls.

## Tailwind Compatibility and Migration

The Tailwind gray and slate palettes are redefined as RGB CSS variables with `<alpha-value>`, preserving opacity modifiers, hover variants, placeholder variants, and scoped `@apply`. A compatibility layer maps the existing dark-oriented utilities and status colors to readable light-theme values immediately.

This compatibility layer covers:

- Gray and slate backgrounds at 950, 900, and 800, including transparent variants.
- Gray and slate borders at 900 through 600 and divide utilities.
- White and gray/slate text at 100 through 500 plus placeholders.
- Hover backgrounds and text.
- Emerald, rose, red, amber, blue, cyan, and violet status foregrounds and soft surfaces.
- Scrims, scrollbars, shadows, and fixed payment-page gradients.

Shared shell and newly redesigned components use semantic utilities directly. Each page phase removes obsolete compatibility usage from the pages it touches, but the compatibility layer remains until the final audit confirms complete visual coverage.

## Shared Component Boundaries

Shared visual components do not fetch data or own business operations. They receive state and emit user intent through props, slots, and events.

The redesign establishes reusable primitives for:

- Application frame, page header, title-bar actions, and responsive navigation.
- Surface sections and grouped settings rows.
- Metric summaries and status badges.
- Primary, secondary, quiet, and destructive actions.
- Form field, help, validation, disabled, and loading states.
- Segmented controls and filter disclosure.
- Empty, loading, error, and partial-data states.
- Accessible modal, popover, sheet, and task panel.
- Data toolbar, batch-action bar, pagination, and dense table framing.

Business pages retain data loading, mutations, polling, cancellation, recovery, and task persistence. The visual components remain independently understandable and testable.

## Page Archetypes

### Data workspaces

Dashboard, accounts, mail, tasks, history, and team pages use a stable page header, metric summary, collapsible filters, batch-action bar, and bounded data view. Desktop preserves efficient density. Mobile moves secondary filters and batch actions into a sheet without changing selection semantics. Existing pagination and render-window safeguards remain in place.

### Workflow workspaces

PayPal, Brazil Pix, India UPI, Kakao Pay, GCash, Momo, Ideal, bind-card, and registration pages use a consistent configuration, launch, progress, and result structure. Desktop may use a two-column input/status composition; mobile becomes a single ordered flow. One primary action remains visually dominant, while secondary and destructive actions are separated.

### Management and settings

Settings, pools, OAuth, sync, support, and maintenance pages use grouped navigation and rows instead of repeated gray cards. Related controls share labels and help text. Advanced and destructive sections are disclosed rather than competing with common actions.

### Authentication and first setup

Login and initial setup retain a focused central path, simplified background, clear recovery/error presentation, and an always-available theme switcher.

## Implementation Phases

### Phase 1: theme foundation and application shell

- Add bootstrap, controller, switcher, semantic tokens, Tailwind palette, and metadata updates.
- Redesign application title bar, sidebar, mobile dock and sheet, login, setup, modal, and task panel.
- Establish the shared visual primitives.
- Restore the 11 currently failing frontend regression scripts.

### Phase 2: operations workspace

- Redesign dashboard, accounts, tasks, mail, records, and team pages.
- Preserve large-list, filtering, selection, pagination, and polling performance.
- Standardize loading, empty, error, and partial-data states.

### Phase 3: payment and registration workflows

- Redesign all payment, registration, and bind-card pages around the workflow archetype.
- Replace fixed dark gradients and page-specific status colors.
- Preserve request acknowledgement, polling recovery, cancellation, and unknown-outcome protections.

### Phase 4: management, support, and final convergence

- Redesign settings, pools, OAuth, sync, support, and remaining routes.
- Remove redundant styling and compatibility mappings proven unused.
- Complete all-theme, all-route browser and accessibility verification.

## Error Handling and Accessibility

- Theme storage failures never block rendering or authentication.
- Invalid stored preference resolves to `system`.
- Theme changes in another tab synchronize without reload.
- Every selector exposes selected state and resolved appearance to assistive technology.
- Focus remains visible and returns to the opener after popover, sheet, and modal close.
- Status is never communicated by color alone.
- Text combinations meet WCAG AA 4.5:1; control boundaries and focus indicators meet 3:1.
- Forced-colors mode receives explicit borders and focus handling.
- `prefers-reduced-motion` disables switcher and sheet movement.

## Performance Requirements

- Theme changes modify root state only and trigger no network request.
- No global color transition or per-node style rewrite is allowed.
- A 20,000-account dashboard survives ten consecutive theme changes with second-frame completion p95 at or below 100 ms.
- The production entry stays at or below 250 KiB and retains at least eight asynchronous JavaScript chunks.
- Page redesign must not remove current render-window, pagination, single-flight, visibility, or cancellation safeguards.

## Test Strategy

### Theme TDD gate

A new non-ignored `web/scripts/theme-regression.mjs` test drives `themePreference.js` before production implementation. RED assertions cover missing controller, three-state normalization, system resolution, explicit override, storage errors, media listener lifecycle, storage-event synchronization, root-only mutation, first-paint bootstrap, switcher accessibility contract, semantic light tokens, reduced motion, and the absence of `transition: all`.

### Existing regression and build gates

- Restore the existing suite from 32/43 to 43/43 before accepting phase one.
- Run the production build after every phase.
- Enforce the 250 KiB entry and asynchronous chunk budgets.
- Run focused page and runtime scripts for every touched workflow.

### Browser matrix

Automated Chromium verification covers system-light, system-dark, explicit light, and explicit dark at:

- Desktop: 1440 x 1000
- Mobile: 390 x 844
- Short viewport: 1024 x 620

Every navigation destination must load without page or console errors, avoid horizontal overflow, expose readable modal/sheet/task-panel states, and retain keyboard navigation. Screenshots are produced for dashboard, settings, PayPal, registration, mobile navigation, and dense mobile forms in both themes.

The 20,000-account fixture additionally measures repeated theme switching and confirms there are no extra requests, layout shifts, or full-DOM traversal.

## Acceptance Criteria

- System, light, and dark preferences work before first paint and persist correctly.
- Theme controls are available in login, setup, the title bar, and Settings.
- Every frontend route is visually coherent and usable in light and dark themes.
- The four page archetypes use consistent composition and shared semantic states.
- Existing business workflows and backend contracts remain unchanged.
- All frontend regression, theme, build, bundle, browser, accessibility, and performance gates pass.
- Required screenshots and transaction artifacts are generated and reopened.
- The branch remains isolated from the unrelated dirty main worktree until integration is explicitly requested.
