# QA record

Initial content review: sole factual basis is records A–D of `/task/input/source_notes.md`. The handover separates requests from approvals and labels the snapshot, attendance correction, water exception, four action owners/deadlines, and unresolved questions. Generation and visual checks are recorded after execution below.

## Executed checks and outcomes
- `python generate.py`: PASS after correcting the installed font directory; 25 content blocks fit the generator's margins. Initial failure was a missing assumed font path, not a content/layout error.
- `pdfinfo handover.pdf`: exactly 2 pages; A4 (595.276 × 841.89 points); unencrypted PDF 1.4, 47,068 bytes.
- `python check_pdf.py`: PASS. Uses pypdf to assert two A4 pages, extract text from each, and check required snapshot/content strings. Poppler `pdftotext -bbox /work/handover.pdf /work/bounds.html` supplies coordinate checks: all 381 word boxes lie within page boundaries. Extracted text is retained as `extracted.txt`.
- `pdftoppm -scale-to 1200 -png handover.pdf handover`: produced `handover-1.png` and `handover-2.png`. Both were opened and inspected with native `view_image`. No visible clipping, collisions, unreadable glyphs or footer overlap; column text wraps cleanly. The urgent exception is prominent on page 1; owners, times and next steps are easy to scan on page 2.
- Manual comparison against records A–D: snapshot is 18 July 2026 at 10:00 local; 82 visits is linked to 17 July and not presented as unique residents; opening is 09:00–18:00; extension is not approved. West-ramp request remains pending, while east entrance is step-free. Stock and arrival time remain unknown. All four owners/deadlines and the missed-update escalation to Mira are included. Medical boundary and authority limits are preserved. Evidence note identifies dated corrections rather than treating the draft as current.

## Limits
No physical print, screen-reader or PDF accessibility conformance test was run; PDF is not tagged. Automated bounds checks do not alone prove absence of overlap, hence the separate visual inspection. No operational outcomes or approvals were independently verified, and all supplied records are synthetic.
