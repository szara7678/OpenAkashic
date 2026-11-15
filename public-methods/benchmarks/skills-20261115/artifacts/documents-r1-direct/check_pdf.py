from pathlib import Path
from pypdf import PdfReader
import xml.etree.ElementTree as ET
import subprocess

root = Path(__file__).resolve().parent
reader = PdfReader(root / 'handover.pdf')
assert len(reader.pages) == 2
text = '\n'.join(page.extract_text() for page in reader.pages)
for page in reader.pages:
    assert abs(float(page.mediabox.width)-595.2756) < 0.1
    assert abs(float(page.mediabox.height)-841.8898) < 0.1
    assert len(page.extract_text()) > 500
for expected in ['82 visits', '09:00–18:00', '10:00 local time', 'Sam Ortiz', '10:30', 'Leila Noor', '11:00', 'Mira Chen', '12:00', 'Owen Reed', '13:00', 'pending', 'source_notes.md']:
    assert expected in text, expected
(root / 'extracted.txt').write_text(text)
subprocess.run(['pdftotext', '-bbox', str(root/'handover.pdf'), str(root/'bounds.html')], check=True)
document = ET.parse(root/'bounds.html')
namespace = {'x':'http://www.w3.org/1999/xhtml'}
count = 0
for page in document.findall('.//x:page', namespace):
    width, height = float(page.attrib['width']), float(page.attrib['height'])
    for word in page.findall('.//x:word', namespace):
        assert 0 <= float(word.attrib['xMin']) <= float(word.attrib['xMax']) <= width
        assert 0 <= float(word.attrib['yMin']) <= float(word.attrib['yMax']) <= height
        count += 1
print(f'PASS: 2 A4 pages; selectable text on both; required content present; {count} word boxes inside page boundaries.')
