# Executed analysis checks

Command: `python /work/analysis.py`

- PASS — 140 unique nonblank case IDs; schema and allowed values validated
- PASS — Exactly six summary rows with required column order
- PASS — Total = known + missing in every row
- PASS — Every success rate uses known outcomes only
- PASS — Pooled counts reconcile to branch counts
- PASS — Pooled negative and equal-branch positive: direction reversal confirmed

Input SHA-256: `7102332b96bc80fc775aa9339b5fa13b437299ff6c9a3631a30cc79ea4a47430`

These are descriptive calculations, not causal or inferential validation. Further independent and visual checks are recorded after execution.

## Independent verification
Executed `python /work/verify.py` successfully (exit 0). Checks use explicit fixture counts, independently specified expected differences, and a second execution in a temporary output directory.

- PASS: Exact seven-column header, exactly six unique service/branch rows, and all expected total/known/missing/success counts.
- PASS: All rates are numeric proportions with known outcomes as denominator; JSON has exactly the two required finite numeric values.
- PASS: Pooled difference equals −10/3 pp and equal-branch difference equals +14 pp within absolute tolerance 1e-12.
- PASS: Offline HTML parses, contains a six-row table and caveat text, and has no script, iframe, external stylesheet, image, src or href dependencies.
- PASS: Reexecution in a temporary directory produces byte-identical summary.csv, comparison.json, and report.html. The initial verification also compared generated QA.md before manual notes were appended; the reusable verifier compares the three deliverables so manual notes do not break reruns.
- PASS: A temporary input with an invalid outcome token is rejected with a nonzero exit and the expected validation error; the real source was not changed.
- summary.csv SHA-256 observed: `80e3a7d52e482544b327ae199680722bd9ac2c024febb9d9eb9f7c90e78a9a3e`.

## Render and visual inspection
Executed:
```sh
chromium --headless --no-sandbox --disable-gpu --allow-file-access-from-files --hide-scrollbars --screenshot=/work/report-preview.png --window-size=1200,1600 file:///work/report.html > /work/chromium.log 2>&1
```
Exit 0; screenshot created. Opened `/work/report-preview.png` with the native image viewer. All six rows, both comparison cards, denominator notes, causal/missingness limitations, next step and footer are readable with no visible clipping at 1200×1600. No mobile or print rendering was tested. The screenshot is optional; report.html itself has no asset dependencies.

## Scope
Checks establish calculation and presentation consistency, not unbiased missingness, random assignment, independence across people, or causal identification. All cases are retained in totals; only blank outcomes are excluded from success-rate denominators. No outcomes were imputed. No data corrections were needed. No statistical significance or uncertainty checks were executed.
