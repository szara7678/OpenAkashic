from pathlib import Path
from xml.etree import ElementTree as ET
import reportlab
import pypdf

root = Path(__file__).resolve().parent
reader = pypdf.PdfReader(root / 'handover.pdf')
assert len(reader.pages) == 2
for number, page in enumerate(reader.pages, 1):
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert abs(width - 595.2756) < .02 and abs(height - 841.8898) < .02
    content = page.extract_text()
    assert len(content) > 500
    print(f'Page {number}: {width:.4f} x {height:.4f} pt; {len(content)} extracted characters')
namespace = {'x': 'http://www.w3.org/1999/xhtml'}
xml = ET.parse(root / 'handover-bbox.html').getroot()
for number, page in enumerate(xml.findall('.//x:page', namespace), 1):
    words = page.findall('x:word', namespace)
    width, height = float(page.attrib['width']), float(page.attrib['height'])
    for word in words:
        assert 0 <= float(word.attrib['xMin']) < float(word.attrib['xMax']) <= width
        assert 0 <= float(word.attrib['yMin']) < float(word.attrib['yMax']) <= height
    print(f'Page {number}: all {len(words)} word boxes within page boundaries')
text = ' '.join(' '.join(page.extract_text() for page in reader.pages).split())
for required in ['82 visits', '09:00–18:00', '10:00 local time', 'Sam Ortiz', 'Leila Noor', 'Mira Chen', 'Owen Reed', '10:30', '11:00', '12:00', '13:00', 'step-free', 'approval remains pending']:
    assert required in text, required
print('Required text checks passed (whitespace normalized)')
print('ReportLab:', reportlab.Version, '| pypdf:', pypdf.__version__)
