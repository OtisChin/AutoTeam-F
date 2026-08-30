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

- [ ] Add failing tests for single-flight execution, RAF event coalescing, HTTP timeout aborts, and numeric progress.
- [ ] Implement focused runtime modules.
- [ ] Integrate abortable fetch and typed timeouts into the API client.
- [ ] Integrate single-flight completion-scheduled polling and RAF drag updates into `App.vue`.

## Task 2: Route splitting

- [ ] Add a failing production bundle-budget test.
- [ ] Convert feature page imports to cached async imports with loading and error states.
- [ ] Prefetch a page when navigation intent is observed.
- [ ] Build and verify the entry budget and emitted route chunks.

## Task 3: Apple-inspired shell

- [ ] Add failing shell-contract tests.
- [ ] Centralize navigation metadata and add semantic SVG icons.
- [ ] Replace the mobile horizontal scroller with a dock and full navigation sheet.
- [ ] Add the workspace title bar, global state indicator, and accessible progress announcements.
- [ ] Replace legacy tokens/layout with opaque layered materials, Apple semantic colors, fixed responsive geometry, and reduced-motion rules.

## Task 4: Regression and visual verification

- [ ] Run all frontend Node regression scripts and fix relevant pre-existing failures.
- [ ] Run a production build and bundle-budget verification.
- [ ] Inspect desktop and mobile screenshots and correct glaring layout issues.
- [ ] Request an independent code review and resolve critical/important findings.

## Task 5: Transaction evidence

- [ ] Produce the modified-file snapshot, unified diff, verification record, and executable rollback script.
- [ ] Run rollback against a disposable copy and verify the original web tree is restored.
- [ ] Reopen all four artifacts and leave the working branch modified.
