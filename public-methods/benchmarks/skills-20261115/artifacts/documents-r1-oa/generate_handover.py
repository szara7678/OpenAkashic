from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parent
pdfmetrics.registerFont(TTFont('Desk', '/usr/share/fonts/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DeskBold', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'))
pdfmetrics.registerFontFamily('Desk', normal='Desk', bold='DeskBold')
WIDTH, HEIGHT = A4
MARGIN = 44
CONTENT = WIDTH - 2 * MARGIN
INK = HexColor('#182C35')
TEAL = HexColor('#205B60')
MUTED = HexColor('#4D5C64')
PDF = canvas.Canvas(str(ROOT / 'handover.pdf'), pagesize=A4)
PDF.setTitle('Cedar support desk | Shift handover | 18 July 2026')
PDF.setAuthor('Cedar support desk')


def text(content, top, size=11, leading=16, color=INK, bold=False, left=MARGIN, width=CONTENT):
    style = ParagraphStyle('body', fontName='DeskBold' if bold else 'Desk', fontSize=size,
                           leading=leading, textColor=color)
    paragraph = Paragraph(content, style)
    _, height = paragraph.wrap(width, HEIGHT)
    assert top + height < HEIGHT - 44, (content, top, height)
    paragraph.drawOn(PDF, left, HEIGHT - top - height)
    return top + height


def heading(label, top):
    return text(label, top, 13, 18, TEAL, True) + 8


def frame(number, title, subtitle):
    PDF.setFillColor(TEAL)
    PDF.rect(MARGIN, HEIGHT - 39, 36, 4, fill=1, stroke=0)
    text('CEDAR / INTERNAL SHIFT HANDOVER', 48, 9, 12, TEAL, True)
    text(title, 73, 25, 31, INK, True)
    text(subtitle, 114, 10, 15, MUTED)
    PDF.setStrokeColor(HexColor('#C9D3D6'))
    PDF.line(MARGIN, 39, WIDTH - MARGIN, 39)
    PDF.setFont('Desk', 8)
    PDF.setFillColor(MUTED)
    PDF.drawString(MARGIN, 25, 'Snapshot: 18 Jul 2026, 10:00 local | Synthetic source records')
    PDF.drawRightString(WIDTH - MARGIN, 25, f'{number} / 2')


frame(1, 'Current shift snapshot', 'Cutoff: 18 July 2026, 10:00 local time • Operational handover')
next_top = heading('Urgent exception / delayed water delivery', 153)
PDF.setFillColor(HexColor('#F5F1E8'))
PDF.rect(MARGIN, HEIGHT - 353, CONTENT, 173, fill=1, stroke=0)
text('Stock is unverified. No delivery arrival time is confirmed.', 192, 11, 16, INK, True, MARGIN + 13, CONTENT - 26)
text('<b>10:30 — Sam Ortiz:</b> check and record water stock.', 235, 11, 16, left=MARGIN + 13, width=CONTENT - 26)
text('<b>11:00 — Leila Noor:</b> obtain the supplier update. If it is missed, escalate to <b>Mira Chen</b>.', 262, 11, 16, left=MARGIN + 13, width=CONTENT - 26)
text('Do not tell residents water has arrived or claim a stockout.', 313, 10, 15, left=MARGIN + 13, width=CONTENT - 26)
next_top = heading('Confirmed position', 376)
next_top = text('<b>Opening today:</b> staffed 09:00–18:00 on 18 July 2026. The proposed 08:00–20:00 extension is <b>not approved</b>.', next_top) + 14
next_top = text('<b>Attendance for 17 July:</b> <b>82 visits</b>, corrected at 09:15 after four duplicate sign-ins were removed from the draft 86. This is not a count of unique residents; no reliable unique-resident count is available.', next_top) + 14
next_top = text('<b>Access:</b> the east entrance is step-free. The west-ramp request was received, but approval is <b>still pending</b>. Do not describe the west entrance as accessible.', next_top) + 22
next_top = heading('Service boundary', next_top)
text('The desk does not provide medical assessment. Refer urgent medical concerns to the existing local emergency procedure.', next_top)
PDF.showPage()

frame(2, 'Owners & next actions', 'All deadlines: 18 July 2026, local time • Outstanding at the 10:00 cutoff')
next_top = 153
for deadline, owner, action in [
    ('10:30', 'Sam Ortiz', 'Check and record water stock. Quantity is currently unknown.'),
    ('11:00', 'Leila Noor', 'Obtain the supplier update; escalate to Mira Chen if the update is missed. Arrival time remains unconfirmed.'),
    ('12:00', 'Mira Chen', 'Ask the facilities team for the west-ramp decision by this time. Approval remains pending.'),
    ('13:00', 'Owen Reed', 'Reconcile remaining paper sign-ins. The currently verified count remains 82 visits for 17 July.'),
]:
    PDF.setStrokeColor(HexColor('#D6DFE0'))
    PDF.line(MARGIN, HEIGHT - next_top, WIDTH - MARGIN, HEIGHT - next_top)
    text(deadline, next_top + 11, 12, 17, TEAL, True, width=64)
    text(owner, next_top + 10, 11, 16, INK, True, MARGIN + 78, CONTENT - 78)
    bottom = text(action, next_top + 31, 10.5, 15, left=MARGIN + 78, width=CONTENT - 78)
    next_top = bottom + 17
next_top = heading('Unresolved at cutoff', next_top + 5)
next_top = text('West-ramp approval • Actual water stock • Delivery arrival time • Reliable unique-resident count', next_top, 10.5, 16) + 17
next_top = heading('Authority limits', next_top)
next_top = text('These records do not authorise extending hours, spending funds, contacting people automatically, or publishing a resident notice.', next_top, 10.5, 16) + 19
next_top = heading('Evidence basis', next_top)
text('Sole factual source: <b>/task/input/source_notes.md</b> (synthetic records). A: draft, 17 Jul 16:00; B: coordinator update, 18 Jul 08:30; C: verified attendance correction, 18 Jul 09:15; D: handover cutoff, 18 Jul 10:00. Later dated corrections take precedence over the draft. Actions and unknowns reflect D; no completion is inferred.', next_top, 9, 13, MUTED)
PDF.showPage()
PDF.save()
print(f'Created {ROOT / "handover.pdf"}')
