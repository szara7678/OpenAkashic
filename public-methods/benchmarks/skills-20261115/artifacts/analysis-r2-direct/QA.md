# Quality assurance

Analysis executed: `python /work/analysis.py --input /task/input/cases.csv --output-dir /work`.
Result: 140 cases; six summary rows; pooled difference −3.3333333333333326 pp;
equal-branch difference +13.99999999999999 pp (floating-point representation).
The initial full-file profile found 140 unique case IDs and these outcome counts:
assisted East 8 success / 2 failure / 4 unknown; assisted West 30 / 20 / 6;
standard East 36 / 14 / 1; standard West 4 / 6 / 9.
Further independent numerical and visual checks are recorded after execution.

## Independent verification
Executed `python /work/verify.py`: PASS.
- Exact six-row schema, service/branch combinations, fixture counts, count identities, and all rate denominators passed.
- Numeric JSON keys matched −10/3 and +14 pp within 1e-12; direction reversal passed.
- HTML parsed; seven table rows including header, English language, expected numerical/caution text, and no external asset/script/link elements passed.
- Re-ran analysis in a temporary directory: all three generated outputs were byte-identical.
- Input SHA-256 unchanged across rerun: `7102332b96bc80fc775aa9339b5fa13b437299ff6c9a3631a30cc79ea4a47430`.
- These are artifact and fixture checks, not evidence of causal validity.

## Render and visual inspection
Executed Chromium offline PDF rendering and Poppler conversion using the exact
commands recorded in README.md. `pdfinfo` reports two tagged Letter pages, no
JavaScript, and 63,660 bytes. Opened both `report-preview.png` (page 1) and
`report-page2.png` (page 2) with the native image viewer. Both pages are readable;
comparison cards, all six table rows, missingness discussion, causal caveat,
next step, and source footer fit without horizontal clipping or overlaps.
The table is kept intact on page 2; its introduction ends page 1. This is an
acceptable print pagination limitation; the HTML is continuous. No visual fixes
were required. Narrow/mobile view was not separately rendered or visually tested.
Runtime check `python --version` returned Python 3.12.16. No external requests made.
