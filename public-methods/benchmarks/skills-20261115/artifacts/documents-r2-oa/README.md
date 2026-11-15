# Cedar support-desk handover

## Outputs and reproduction
- `handover.pdf`: two-page A4 operational handover.
- `generate_handover.py`: editable ReportLab generator; all handover copy is editable in this file.
- `QA.md`: actual validation results (completed after generation).
- `page-1.png`, `page-2.png`: page renders for visual review.

Commands run from `/work` (file creation used shell heredocs):
```sh
python /runtime/research.py oa bundle '{"situation":"Prepare a two-page A4 operational support-desk handover PDF from dated source notes, preserving latest corrections, request versus approval distinctions, urgent accessibility exception and action ownership.","goal":"Create runnable editable PDF generator, readable selectable two-page handover, render and visually inspect both pages, document actual source and QA checks.","mode":"hybrid","limit":3,"max_tokens":2048}'
cat /task/input/source_notes.md
cat /skills/catalog.json
ls -la /work
command -v pdftoppm
command -v pdftotext
cat /skills/pdf/SKILL.md
python /work/generate_handover.py
pdftoppm -scale-to 1300 -png /work/handover.pdf /work/page
pdftotext -layout /work/handover.pdf /work/handover.txt
```

## Guidance consulted versus applied
The designated first retrieval returned `items: []`: no method IDs or versions were read or applied. Read `/skills/catalog.json` metadata, then the full `/skills/pdf/SKILL.md` only. PDF skill metadata: commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, SHA-256 `d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee` (identifiers reported by the provided catalog, not independently hashed). Applied its ReportLab creation, pypdf page/text inspection, and Poppler text-extraction guidance. Other skills were not read or applied; examples in source guidance were reviewed, not executed as scripts.

## Factual source, corrections and limitations
Only `/task/input/source_notes.md` supplies handover facts; all records are synthetic. B overrides draft hours and ramp approval; C corrects 86 to 82 visits, not unique residents; D defines the 10:00 snapshot and outstanding actions. No delivery arrival, stock quantity, ramp approval or unique-resident total is inferred. The document grants no new authority and does not report later outcomes. No network, external template, brand asset, contacts or production systems are used. Installed ReportLab and Poppler are required to regenerate and render; pypdf is used for QA. This is a selectable PDF, not a tagged-PDF accessibility certification.

## Result
Generation and QA results are recorded in `QA.md`; visual review will be recorded only after inspecting both renders.

## Final executed QA commands and results
```sh
cat /work/handover.txt
pdftotext -bbox /work/handover.pdf /work/handover-bbox.html
python /work/check_handover.py
```
An initial inline Python QA command used pypdf and ElementTree for the same structural/bounds checks and a literal substring check. It confirmed two A4 pages, 1,144/1,283 extracted characters, and 180/198 in-bounds word boxes, then failed the phrase `approval remains pending` because of an extracted line break. The saved `check_handover.py` corrects that test by normalizing whitespace and passed on rerun. This was not a content correction. Actual versions reported by the check: ReportLab 5.1.0 and pypdf 7.1.0. Both page PNGs were opened with the native image viewer and visually inspected; no overlap, clipping or missing glyphs was seen. Final result: two readable A4 pages with selectable text and the required operational distinctions. Full check details and unperformed checks are in `QA.md`.
