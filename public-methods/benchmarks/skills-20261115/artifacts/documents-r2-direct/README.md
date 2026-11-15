# Cedar support-desk handover

## Outputs
- `handover.pdf`: two-page A4 operational handover, with selectable text.
- `generate_handover.py`: editable Python source; content is curated from the supplied notes, not dynamically parsed.
- `QA.md`: actual validation results (completed after generation).
- `handover-1.png`, `handover-2.png`: rendered page previews (generated during QA).

## Source and guidance
Only factual input: `/task/input/source_notes.md`, records A–D. Cutoff: 2026-07-18 10:00 local. Source records are synthetic.

Consulted skill: `/skills/pdf/SKILL.md`, original skill `pdf`, package `skill_b645bd7b8fcb43d29d72b7582ece950d`, catalog commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, catalog SHA-256 `d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee`. These identifiers came from discovery, not a separately computed hash. Initial full-file display was truncated; the relevant creation/extraction section was then explicitly read with `sed`.
Applied guidance: ReportLab for PDF creation, pypdf for page/text inspection, Poppler for text extraction. No example script from the skill was executed. A4 replaces the guide's example Letter size; embedded DejaVu Sans supports the document punctuation. No other skill content was read or applied.

## Commands actually run before generation
```sh
python /runtime/research.py skills search '{"query":"two-page PDF operational handover readable printable A4 source notes","limit":3}'
cat /skills/pdf/SKILL.md
cat /task/input/source_notes.md
ls -la /work
fc-list | head -8
sed -n '110,205p' /skills/pdf/SKILL.md
command -v pdftoppm
command -v pdftotext
python -c "import reportlab,pypdf; print('reportlab',reportlab.Version); print('pypdf',pypdf.__version__)"
```
The two grouped inspection commands also used `printf` separators. Files were written with shell heredocs. Installed versions reported: ReportLab 5.1.0; pypdf 7.1.0. Generation and QA commands/results are appended below after execution.

## Editorial decisions / limitations
The 08:00–20:00 proposal, 86 draft visits and “ramp approved” margin note are not treated as current facts. The handover uses 09:00–18:00, 82 visits (not unique residents), and pending ramp approval. Water stock and arrival remain unknown; the 11:00 time is an update deadline, not a delivery ETA. No actual operational action, supplier contact, approval or stock check was performed. The emergency procedure is referenced without invented contact details. No network access, corporate template, diagram or signatures were used.

## Generation and QA commands actually run
```sh
python /work/generate_handover.py
pdftoppm -scale-to 1250 -png /work/handover.pdf /work/handover
pdftotext -layout /work/handover.pdf /work/handover.txt
cat /work/handover.txt
python -c "import importlib.util; print('pdfplumber', bool(importlib.util.find_spec('pdfplumber')))"
python /work/check_handover.py | tee /work/check-results.txt
```
`check_handover.py` also runs `pdftotext -bbox /work/handover.pdf /work/handover-bbox.html`. Both preview images were opened with `view_image`. The optional pdfplumber probe returned False; no pdfplumber guidance was applied. Validation therefore uses installed pypdf and Poppler only.

Result: creation succeeded, exactly two A4 pages, key-text checks passed, no replacement/black-square extraction characters, and all extracted word boxes are inside page boundaries. Both page renders were visually inspected and found readable without clipping or overlap. `QA.md` records checks and caveats; `check-results.txt` contains exact measurements. No post-render layout correction was necessary. Physical printing and tagged-PDF accessibility were not tested.

To reproduce, run `python /work/generate_handover.py` and `python /work/check_handover.py` in this environment. Rendering requires the separate `pdftoppm` command above. The generator requires ReportLab and the installed DejaVu fonts; QA requires pypdf and Poppler. This is a static handover as of the source cutoff, not a live status report.
