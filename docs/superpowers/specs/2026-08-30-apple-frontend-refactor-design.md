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
- `Sidebar.vue` owns desktop and mobile navigation presentation.
- `style.css` defines the Apple-inspired design tokens and the responsive shell.

## Performance and reliability

- Split every large feature page from the initial JavaScript entry.
- Replace overlapping `setInterval` polling with completion-scheduled `setTimeout` polling and single-flight guards.
- Pause network polling while the document is hidden or the browser is offline.
- Abort stalled HTTP calls with a typed timeout rather than leaving controls permanently busy.
- Normalize task counters numerically so string-valued API fields cannot corrupt progress.
- Remove full-workspace live backdrop blur and the 360 px mobile width cap.

## Testing

Runtime tests cover single-flight execution, animation-frame coalescing, request aborts, and numeric progress. Source-contract tests cover responsive layout, active navigation semantics, reduced motion, and shell structure. A production bundle budget enforces route splitting. Existing frontend regression scripts and a production build remain required.
