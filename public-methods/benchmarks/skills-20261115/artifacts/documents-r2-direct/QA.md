# Handover QA

## Executed checks
- `python /work/generate_handover.py` — successful creation, with paragraph bottom-boundary assertions enabled.
- `pdftoppm -scale-to 1250 -png /work/handover.pdf /work/handover` — successfully rendered both pages.
- Both PNGs opened with native `view_image`: inspected headings, line wrapping, urgent callout, source notes, action register and footers. No visible clipping, overlap, missing glyphs or unexpected page breaks. Body text is 10.5 pt, evidence notes 8.6 pt. Layout uses dark text, restrained light shading and generous margins for screen and print.
- `pdftotext -layout /work/handover.pdf /work/handover.txt` — extracted and read both pages, confirming selectable text and logical order.
- `python /work/check_handover.py` — passed; pypdf verifies exactly two A4 pages and key content; Poppler `-bbox` plus XML checks verify every extracted word fits inside the page. See `check-results.txt` for exact counts/bounds.

## Factual review against the only input
- Snapshot is 18 July 2026, 10:00 local, not the generation date.
- Page 1 identifies delayed water as urgent, stock unverified, no delivery ETA, no arrival claim or stockout claim; Sam checks by 10:30; Leila obtains the 11:00 update and escalates to Mira if missed.
- 82 visits for 17 July replaces the draft 86; four duplicates removed. Visits are not unique residents.
- Staffed opening is 09:00–18:00. The 08:00–20:00 proposal is explicitly not approved.
- East entrance is step-free; west ramp remains pending, not approved or described as accessible.
- Page 2 has all four owners and deadlines, including Mira's facilities request by 12:00 and Owen's remaining paper reconciliation by 13:00. All are outstanding, not completed.
- The four unresolved questions, medical-assessment boundary, existing emergency procedure and limits on authority are preserved. Evidence notes distinguish records B, C and D from superseded A.

## Limitations / corrections
No physical print test, screen-reader accessibility audit or live operational verification was performed. The PDF is selectable text but not a tagged accessibility deliverable. No layout correction was needed after the first render. The source's factual corrections are applied as listed above; no missing stock, delivery, approval or unique-resident outcome has been invented.
