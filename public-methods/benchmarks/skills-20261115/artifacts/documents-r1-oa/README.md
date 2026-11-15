# Cedar handover

Deliverable: `handover.pdf`; editable content and layout: `generate_handover.py`.
The only factual input is `/task/input/source_notes.md` (records A–D). No network, credentials or production systems were used. The document is a cutoff snapshot, not a claim that actions were completed.

## Sources consulted versus methods applied
- Designated first retrieval: `python /runtime/research.py oa bundle '{"situation":"Create a two-page A4 operational support-desk handover PDF from dated source notes, respecting corrections, pending requests versus approvals, urgent accessibility exception, owners and deadlines","goal":"Produce selectable, readable, print-ready exactly two-page PDF plus editable generator, source evidence note and honest rendered visual QA","mode":"hybrid","limit":3,"max_tokens":2048}'`. Result: ready, empty items. No method IDs or versions returned or applied.
- Read `/skills/catalog.json`, then the complete `/skills/pdf/SKILL.md`. Catalog identifies pdf commit `1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064`, entrypoint SHA-256 `d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee`. This is the only skill text consulted. No separate skill version is declared in its frontmatter.
- Applied PDF guidance: ReportLab creation, explicit page breaks, pypdf page/text checks and Poppler text extraction. Used local embedded fonts. Did not execute skill example scripts. Other catalog entries were metadata only, not applied guidance.
- Editorial method: preserve dated precedence; place the urgent water exception first; distinguish received requests from approval; list four outstanding owners/deadlines; preserve all unknowns and authority limits.

## Commands actually run
Initial inspection used `cat /task/input/source_notes.md`, `cat /skills/catalog.json`, `ls -la /work`, `command -v pdftoppm`, `command -v pdftotext`, `fc-list | head -8`, and `cat /skills/pdf/SKILL.md`.
Files were written with shell heredocs. Build and validation commands and results follow below; see also `QA.md`.

```sh
cd /work
python generate_handover.py
pdftoppm -scale-to 1400 -png handover.pdf preview
pdftotext -layout handover.pdf handover.txt
```

## Limitations and corrections
No added factual sources, branding, contact details, medical advice or approvals. Corrected 86 draft visits to 82 verified visits; retained 09:00–18:00 opening instead of proposed 08:00–20:00; west-ramp approval remains pending. Water stock and arrival time remain unknown. No live status was checked. Generator requires installed ReportLab and the local DejaVu font paths specified in the file. Rebuild from `/work` with `python generate_handover.py`.

## Executed corrections and final checks
The initial generator failed on an unavailable font directory. Exact correction:
```sh
sed -i 's@/usr/share/fonts/truetype/dejavu/@/usr/share/fonts/dejavu/@g' /work/generate_handover.py
cd /work && python generate_handover.py && pdftoppm -scale-to 1400 -png handover.pdf preview && pdftotext -layout handover.pdf handover.txt
```
The first `cd /work && python check_pdf.py` failed with `ModuleNotFoundError: pdfplumber`. Rewrote `check_pdf.py` to use installed pypdf and Poppler instead. Then ran:
```sh
cd /work && python check_pdf.py
```
The successful checker internally executes `pdftotext -bbox /work/handover.pdf /work/bounds.html` and writes `qa_results.json`. Result: exactly two A4 pages, selectable text, all extracted word bounds inside their pages, required content tokens present. Opened `/work/preview-1.png` and `/work/preview-2.png` using native `view_image`; no visible clipping, overlap or missing glyphs. `QA.md` records the actual checks and limitations. No physical printing or screen-reader testing was performed.
