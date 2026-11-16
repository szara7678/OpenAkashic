# Atlas event contracts

Run `node --test web/tests/mobile-interaction.contract.cjs` from `public-methods/`
with Node.js 18 or newer. The existing `pytest api/tests` job also discovers the
Python launcher; it reports a skip if Node is unavailable.

The harness runs the real atlas JavaScript in a Node VM. The original 14 gesture
contracts use two synthetic public records and a `choose` spy. Five additional
reader contracts retain the actual `choose` implementation, supply two synthetic
public methods linked through one shared public source, and resolve small
detail-response fixtures. They exercise Back/Forward using an in-memory
location/history fixture, including delayed response orderings.

The harness observes state, selection calls, SVG writes, text/layout measurement
calls and queued animation frames. It fakes the DOM, SVG matrix and clock; its
click helper explicitly dispatches document capture handlers before target and
ancestor handlers. It does not implement native hit testing or duplicate the
gesture/reader implementation. An optional `ATLAS_SCRIPT` path runs the same
contracts against another source revision for regression checks.

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

The [2026-11-17 reader flow check](../../docs/mobile-reader-flow-2026-11-17.md)
records the five added reader regressions and the separately observed Chrome
touch-emulation failures that motivated them.
