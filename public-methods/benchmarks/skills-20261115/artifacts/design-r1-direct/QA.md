# Actual QA results

## Executed checks
Command: `node /work/qa.mjs` (Node v24.22.3, installed Chromium, Chrome DevTools Protocol, local `file:///work/index.html`). Completed successfully with exit code 0. The test starts its own local debugging browser and closes it afterward; no packages or network services are needed.

- All 7 source IDs appear initially as cards inside `#results`. Each source name, neighborhood, service, hours, note, access value and open/closed status was checked against the rendered card text.
- All 24 combinations of 4 neighborhood choices × 3 service choices × 2 step-free states passed against independently computed source-data expectations. Each combination also checked the result count and empty-state visibility.
- Every active filter excluded closed locations. Step-free only excluded both false and null values. East + Cooling + Step-free only yields Cedar Library; West + Advice yields no matches.
- Reset button was clicked after filtering: all controls reset and all 7 records returned.
- Every select and checkbox has an associated label.
- Real keyboard Tab events reached Skip to directory → Neighborhood → Service → Step-free only → Reset filters. Each active element had a solid visible outline.
- No horizontal overflow at viewport widths 320, 390, 768 and 1280 CSS pixels. Recorded document scroll widths: 305, 375, 753 and 1265 respectively (the difference is the browser's vertical scrollbar).
- Zero browser JavaScript exceptions and zero external requests recorded during the local-file test.
- Full-page `desktop.png` (1280 viewport) and `mobile.png` (390 viewport) were captured by Chromium and both opened with the native image viewer. Visual inspection found readable content, an obvious dated snapshot notice, aligned controls, distinguishable closed cards, wrapping unknown-access labels and no clipping. No visual correction was needed after inspection.

Machine-readable results: `qa-results.json`. Re-run: `node /work/qa.mjs`. Rebuild from the fixture: `python /work/build.py` (requires the supplied `/task/input/centers.json`). The built HTML itself needs neither script nor fixture to run.

## Limits
This was Chromium-only testing, not a cross-browser or screen-reader audit. No live availability or real-world service verification was attempted. Snapshot information is explicitly historical. Native select keyboard behavior is provided by the browser; automated tests changed select values and dispatched change events for the combination matrix, while keyboard Tab navigation was exercised separately. No claim of formal WCAG certification is made.
