# Cedar pilot analysis

## Reproduce
Run `python /work/analysis.py --input /task/input/cases.csv --output-dir /work`.
Only the Python standard library is required. Outputs are `summary.csv` (six rows),
`comparison.json` (numeric percentage-point differences), and offline `report.html`.
Input is read only. The script rejects unexpected schemas/categories/outcomes,
nonrectangular rows, missing/duplicate IDs, and zero known-outcome denominators.
`1` is interpreted as success, `0` as failure, and blank as unknown.

## Results
Full input: 140 cases, 120 known outcomes, 20 unknown. Assisted: 38/60 = 63.33%
known-outcome success; standard: 40/60 = 66.67%. Pooled difference: −3.33 pp.
Equal-branch rates: 70% vs 56%, a +14 pp difference. Assisted is higher in both
branches; branch composition reverses the pooled ranking. Each service has 10/70
unknown outcomes, but standard West has 9/19 unknown. No unknown is imputed.

## Sources consulted versus methods applied
- Discovery command: `python /runtime/research.py skills search '{"query":"observational service comparison pooled stratified success rates missing outcomes report","limit":3}'`.
- Read `/skills/exploratory-data-analysis/SKILL.md` using `cat`, then
  `sed -n '105,235p' /skills/exploratory-data-analysis/SKILL.md` to recover the
  relevant reasoning/workflow section after the first tool output was truncated.
- Consulted skill: exploratory-data-analysis, metadata version **1.4**, last reviewed
  **2026-09-30**, catalog commit `2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5`.
  No other skill source or linked reference was read. Catalog identifiers are source
  metadata, not a claim that optional package versions were installed or verified.
- Applied guidance: preserve raw input, distinguish missingness from failure,
  disclose denominators and scope, report effect sizes, document reproducibility,
  avoid causal claims. Implemented the task-specific stratified comparison directly;
  did not run supplied scripts, install packages, or apply the entire generic EDA workflow.
- Correction: the initial `head -12 /task/input/cases.csv` inspection displayed raw
  sample IDs despite the skill's aggregate-only guidance. No IDs appear in final reports;
  subsequent profiling and outputs use aggregates. The sample alone was not treated
  as validation; all 140 records are parsed and checked.

## Execution record
Initial inspection also ran `ls -la /task/input`, `ls -la /work`,
`command -v chromium`, and `command -v pdftoppm`.
An inline standard-library Python profile counted all records by service, branch,
and outcome and counted unique IDs (140). Artifact files were written with shell
heredocs. Exact analysis and verification commands and their actual results are
recorded below and in QA.md as completed.

## Limitations
Observational association only; equal-branch weighting is not full severity/routing
adjustment. Missingness may be informative, especially in standard West. No dates,
severity variables, allocation mechanism, or validated follow-up definition are
available. No causal effect, confidence interval, or significance claim is made.
No external requests, credentials, production systems, or external assets are used.

### Completed validation commands
```sh
python /work/analysis.py --input /task/input/cases.csv --output-dir /work
python /work/verify.py
chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --no-pdf-header-footer --print-to-pdf=/work/report.pdf file:///work/report.html > /work/render.log 2>&1
pdftoppm -scale-to 1500 -png -singlefile /work/report.pdf /work/report-preview
pdfinfo /work/report.pdf | head -18
pdftoppm -f 2 -l 2 -scale-to 1500 -png -singlefile /work/report.pdf /work/report-page2
python --version
```
`verify.py` passed exact expected counts, schemas, all rates, JSON differences,
offline HTML structural checks, a byte-identical rerun in a temporary directory,
and unchanged input digest. It invokes the same analysis command with a temporary
output directory via the current Python executable. See QA.md for the actual digest.
Chromium successfully rendered a two-page tagged Letter PDF (63,660 bytes), with
JavaScript reported as absent by `pdfinfo`. PNG previews are auxiliary QA artifacts;
`report.html` is the requested self-contained deliverable. Page 1 was inspected with
the native image viewer: clear cards, readable text, no horizontal clipping. The
print layout places the intact table on page 2 after its introduction on page 1;
HTML remains a continuous scroll. No styling correction was necessary on page 1.
Page 2 was also inspected with the native image viewer: all six table rows,
limitations, next step and footer are legible and unclipped. Both pages passed
visual review; mobile rendering was not separately checked. Actual Python runtime:
3.12.16. QA.md records these completed checks. Documentation additions used shell
heredocs (`cat >> /work/QA.md` and `cat >> /work/README.md`); they do not modify
analysis outputs or raw input.
