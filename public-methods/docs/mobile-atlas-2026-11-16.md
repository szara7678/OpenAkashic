# Mobile atlas interaction check — 2026-11-16

The candidate addresses captured node gestures, repeated rendering work, and
mobile panels that covered the map after closing a record. This is a bounded
regression check, not a physical Android performance result.

## JavaScript contracts

`web/tests/mobile-interaction.contract.cjs` contains 14 behavioral contracts,
discovered by `api/tests/test_method_mobile_interaction.py` in the existing
pytest job. They run the actual atlas script with synthetic public graph data,
a small fake DOM/SVG, a manual animation clock, and a selection-call spy.

Coverage includes captured tap/drag routing, final pointerup coordinates,
cancel/lost-capture cleanup, pinch-to-pan continuation, SVG coordinate conversion,
the five-CSS-pixel drag threshold, multi-pointer tap suppression, compatibility
click deduplication, frame coalescing, cached label measurements, keyboard/help
focus behavior, reset/ARIA state, and return to the full mobile map without
reopening discovery or retaining dimmed nodes. Desktop dismissal retains its
expanded discovery panel.

The initial 13-contract comparison against revision `e652` produced 6 passes
and 7 failures; the candidate passed those 13 contracts. The added focused
mobile-dismissal contract also failed on `e652`: dismissal reopened discovery.
It passes with the candidate. These are event/state contracts; the fake DOM
does not establish browser hit testing, screen reader output or device behavior.
The final existing-runtime pytest run passed 226 tests and 7 subtests in
47.97 seconds, including the launcher for all 14 JavaScript contracts.

## Visible Chrome touch emulation

The browser comparison used a 390 × 844 viewport, touch emulation, a frozen
public graph of 71 methods / 114 nodes / 103 edges, CPU throttling at 4×, and
six pan move events covering 90 × 60 CSS pixels. One measured trace per version
reported:

- Baseline: LayoutCount 696; text measurements 684; TaskDuration 0.671095 s;
  ScriptDuration 0.127147 s; LayoutDuration 0.192202 s.
- Candidate: LayoutCount 6; text measurements 0; TaskDuration 0.101435 s;
  ScriptDuration 0.014127 s; LayoutDuration 0.004687 s.

These measurements show less work in this trace. They do not establish an FPS
target, typical latency, sustained smoothness or physical Android performance.

Visible Chrome checks also passed map panning, node dragging and record taps.
An emulated pinch from map points (90, 250) / (300, 250) to (60, 250) /
(330, 250) increased zoom from 98% to 126%; ending touch preserved 126%, kept
the inspector hidden and left document scrollY at zero. A fresh record tap
followed by close left the inspector hidden, no selected or dimmed nodes,
discovery collapsed, zoom at 98%, and no horizontal overflow. These checks used
Chrome touch emulation; physical devices were not checked.

## Reproduction and boundaries

From `public-methods/`, run:

```sh
node --test web/tests/mobile-interaction.contract.cjs
PYTHONPATH=api python -m pytest api/tests -q
```

Node.js 18+ is required for the JavaScript contracts. The Python launcher
explicitly skips them when Node is missing. Public API read-only boundaries
remain covered by the existing API suite. This work does not add public writes,
modify private data, or establish deployment/publication.
