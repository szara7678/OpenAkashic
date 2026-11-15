# QA — executed checks

## Run
`node /work/qa.cjs` — PASS, exit code 0. Uses installed `/opt/eval-browser/node_modules/playwright-core` and `/usr/bin/chromium`, headless with `--no-sandbox`, opening `file:///work/index.html`. No development server or downloads.

## Automated outcomes
- Initial view: all seven source IDs appear inside `#results` in source order. Each card contains its source name, neighborhood, services, hours, step-free answer, note and open/closed status.
- Snapshot: `<time datetime>` matches `2026-07-18`.
- All 24 combinations (4 neighborhoods × 3 services × 2 step-free states) match an independently computed expectation from the fixture. Nondefault filters exclude both closed locations. Step-free only excludes false and null.
- Result count matches the displayed cards in every combination. Empty-state heading appears exactly when zero locations match.
- Reset restores all seven locations and resets both selects and the checkbox.
- Keyboard: Tab reaches the skip link, then Neighborhood. The focused select has a solid outline. ArrowDown + Enter chooses East and immediately shows exactly Cedar Library and Market Room.
- At 390px width: document width does not exceed viewport in default, filtered and empty states; filter controls fit inside the viewport.
- Browser JavaScript errors: 0. HTTP(S) requests: 0.
- Raw report: `qa-results.json`. Re-runnable checks: `qa.cjs`.

## Render and visual inspection
Chromium screenshots saved and opened with the native image viewer:
- `desktop.png`: 1280px-wide full page. Clear hierarchy, two-column directory, restrained introduction, snapshot notice and readable closed-location treatment.
- `mobile.png`: 390px-wide full page. Single-column cards, stacked selects, complete visible labels, wrapped unknown access and notes; no clipping observed.
- `empty-mobile.png`: 390px-wide West + Advice + Step-free only. Zero matches, helpful recovery guidance and Reset filters available; no clipping observed.

## Scope and corrections
No QA failures required correction. Design review before implementation omitted promotional hero imagery to prioritize the usable directory. No screen-reader session, automated accessibility audit, cross-browser check, or claim of full WCAG conformance. Focus and label checks are limited to the executed tests described above. Data is a fixed snapshot, not live availability; no contact or address information was supplied. JavaScript is required to render/filter the directory and a noscript notice communicates that limitation.
