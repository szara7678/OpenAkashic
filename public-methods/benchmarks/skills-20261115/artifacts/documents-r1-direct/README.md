# Cedar handover

Deliverables: `handover.pdf` (two-page A4 handover), editable `generate.py`, and `QA.md`. The only factual input is `/task/input/source_notes.md`, records A–D. Content is deliberately fixed in the generator so edits are reviewable; it does not automatically parse future notes.

## Sources consulted and guidance applied
- Initial discovery: `python /runtime/research.py skills search '{"query":"operational handover two-page PDF document layout quality assurance","limit":3}'`.
- Read `/skills/pdf/SKILL.md`, original `pdf` skill; discovery reports commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, SHA-256 `d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee`. No separate skill version is declared. Other returned skills were not read or applied.
- Applied the PDF guide's ReportLab generation and pypdf extraction approaches; Poppler rendering supports visual QA. No supplied scripts were executed. Reference/form guides were unnecessary.

## Commands run
Read/discovery commands, in order:
```sh
python /runtime/research.py skills search '{"query":"operational handover two-page PDF document layout quality assurance","limit":3}'
cat /skills/pdf/SKILL.md; printf '\n---INPUT---\n'; cat /task/input/source_notes.md; printf '\n---FILES---\n'; ls -la /work; fc-list | head -8
```
Files were authored using shell heredocs. Build and validation commands and results are recorded below after execution.

## Editorial decisions and limits
Latest dated notes override the draft: 82 visits (not 86 or unique residents); staffed hours 09:00–18:00 (extension not approved); west-ramp request received, not approved. Water stock and arrival time remain unknown. Owners and deadlines are outstanding, not reported as completed. No staffing count, medical advice, phone number, approval, or outcome is invented. No production action or contact was taken. All input records are synthetic.

Build/validation commands actually run (working directory `/work`):
```sh
python generate.py && pdfinfo handover.pdf && pdftoppm -scale-to 1200 -png handover.pdf handover
```
The first build failed because the assumed `/usr/share/fonts/truetype/dejavu/` directory does not exist here; the chained inspection/render commands did not run on that attempt. Corrected using:
```sh
sed -i 's|/usr/share/fonts/truetype/dejavu/|/usr/share/fonts/dejavu/|g' /work/generate.py
cd /work && python generate.py && pdfinfo handover.pdf && pdftoppm -scale-to 1200 -png handover.pdf handover
cd /work && python check_pdf.py
```
`check_pdf.py` also executes the exact command `pdftotext -bbox /work/handover.pdf /work/bounds.html`. It writes `extracted.txt` and checks page count, A4 dimensions, extracted content, and word coordinates. Generator, checker, README and QA were written with `cat > ... <<'PY'` / `cat > ... <<'MD'` shell heredocs; documentation additions use `cat >>`.

Results: successful generation (25 content blocks within margins); `pdfinfo` reports two A4 pages, 595.276 × 841.89 pt, unencrypted, 47,068 bytes. Checker passes: 381 word boxes inside page boundaries and selectable text on both pages. Both rendered PNGs were opened using native `view_image` and visually inspected: no clipped text, missing glyphs or overlapping elements; clear table, headings and footer. No further layout correction was needed.

Limitations: not a tagged PDF; accessibility conformance was not tested. No physical print test was performed. PNG inspection confirms screen rendering, not printer output. Generator uses installed DejaVu fonts at the paths shown in its source; adapting to another machine may require font path changes. No actual stock, delivery, ramp decision or attendance reconciliation was verified beyond the provided notes.
