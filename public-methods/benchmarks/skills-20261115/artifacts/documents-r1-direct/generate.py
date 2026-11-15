from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parent
pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'))
pdfmetrics.registerFontFamily('DejaVu', normal='DejaVu', bold='DejaVu-Bold')
WIDTH, HEIGHT = A4
MARGIN = 44
CONTENT = WIDTH - 2 * MARGIN
INK = HexColor('#182D3B')
MUTED = HexColor('#425767')
TEAL = HexColor('#12666A')
PALE = HexColor('#EFF5F5')
AMBER = HexColor('#FFF3DC')
pdf = canvas.Canvas(str(ROOT / 'handover.pdf'), pagesize=A4)
pdf.setTitle('Cedar support desk | Shift handover | 18 July 2026')
pdf.setAuthor('Cedar support desk')
bounds = []

def paragraph(text, top, size=11, color=INK, width=CONTENT, left=MARGIN, bold=False):
    style = ParagraphStyle('body', fontName='DejaVu-Bold' if bold else 'DejaVu', fontSize=size,
                           leading=size * 1.42, textColor=color)
    item = Paragraph(text, style)
    _, height = item.wrap(width, HEIGHT)
    assert top + height < HEIGHT - 45, (text, top, height)
    item.drawOn(pdf, left, HEIGHT - top - height)
    bounds.append((pdf.getPageNumber(), left, top, width, height))
    return top + height

def heading(text, top):
    return paragraph(text, top, 13, TEAL, bold=True) + 9

def base(number, label):
    pdf.setFillColor(TEAL)
    pdf.rect(0, HEIGHT - 12, WIDTH, 12, fill=1, stroke=0)
    paragraph('CEDAR  /  INTERNAL SHIFT HANDOVER', 32, 9, TEAL, bold=True)
    paragraph(label, 58, 25, INK, bold=True)
    paragraph('Snapshot: 18 July 2026, 10:00 local time', 101, 10, MUTED)
    pdf.setStrokeColor(HexColor('#CBD6DB'))
    pdf.line(MARGIN, 43, WIDTH - MARGIN, 43)
    pdf.setFont('DejaVu', 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN, 29, 'Cedar support desk • Operational handover • Synthetic records')
    pdf.drawRightString(WIDTH - MARGIN, 29, f'{number} / 2')

base(1, 'Current shift at a glance')
pdf.setFillColor(AMBER)
pdf.roundRect(MARGIN, HEIGHT - 332, CONTENT, 190, 7, fill=1, stroke=0)
top = paragraph('URGENT EXCEPTION  /  WATER DELIVERY', 155, 11, INK, width=CONTENT-28, left=MARGIN+14, bold=True)
top = paragraph('Delivery is delayed. Current stock is unverified; there is no confirmed arrival time.', top+9, 11, width=CONTENT-28, left=MARGIN+14)
top = paragraph('<b>10:30 — Sam Ortiz:</b> check and record water stock.<br/><b>11:00 — Leila Noor:</b> obtain the supplier update. If the update is missed, escalate to <b>Mira Chen</b>.', top+10, 11, width=CONTENT-28, left=MARGIN+14)
paragraph('Do not say water has arrived or claim a stockout.', top+10, 10, width=CONTENT-28, left=MARGIN+14, bold=True)
top = heading('Confirmed operating position', 354)
top = paragraph('<b>Opening today:</b> staffed 09:00–18:00 on 18 July. The proposed 08:00–20:00 extension is <b>not approved</b>.', top)
top = paragraph('<b>Corrected attendance:</b> 82 visits on 17 July 2026, after removal of four duplicate sign-ins. This is not a count of unique residents; no reliable unique-resident count is available.', top+12)
top = heading('Access remains unresolved', top+24)
top = paragraph('The <b>east entrance is step-free</b>. The west-ramp request was received, but approval is still pending. Do not describe the west entrance as accessible.', top)
top = heading('Service boundary', top+24)
paragraph('The desk does not provide medical assessment. Refer urgent medical concerns to the existing local emergency procedure.', top)
pdf.showPage()

base(2, 'Owners and next actions')
top = paragraph('All four actions remain outstanding at cutoff. Deadlines below are on 18 July 2026, local time.', 142, 11)
style = ParagraphStyle('cell', fontName='DejaVu', fontSize=10, leading=14, textColor=INK)
header_style = ParagraphStyle('header', parent=style, fontName='DejaVu-Bold', textColor=white)
def cell(text, header=False):
    return Paragraph(text, header_style if header else style)
rows = [list(map(lambda text: cell(text, True), ['Due / owner', 'Next action / current status'])),
        [cell('<b>10:30</b><br/>Sam Ortiz'), cell('Check and record water stock. Quantity is currently unknown.')],
        [cell('<b>11:00</b><br/>Leila Noor'), cell('Obtain the supplier update. Escalate to Mira Chen if the update is missed. Arrival time is not confirmed.')],
        [cell('<b>12:00</b><br/>Mira Chen'), cell('Ask the facilities team for the west-ramp decision. Approval remains pending.')],
        [cell('<b>13:00</b><br/>Owen Reed'), cell('Reconcile remaining paper sign-ins. 82 is the currently verified visit count.')]]
table = Table(rows, colWidths=[137, CONTENT-137])
table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), TEAL), ('VALIGN',(0,0),(-1,-1),'TOP'),
                          ('LEFTPADDING',(0,0),(-1,-1),12), ('RIGHTPADDING',(0,0),(-1,-1),12),
                          ('TOPPADDING',(0,0),(-1,-1),10), ('BOTTOMPADDING',(0,0),(-1,-1),10),
                          ('ROWBACKGROUNDS',(0,1),(-1,-1),[PALE,white]),
                          ('LINEBELOW',(0,1),(-1,-1),0.4,HexColor('#CBD6DB'))]))
_, table_height = table.wrap(CONTENT, HEIGHT)
table_top = top+15
table.drawOn(pdf,MARGIN,HEIGHT-table_top-table_height)
bounds.append((2, MARGIN, table_top, CONTENT, table_height))
top = heading('Questions still open', table_top+table_height+23)
top = paragraph('West-ramp approval • Actual water stock<br/>Delivery arrival time • Reliable unique-resident count', top, 11)
top = heading('Authority limits', top+21)
top = paragraph('These records do not authorise extended hours, spending funds, automatic contact with people, or publication of a resident notice.', top, 10)
top = heading('Evidence and corrections', top+21)
paragraph('Sole factual source: <b>source_notes.md</b>, records A–D (synthetic). A: draft, 17 July 16:00. B: coordinator update, 18 July 08:30, replaces draft hours and ramp claim. C: verified correction, 18 July 09:15, replaces 86 with 82 visits. D: cutoff, 18 July 10:00, supplies current exceptions and outstanding actions. Latest dated corrections govern; no completed outcomes are recorded.', top, 9, MUTED)
pdf.save()
for page, left, top, width, height in bounds:
    assert left >= MARGIN and left+width <= WIDTH-MARGIN+0.01
    assert top >= 0 and top+height <= HEIGHT-45
print(f'Created {ROOT / "handover.pdf"}; {len(bounds)} content blocks within margins.')
