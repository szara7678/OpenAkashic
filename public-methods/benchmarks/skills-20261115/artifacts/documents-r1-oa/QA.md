# Actual quality checks

## Automated checks executed
- `python generate_handover.py`: succeeded after correcting the local font directory. Produces PDF using embedded DejaVu fonts and two explicit pages. Generator asserts paragraph bottoms stay above the footer area.
- `pdftoppm -scale-to 1400 -png handover.pdf preview`: succeeded, producing `preview-1.png` and `preview-2.png`.
- `pdftotext -layout handover.pdf handover.txt`: succeeded; creates selectable text extraction for review.
- `python check_pdf.py`: passed. Uses pypdf and Poppler `pdftotext -bbox`, then parses bounding boxes with Python's standard XML library. Checks exactly two pages, A4 dimensions (595.276 × 841.890 points within tolerance), nonempty extracted words, every word bounding box inside the page, and required names, times and key content tokens. Detailed per-page results are in `qa_results.json`; raw bounds are in `bounds.html`.

## Visual checks executed
Opened both rendered PNGs with native `view_image`. Both pages show clear headings, readable body text, intact accented punctuation, aligned action rows, visible page numbers and generous margins. No clipping, overlaps or missing-glyph boxes were visible. The urgent water exception is prominent on page 1. Page 2 fits the four owners/deadlines, unresolved questions, authority limits and source note without crowding.

## Factual review against the sole source
- Snapshot is 18 July 2026, 10:00 local; all action deadlines explicitly share that date.
- Attendance is 82 visits for 17 July, not unique residents; four duplicate sign-ins explain the correction from 86.
- Opening is 09:00–18:00; the proposed extension is not approved.
- East entrance is step-free; west-ramp request is received but approval remains pending.
- Delivery is delayed; stock and arrival time remain unknown. Sam checks stock at 10:30, Leila obtains the 11:00 update and escalates to Mira if missed.
- Mira asks facilities for the decision by 12:00; Owen reconciles paper sign-ins by 13:00. No action is represented as completed.
- Medical and authority limits are preserved; no invented contact details, spending permissions, staffing totals or outcomes.

## Corrections and limitations
The first build failed because `/usr/share/fonts/truetype/dejavu/` did not exist; changed to the installed `/usr/share/fonts/dejavu/` and rebuilt successfully. The initial QA script failed because pdfplumber was not installed; replaced it with installed pypdf plus Poppler bounding-box extraction, with no dependency installation. No physical print, live operational check, or screen-reader accessibility conformance test was performed. Bounding-box checks establish in-page text placement, not full tagged-PDF accessibility. The notes themselves are synthetic.
