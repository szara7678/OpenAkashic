# Executed quality assurance

## Commands and observed results

1. `python /work/analysis.py --input /task/input/cases.csv --outdir /work`
   - Exit 0; 140 input cases.
   - Input SHA-256 (computed from fixture bytes): `7102332b96bc80fc775aa9339b5fa13b437299ff6c9a3631a30cc79ea4a47430`.
   - JSON results: pooled difference `-3.3333333333333326` pp; equal-branch difference `13.99999999999999` pp. These are machine-precision representations of −3⅓ and +14 pp.
2. `python /work/verify.py`
   - Exit 0; all assertions passed.
   - Checked exact CSV column order, exactly six unique service/branch rows, all expected counts and numeric rates, total = known + missing, and successes <= known.
   - Independent fixture expectations: assisted East (14 total, 10 known, 4 missing, 8 successes); assisted West (56, 50, 6, 30); standard East (51, 50, 1, 36); standard West (19, 10, 9, 4). Service pooled rows each have 70 total, 60 known and 10 missing, with 38 and 40 successes respectively.
   - Checked both JSON numeric keys, differences within absolute tolerance 1e-12, and direction reversal.
   - Parsed HTML: seven table rows including header; no external resource attributes, URL strings, or CSS imports. Confirmed explicit unknown-outcome wording.
   - Reran analysis into a temporary directory: all three generated deliverables were byte-identical.
   - Tested three malformed fixture variants in a temporary directory: invalid outcome, duplicate case ID and unexpected branch each produced a nonzero exit. No changes to original fixtures.
3. `chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --no-pdf-header-footer --print-to-pdf=/work/report.pdf file:///work/report.html > /work/chromium.log 2>&1`
   - Exit 0; produced a two-page PDF for visual QA. The requested deliverable remains the standalone HTML; PDF is supplemental.
4. `pdftoppm -scale-to 1500 -png -singlefile /work/report.pdf /work/report-preview`
   - Exit 0; rendered first-page preview.
5. `pdfinfo /work/report.pdf | head -18`
   - Two letter-size pages; tagged PDF, no JavaScript. Producer: Skia/PDF m156; Chromium creator version 156.0.0.0.
6. `python --version`
   - Python 3.12.16. Analysis and verification use only standard-library modules.
7. `pdftoppm -f 2 -l 2 -scale-to 1500 -png -singlefile /work/report.pdf /work/report-preview-page2`
   - Exit 0; rendered second-page preview.

## Visual review
Used native image viewing on `report-preview.png` and `report-preview-page2.png`. Checked headline, paired result cards, explanation of reversal, table counts and denominators, unknown-outcome discussion, recommendation and footer. Text is legible with no clipping or overlap. The table moves intact to the second printed page. HTML is a continuous offline document; mobile CSS is supplied but no separate mobile viewport inspection was executed.

## Scope and caveats
No significance, uncertainty, causality, missing-at-random assumption, or independence check is claimed. Input ID uniqueness is not proof of independent observations. HTML parser checks are basic structural/resource checks, not full standards or accessibility certification. No external requests, source scripts, production systems or credentials were used. No numerical corrections were needed after verification. The fixture-specific report narrative is not intended to auto-adapt to unrelated future inputs; computed CSV and JSON are data-driven.
