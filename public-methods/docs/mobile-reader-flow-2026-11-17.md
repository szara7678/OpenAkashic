# Mobile reader flow check — 2026-11-17

This check covers navigation and reading state after the earlier mobile gesture
work. The original 14 gesture/rendering-work contracts remain in place. No new
device-performance measurement or utility KPI is reported here.

## Observed baseline failures

A visible Chrome session at 390 × 844 with touch emulation reproduced these
failures against baseline `c168578`:

- A graph tap on public method `method_0b8450340161413d96cd38d879e84ae3:v2`
  ended around (293, 587). The ensuing native click (`detail: 1`) hit the newly
  inserted connections tab at the same position, opening an unrequested tab.
- From that method's connections pane at scrollTop 960, opening shared-source
  method `method_fa79358fbb3143459eaeab135bcdb023:v2` and selecting Previous
  returned to the original method's overview pane at scrollTop 0.
- Tapping a linked card's context text at (100, 820) did not navigate.
- The bottom overview action opened the steps pane at scrollTop 703, with its
  heading at y −63.98 while the inspector began at y 354.48.

These are Chrome touch-emulation observations, not physical Android results.

## Regression coverage and candidate behavior

Five reader contracts run the actual reader code with synthetic public method
details and a small in-memory history fixture:

1. Linked-method navigation and Back/Forward retain each entry's tab, scroll
   position and expanded reader state.
2. A linked method card is one semantic button; clicking its context reaches
   the method, without nested buttons.
3. The overview-to-steps and steps-to-connections actions show the next pane
   from its start. Keyboard activation focuses its corresponding tab.
4. Late detail responses cannot replace a newer selection or a restored reader.
5. A graph tap consumes its matching compatibility click once; a fresh contact,
   keyboard activation, different pointer or different position remains usable.

Against `c168578`, these five tests produced one pass and four failures. The
existing late-response protections passed; Back state, whole-card activation,
overview action scroll reset and compatibility-click handling failed. The
candidate passes all 19 JavaScript contracts, including the original 14.
The final existing-runtime pytest run passed 226 tests and 7 subtests in
60.38 seconds, including the launcher for all 19 JavaScript contracts.

A separate visible Chrome candidate check at the same emulated mobile size
confirmed that the first graph tap opens overview, with no unintended
connections selection and no duplicate reading-route controls. The bottom
overview action opened steps at scrollTop 0, with its heading visible around
y 598. Tapping linked context at (100, 820) opened the intended second method.
Previous returned to the first method's connections pane at scrollTop 930
after the restore animation frame; Forward reopened the second method's
overview at scrollTop 0. The candidate reading position in this check was 930;
the earlier baseline observation used 960.

Final Chrome checks at 320 × 740 confirmed navigation buttons at 44 CSS pixels
high and at least 44 wide in normal, expanded and long-focus-label states,
without horizontal overflow. With the final sticky offset, navigation began at
y 117 against an inspector top of y 116 (the border accounts for one pixel);
tabs occupied y 169–225, without the earlier exposed text strip. Back/Forward
also preserved the first method's connections pane at scrollTop 930 with the
reader unexpanded, and the second method's steps pane at scrollTop 295 with the
reader expanded. The bottom steps action opened connections at scrollTop 0.
Keyboard Enter on a source card opened its reader and focused the close button;
that source reader showed two tabs, each 141 CSS pixels wide. These remain
Chrome emulation checks, including the measured dimensions.

The fake DOM does not calculate layout, scroll clamping, browser event targeting
or screen-reader output. Passing these contracts establishes JavaScript state
and dispatch behavior. Candidate visual reading layout and actual browser flow
must be checked separately; neither these tests nor Chrome touch emulation
establish physical-device behavior.

Run from `public-methods/`:

```sh
node --test web/tests/mobile-interaction.contract.cjs
PYTHONPATH=api python -m pytest api/tests -q
```

See [the harness notes](../web/tests/README.md) for fixture boundaries and
[the earlier mobile check](mobile-atlas-2026-11-16.md) for the historical trace.
This change does not establish deployment or publication.
