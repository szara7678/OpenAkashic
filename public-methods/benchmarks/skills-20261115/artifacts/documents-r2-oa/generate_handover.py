from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.colors import HexColor

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = A4
MARGIN = 44
CONTENT = WIDTH - 2 * MARGIN
INK = '#182D35'
MUTED = '#465B63'
TEAL = '#245D62'

pdf = canvas.Canvas(str(ROOT / 'handover.pdf'), pagesize=A4)
pdf.setTitle('Cedar support desk | Shift handover | 18 July 2026')
pdf.setAuthor('Cedar support desk')


def text(content, top, size=11.5, bold=False, color=INK, width=CONTENT, left=MARGIN, leading=None):
    style = ParagraphStyle('text', fontName='Helvetica-Bold' if bold else 'Helvetica',
                           fontSize=size, leading=leading or size * 1.38, textColor=HexColor(color))
    paragraph = Paragraph(content, style)
    _, height = paragraph.wrap(width, HEIGHT)
    assert top + height < HEIGHT - 44, (content, top, height)
    paragraph.drawOn(pdf, left, HEIGHT - top - height)
    return top + height


def line(top):
    pdf.setStrokeColor(HexColor('#CCD5D8'))
    pdf.setLineWidth(0.6)
    pdf.line(MARGIN, HEIGHT - top, WIDTH - MARGIN, HEIGHT - top)


def header(page, title, subtitle):
    text('CEDAR / SUPPORT DESK', 35, 10, True, TEAL)
    text(title, 63, 26, True, leading=30)
    text(subtitle, 104, 10.5, color=MUTED)
    line(134)
    pdf.setFont('Helvetica', 9)
    pdf.setFillColor(HexColor(MUTED))
    pdf.drawString(MARGIN, 28, 'Internal operational handover | Synthetic source records')
    pdf.drawRightString(WIDTH - MARGIN, 28, f'{page} / 2')


header(1, 'Incoming shift handover', 'Snapshot: 18 July 2026, 10:00 local time')
text('CURRENT SNAPSHOT', 152, 10, True, TEAL)
text('09:00–18:00', 177, 23, True)
text('Confirmed staffed opening today, 18 July 2026. The proposed<br/>08:00–20:00 extension is <b>not approved</b>. [B]', 216)
line(263)
text('82 visits', 279, 23, True)
text('Verified attendance for 17 July 2026, after four duplicate sign-ins<br/>were removed. This is <b>not</b> a count of unique residents. [C]', 317)

pdf.setFillColor(HexColor('#F5F1E9'))
pdf.roundRect(MARGIN, HEIGHT - 568, CONTENT, 190, 6, fill=1, stroke=0)
text('URGENT EXCEPTION / WATER DELIVERY', 393, 10, True, '#684918', left=60, width=CONTENT-32)
text('Delayed; stock not yet verified', 417, 16, True, left=60, width=CONTENT-32)
text('<b>10:30 — Sam Ortiz:</b> check and record water stock.<br/>'
     '<b>11:00 — Leila Noor:</b> obtain the supplier update.<br/>'
     '<b>If the 11:00 update is missed:</b> Leila escalates to Mira Chen.',
     450, left=60, width=CONTENT-32)
text('No confirmed arrival time. Do not say water has arrived or claim a stockout. [B, D]',
     520, 10.5, left=60, width=CONTENT-32)

text('ACCESS / APPROVAL STILL PENDING', 590, 10, True, TEAL)
text('The <b>east entrance is step-free</b>. The west-ramp request has been received, '
     'but approval remains pending. Do not describe the west entrance as accessible. [B, D]', 614)
text('MEDICAL CONCERNS', 682, 10, True, TEAL)
text('The desk does not provide medical assessment. Refer urgent medical concerns '
     'to the existing local emergency procedure. [D]', 705, 11)
text('Evidence: source_notes.md, records B–D. Source chronology and action register: page 2.',
     765, 9, color=MUTED)
pdf.showPage()

header(2, 'Owners & next actions', 'All deadlines: 18 July 2026, local time | Outstanding at the 10:00 cutoff')
text('ACTION REGISTER', 152, 10, True, TEAL)


def action(top, deadline, owner, task, status):
    text(deadline, top, 17, True, TEAL, width=77)
    text(owner, top, 12, True, left=137, width=WIDTH-181)
    bottom = text(task, top+23, 11.5, left=137, width=WIDTH-181)
    bottom = text(status, bottom+5, 10, color=MUTED, left=137, width=WIDTH-181)
    line(bottom+13)
    return bottom+29

position = 180
position = action(position, '10:30', 'Sam Ortiz', 'Check and record water stock.', 'Current quantity is unknown. [D]')
position = action(position, '11:00', 'Leila Noor', 'Obtain the supplier update; escalate to Mira Chen if missed.', 'Delivery arrival time is not confirmed. [B, D]')
position = action(position, '12:00', 'Mira Chen', 'Ask the facilities team for the west-ramp decision.', 'Approval remains pending; a received request is not approval. [B, D]')
position = action(position, '13:00', 'Owen Reed', 'Reconcile remaining paper sign-ins.', '82 visits is the currently verified count. [C, D]')

text('UNRESOLVED AT CUTOFF', position+1, 10, True, TEAL)
text('Ramp approval; actual water stock; delivery arrival time; reliable unique-resident count. [D]', position+23, 11)
text('AUTHORITY BOUNDARIES', position+68, 10, True, TEAL)
text('These records do not permit extending hours, spending funds, contacting people automatically, or publishing a resident notice. [D]', position+90, 11)

text('SOURCE / CORRECTIONS', 690, 10, True, TEAL)
text('Sole factual basis: /task/input/source_notes.md (synthetic internal records). '
     'A: 17 July, 16:00 draft; B: 18 July, 08:30 coordinator update; '
     'C: 18 July, 09:15 verified correction; D: 18 July, 10:00 cutoff. '
     'B supersedes A on hours and ramp status; C corrects A’s 86 to 82 visits. '
     'D defines outstanding actions and unknowns. No later outcomes are evidenced.',
     713, 9.5, leading=12.5)
pdf.save()
print('Created', ROOT / 'handover.pdf')
