from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parent
FONT_ROOT = Path('/usr/share/fonts/dejavu')
pdfmetrics.registerFont(TTFont('Desk', str(FONT_ROOT / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DeskBold', str(FONT_ROOT / 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('Desk', normal='Desk', bold='DeskBold')
WIDTH, HEIGHT = A4
MARGIN = 43
CONTENT = WIDTH - 2 * MARGIN
INK = HexColor('#172B36')
TEAL = HexColor('#255C65')
RULE = HexColor('#B9C6CB')
BODY = ParagraphStyle('Body', fontName='Desk', fontSize=10.5, leading=15.5, textColor=INK)
SMALL = ParagraphStyle('Small', parent=BODY, fontSize=8.6, leading=12.5)
HEADING = ParagraphStyle('Heading', parent=BODY, fontName='DeskBold', fontSize=13, leading=18, textColor=TEAL)
TITLE = ParagraphStyle('Title', parent=BODY, fontName='DeskBold', fontSize=25, leading=31)
PDF = canvas.Canvas(str(ROOT / 'handover.pdf'), pagesize=A4)
PDF.setTitle('Cedar support desk | Shift handover | 18 July 2026')
PDF.setAuthor('Cedar support desk')


def paragraph(text, top, style=BODY, left=MARGIN, width=CONTENT):
    block = Paragraph(text, style)
    _, height = block.wrap(width, HEIGHT)
    assert top - height >= 52, f'Content too low: {text}'
    block.drawOn(PDF, left, top - height)
    return top - height


def section(title, text, top):
    top = paragraph(title, top, HEADING) - 6
    return paragraph(text, top) - 22


def header(page, title, subtitle):
    PDF.setFillColor(TEAL)
    PDF.rect(MARGIN, HEIGHT - 44, 33, 4, fill=1, stroke=0)
    top = paragraph('CEDAR SUPPORT DESK / INTERNAL HANDOVER', HEIGHT - 58, SMALL) - 12
    top = paragraph(title, top, TITLE) - 9
    top = paragraph(subtitle, top, SMALL) - 17
    PDF.setStrokeColor(RULE)
    PDF.line(MARGIN, top, WIDTH - MARGIN, top)
    PDF.setFillColor(INK)
    PDF.setFont('Desk', 8)
    PDF.drawString(MARGIN, 30, 'Snapshot: 18 July 2026, 10:00 local • Internal shift use')
    PDF.drawRightString(WIDTH - MARGIN, 30, f'{page} / 2')
    return top - 22


top = header(1, 'Incoming shift brief', 'Snapshot / cutoff: 18 July 2026 at 10:00, local time')
box_top = top
urgent = (
    '<b>URGENT EXCEPTION — WATER DELIVERY DELAYED</b><br/>'
    'Stock level is unverified; there is no confirmed delivery arrival time. '
    'Do not tell residents the water has arrived or claim a stockout.<br/><br/>'
    '<b>10:30 — Sam Ortiz:</b> check and record water stock.<br/>'
    '<b>11:00 — Leila Noor:</b> obtain the supplier update. '
    'If the update is missed, escalate to <b>Mira Chen</b>.'
)
block = Paragraph(urgent, BODY)
_, box_height = block.wrap(CONTENT - 28, HEIGHT)
PDF.setFillColor(HexColor('#F2F5F6'))
PDF.setStrokeColor(TEAL)
PDF.rect(MARGIN, box_top - box_height - 28, CONTENT, box_height + 28, fill=1, stroke=1)
top = paragraph(urgent, box_top - 14, left=MARGIN + 14, width=CONTENT - 28) - 37

top = section('Today’s opening & access',
    '<b>18 July: staffed opening is 09:00–18:00.</b> The proposed 08:00–20:00 '
    'extension is not approved.<br/>'
    '<b>East entrance:</b> step-free. <b>West entrance:</b> ramp request received, '
    'approval pending. Do not describe the west entrance as accessible.', top)

top = section('Corrected attendance',
    '<b>82 visits on 17 July 2026</b> is the currently verified count. '
    'Owen Reed removed four duplicate sign-ins from the draft count of 86. '
    'This is a visit count, not a count of unique residents; no reliable '
    'unique-resident count is available.', top)

top = section('Urgent medical concerns',
    'The desk does not provide medical assessment. Refer urgent medical '
    'concerns to the existing local emergency procedure.', top)

paragraph('<b>Source basis:</b> /task/input/source_notes.md, records A–D (synthetic). '
    'Latest cutoff: D, 18 July 10:00. B (08:30) corrects A’s hours and ramp status; '
    'C (09:15) corrects A’s attendance. Later explicit corrections take precedence. '
    'See page 2 for outstanding actions and open questions.', top, SMALL)
PDF.showPage()

top = header(2, 'Owners & next actions', 'All deadlines below are on 18 July 2026, local time. Outstanding at cutoff.')
top = paragraph('Action register', top, HEADING) - 10
rows = [
    ('10:30', 'Sam Ortiz', 'Check and record water stock.', 'Quantity is currently unknown.'),
    ('11:00', 'Leila Noor', 'Obtain the supplier update.', 'If the update is missed, escalate to Mira Chen. Arrival time remains unconfirmed.'),
    ('12:00', 'Mira Chen', 'Ask the facilities team for the west-ramp decision.', 'Approval remains pending; a received request is not an approval.'),
    ('13:00', 'Owen Reed', 'Reconcile remaining paper sign-ins.', '82 is the currently verified visit count.'),
]
for deadline, owner, action, status in rows:
    top = paragraph(f'<b>{deadline}  |  {owner}</b>', top) - 4
    top = paragraph(action + ' ' + status, top) - 12
    PDF.setStrokeColor(RULE)
    PDF.line(MARGIN, top, WIDTH - MARGIN, top)
    top -= 15

top = section('Still unresolved at 10:00',
    '<b>West-ramp approval:</b> decision pending.<br/>'
    '<b>Actual water stock:</b> not yet verified.<br/>'
    '<b>Delivery arrival time:</b> no confirmed time.<br/>'
    '<b>Unique-resident count:</b> no reliable count available.', top + 1)

top = section('Authority limits',
    'These records do not authorise extending hours, spending funds, contacting '
    'people automatically, or publishing a resident notice. This handover '
    'records outstanding work, not completed actions or a service expansion.', top)

paragraph('<b>Evidence note:</b> All four actions, deadlines, escalation and unresolved '
    'questions come from record D (18 July 2026, 10:00). Current opening and '
    'entrance arrangements come from B; verified attendance comes from C. '
    'No later outcome is provided in the source.', top, SMALL)
PDF.save()
print(f'Created {ROOT / "handover.pdf"}')
