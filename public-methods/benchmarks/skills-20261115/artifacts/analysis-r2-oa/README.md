# Cedar pilot comparison

## Reproduce
Uses Python 3.12.16 standard library only; no installation or external requests.
```sh
cd /work
python /work/analysis.py
python /work/verify.py
```
Optional input/output overrides: `python /work/analysis.py --input /task/input/cases.csv --output-dir /work`.
Outputs: `summary.csv` (six rows), `comparison.json`, and self-contained `report.html`.
Verification writes `QA.md`. Open `report.html` directly in an offline browser.

## Results
140 cases; assisted and standard each have 70 cases, 60 known outcomes and 10 unknown.
Pooled success: assisted 38/60 = 63.33%, standard 40/60 = 66.67%; difference −3.33 pp.
East: 8/10 = 80% vs 36/50 = 72%. West: 30/50 = 60% vs 4/10 = 40%.
Equal-branch success: assisted 70%, standard 56%; difference +14 pp.
The sign reverses because service branch mixes differ. Unknowns are not imputed.

## Sources consulted versus methods applied
- Designated first retrieval actually run:
  `python /runtime/research.py oa bundle '{"situation":"Analyze observational Cedar service case log with assisted and standard services, East/West case mix differences and missing resolved outcomes; create reproducible CSV JSON and offline HTML report","goal":"Compute pooled and equal-branch known-outcome success comparisons without imputing unknown outcomes, explain confounding and missingness, and verify runnable report artifacts","mode":"hybrid","limit":3,"max_tokens":2048}'`
  Returned `items: []`. No OpenAkashic method IDs or versions were read or applied.
- Consulted `/skills/catalog.json` for original skill metadata.
- Read `/skills/statistical-analysis/SKILL.md` using `cat`; output was truncated. Then progressively read lines 48–76 with `sed -n '48,76p' /skills/statistical-analysis/SKILL.md` to establish the workflow applied.
  Source frontmatter: `statistical-analysis` version **2.0**, reviewed 2026-10-01; catalog commit `2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5`, catalog-reported SHA-256 `e112848726b3713267cac65e4e2c15491a0a26ee1ed628db01195f7e43f97997` (not independently hash-verified).
- Applied relevant guidance: define case-level descriptive estimands and observational design; inspect group sizes and missingness; report signed effect sizes with explicit denominators and design limitations; preserve reproducibility. Binary counts replace continuous-outcome diagnostics. No supplied scripts, installation commands or hypothesis tests were executed. No other original skill contents were read.

## Actual command record
Inspection commands: `ls -la /work /task/input`; `find /task -name AGENTS.md -o -name TASK.md`; `cat /skills/catalog.json`; `head -15 /task/input/cases.csv`; `wc -l /task/input/cases.csv`; `cat /skills/statistical-analysis/SKILL.md`; the `sed` command above.
An inline Python command read cases with `csv.DictReader`, counted resolved categories by service and branch with `collections.Counter`, and printed `sys.version` and `shutil.which('chromium')`: Python 3.12.16 and `/usr/bin/chromium`.
Files were authored using shell `cat > /work/<filename> <<'…'` heredocs. The runnable analysis and verification commands and their actual results are documented in QA.md; render and visual-inspection results are recorded there after execution.

## Limitations and corrections
Descriptive known-outcome estimates only; missingness may be informative. Equal-branch weighting does not control other confounders or establish causality. No uncertainty intervals or significance tests; case independence and generalizability are unverified. Input validation checks case IDs, categorical domains and known outcomes, but cannot establish log accuracy. No production systems or credentials used. The initial source read was truncated, corrected by a targeted progressive read; no numerical correction has been needed.

## Executed verification and rendering
`python /work/analysis.py` printed 140 cases, pooled difference `-3.3333333333333326` pp, equal-branch difference `13.99999999999999` pp (floating-point representation).
`python /work/verify.py` passed all assertions, including independent expected counts, exact output schema, differences and a byte-identical rerun.
Render commands actually run:
```sh
chromium --headless --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf=/work/report.pdf file:///work/report.html > /work/render.log 2>&1
pdftoppm -scale-to 1500 -png -singlefile /work/report.pdf /work/report-preview
pdfinfo /work/report.pdf | head -17
pdftoppm -f 2 -l 2 -scale-to 1500 -png -singlefile /work/report.pdf /work/report-page2
```
Chromium 156 generated a two-page, tagged letter-size PDF. `report.pdf` and preview PNGs are optional QA artifacts, not required analysis outputs. Page 1 was visually inspected using the native image viewer: clear typography, readable cards, no clipped text; the counts section heading falls at the end of page 1 while its table starts on page 2 (a print-pagination limitation, not an HTML content omission).
Page 2 was also inspected with native `view_image`: all six table rows, denominators, unknown-outcome caveat and decision guidance are readable without clipping. Both image inspections and the print-pagination limitation are documented in QA.md. No numerical or visual corrections were applied.
