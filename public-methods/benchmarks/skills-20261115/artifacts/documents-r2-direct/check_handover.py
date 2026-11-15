from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from pypdf import PdfReader

root = Path(__file__).resolve().parent
reader = PdfReader(root / 'handover.pdf')
assert len(reader.pages) == 2
for page in reader.pages:
    assert abs(float(page.mediabox.width) - 595.2756) < 0.01
    assert abs(float(page.mediabox.height) - 841.8898) < 0.01
texts = [' '.join(page.extract_text().split()) for page in reader.pages]
for phrase in ['10:00, local time', '82 visits on 17 July 2026', '09:00–18:00',
               'ramp request received, approval pending', 'URGENT EXCEPTION',
               'does not provide medical assessment']:
    assert phrase in texts[0], phrase
for phrase in ['10:30 | Sam Ortiz', '11:00 | Leila Noor', '12:00 | Mira Chen',
               '13:00 | Owen Reed', 'escalate to Mira Chen',
               'Unique-resident count:', 'Authority limits', 'Evidence note:']:
    assert phrase in texts[1], phrase
assert all('\ufffd' not in text and '\u25a0' not in text for text in texts)
subprocess.run(['pdftotext', '-bbox', str(root / 'handover.pdf'), str(root / 'handover-bbox.html')], check=True)
tree = ET.parse(root / 'handover-bbox.html')
ns = {'x': 'http://www.w3.org/1999/xhtml'}
lines = []
for number, page in enumerate(tree.findall('.//x:page', ns), 1):
    width, height = float(page.attrib['width']), float(page.attrib['height'])
    words = page.findall('x:word', ns)
    assert words
    for word in words:
        bounds = [float(word.attrib[key]) for key in ['xMin', 'yMin', 'xMax', 'yMax']]
        assert 0 <= bounds[0] <= bounds[2] <= width, (number, word.text, bounds)
        assert 0 <= bounds[1] <= bounds[3] <= height, (number, word.text, bounds)
    extents = [min(float(word.attrib['xMin']) for word in words),
               min(float(word.attrib['yMin']) for word in words),
               max(float(word.attrib['xMax']) for word in words),
               max(float(word.attrib['yMax']) for word in words)]
    lines.append(f'Page {number}: {len(words)} selectable words; text bounds (left, top, right, bottom) = ' + ', '.join(f'{value:.2f}' for value in extents) + ' pt.')
print('PASS: exactly two A4 pages (595.28 × 841.89 pt).')
print('PASS: key snapshot, correction, opening, exception, owners/deadlines and escalation text checks.')
print('PASS: no replacement or black-square characters in extracted text.')
print('PASS: all Poppler word bounding boxes fall within page boundaries.')
print('\n'.join(lines))
