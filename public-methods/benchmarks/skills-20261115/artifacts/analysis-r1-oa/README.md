# Cedar pilot comparison

## Reproduce
Python 3 standard library only; no installs, credentials, or network needed.

```sh
python /work/analysis.py --input /task/input/cases.csv --outdir /work
```

Artifacts: `summary.csv` (six rows), `comparison.json`, `report.html` (offline, inline CSS). Open the HTML in any browser. `QA.md` records actual checks; visual QA artifacts are supplemental.

## Results and methods
140 cases; 120 known outcomes and 20 unknown. Assisted: 38/60 known successes; standard: 40/60. Pooled assisted-minus-standard difference: −3.3333333333333326 percentage points. Equal branch weights: assisted 70%, standard 56%, difference +14 percentage points (floating-point serialization may differ at machine precision). Branch differences: East +8 pp, West +20 pp. No unknown outcomes are imputed. Rates are numeric proportions in CSV; presentation rounds to one decimal for rates and two for headline differences.

The estimands are pooled known-outcome success and an equal-weight mean of East and West known-outcome success rates, at the case level. Input validation rejects duplicate/missing case IDs, unexpected columns, labels or outcome values, and empty known-outcome groups. The displayed narrative is specific to this supplied Cedar fixture, not a general-purpose report template for arbitrary replacement datasets.

## Consulted sources vs applied guidance
- Designated initial retrieval executed exactly:
  `python /runtime/research.py oa bundle '{"situation":"Observational Cedar service log in /task/input/cases.csv, assisted versus standard across East and West with differing case mix and unknown outcomes","goal":"Reproducible analysis with six-row known-outcome summary, pooled and equally weighted branch differences, and readable offline HTML report with missingness, noncausal interpretation and verified artifacts","mode":"hybrid","limit":3,"max_tokens":2048}'`
- Complete method read: `method_c308cd0b8ee945fdbb32109d6bccedae`, version 1, source hash `23d2d90faf19d5aed3d1654667dd2ac25a27ecc931f1e78080aa1e46498e4335`. It concerns ReportLab PDF generation and subscripts; consulted but **not applied**, since the deliverable is HTML. No retrieved OpenAkashic method was applied.
- Read `/skills/catalog.json` metadata and lines 1–200 of `/skills/statistical-analysis/SKILL.md`. Statistical-analysis metadata version **2.0**, commit `2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5`, catalog SHA-256 `e112848726b3713267cac65e4e2c15491a0a26ee1ed628db01195f7e43f97997` (catalog identifier, not independently recomputed). Applied relevant overview/workflow guidance: define estimands and case unit, inspect group sizes and missingness, report signed effect sizes, and separate descriptive associations from causal validity. Did not execute source snippets, install its suggested stack, or apply its inferential testing workflows. No other original skill body was read.

## Commands and inspection record
- Initial shell inspection: `ls -la /work; ls -la /task/input; cat /skills/catalog.json; head -12 /task/input/cases.csv; wc -l /task/input/cases.csv; command -v chromium || command -v chromium-browser; find /task -name AGENTS.md` (140 records plus header; Chromium found).
- Guidance inspection: `sed -n '1,200p' /skills/statistical-analysis/SKILL.md` and a Python CSV/Counter grouping by `(service, branch)` (East assisted 14, West assisted 56, East standard 51, West standard 19). The combined output had an elision in the middle; only visible guidance is treated as consulted.
- Artifact creation used shell heredocs. The exact reproducibility command above was run successfully. Subsequent verification/render commands and actual results are recorded in `QA.md`.

## Limitations and corrections
Observational allocation, unmeasured within-branch case mix, uneven branch-specific missingness, and unverified independence prevent causal conclusions. Equal branch weighting is a hypothetical target mix, not proof that branch is the only confounder. No confidence intervals, hypothesis tests, or model-based adjustment are claimed. Input fixtures remain unchanged. The initial retrieval was not relevant to the comparison, so original statistical guidance was consulted instead; PDF-specific methods were not used.

## Verification results
Executed `python /work/verify.py`: all assertions passed, including fixture-specific count/rate checks, both comparison values, malformed-input rejection, offline HTML resource checks and byte-for-byte rerun reproducibility. Rendered with local Chromium and Poppler; inspected both PDF page previews with native image viewing. `QA.md` lists the exact rendering commands, environment observations and scope. No numerical corrections were necessary. Supplemental artifacts: `verify.py`, `report.pdf`, `report-preview.png`, `report-preview-page2.png`, and `chromium.log`.
