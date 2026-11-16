# Atlas event contracts

Run `node --test web/tests/mobile-interaction.contract.cjs` from `public-methods/`
with Node.js 18 or newer. The existing `pytest api/tests` job also discovers the
Python launcher; it reports a skip if Node is unavailable.

The harness runs the real atlas JavaScript in a Node VM, supplies two synthetic
public graph records, and observes state changes, selection calls, SVG writes,
layout/text measurements, and queued animation frames. It fakes the DOM, SVG
screen matrix and clock, and spies on `choose` so event routing is isolated from
network retrieval and record rendering. It does not duplicate the gesture
implementation or require browser automation. An optional `ATLAS_SCRIPT` path
runs the same contracts against another source revision for regression checks.

These checks establish event routing, final-coordinate handling, cancel cleanup,
pinch continuation, tap thresholds, frame coalescing, cached text measurements,
keyboard activation and reset state. They do **not** establish real browser
pointer capture/retargeting, default-event behavior, physical touch support,
screen reader output, CSS layout, visual clarity or device performance. Those
require separate visible browser/device checks. Public API read-only boundaries
remain covered by `api/tests/test_methods_standalone.py` and related API tests.

The [2026-11-16 mobile atlas check](../../docs/mobile-atlas-2026-11-16.md)
records the 14 contracts, baseline regressions, and the separate bounded Chrome
touch-emulation checks and rendering-work measurements.
