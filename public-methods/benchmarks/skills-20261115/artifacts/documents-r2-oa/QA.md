# Executed QA

## Structural and text checks
- `python /work/generate_handover.py` completed and produced `handover.pdf` using ReportLab 5.1.0.
- pypdf 7.1.0 confirmed exactly two pages. Each is 595.2756 × 841.8898 points (A4 portrait).
- Text extraction succeeded: page 1 has 1,144 characters; page 2 has 1,283 characters. Text is PDF text, not a flattened image.
- `pdftotext -layout /work/handover.pdf /work/handover.txt` completed; the extracted text was read.
- `pdftotext -bbox /work/handover.pdf /work/handover-bbox.html` completed. The validator checked every extracted word box against page boundaries: 180 on page 1, 198 on page 2, all within the page.
- `python /work/check_handover.py` passed page count, A4 size, nonempty extraction, word boundaries, and required text checks for the snapshot, corrected count, opening hours, all four owners and deadlines, and pending approval.

## Visual inspection actually performed
Rendered both pages with `pdftoppm -scale-to 1300 -png /work/handover.pdf /work/page`. Opened both `page-1.png` and `page-2.png` with the native image viewer. Both pages have readable headings/body copy, clear hierarchy, comfortable margins and separate footers. No visible clipping, overlap, missing glyphs or awkward page breaks. The shaded urgent-water panel distinguishes immediate actions without relying only on color. Page 2's four action rows and compact source note are legible. No layout correction was necessary after rendering.

## Factual review against the sole input
- Snapshot: 18 July 2026 at 10:00 local time.
- Current staffed opening: 09:00–18:00; 08:00–20:00 is an unapproved proposal.
- Attendance: 82 visits on 17 July after removing four duplicate sign-ins; no unique-resident total asserted.
- Ramp request received, not approved; east entrance step-free; west entrance not described as accessible.
- Water delivery delayed, arrival unconfirmed, stock unverified; no assertion of arrival or stockout.
- Sam: stock check by 10:30. Leila: supplier update at 11:00, escalate to Mira if missed. Mira: ask facilities for ramp decision by 12:00. Owen: reconcile remaining paper sign-ins by 13:00. All dates are 18 July 2026.
- All four unresolved questions, medical-assessment boundary, existing emergency procedure, and restrictions on authority are retained.
- Compact evidence note identifies records A–D and their dated correction sequence. No external facts added.

## Test correction and limitations
The first ad hoc text assertion failed for `approval remains pending` because the extracted text inserted a newline between `remains` and `pending`. This was a test-normalization issue, not missing content. The saved validator normalizes whitespace; its rerun passed. No PDF-content change was needed. No physical print test, tagged-PDF/accessibility certification or live operational verification was performed. The source is synthetic and ends at the cutoff; unknowns remain unknown.
