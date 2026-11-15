from pathlib import Path
import json
import subprocess
import xml.etree.ElementTree as ET
from pypdf import PdfReader

root = Path(__file__).resolve().parent
reader = PdfReader(root / 'handover.pdf')
assert len(reader.pages) == 2
subprocess.run(['pdftotext', '-bbox', str(root / 'handover.pdf'), str(root / 'bounds.html')], check=True)
namespace = {'x': 'http://www.w3.org/1999/xhtml'}
pages = ET.parse(root / 'bounds.html').findall('.//x:page', namespace)
assert len(pages) == 2
results = []
for number, page in enumerate(pages, 1):
    width, height = float(page.attrib['width']), float(page.attrib['height'])
    assert abs(width - 595.276) < 0.02
    assert abs(height - 841.89) < 0.02
    words = page.findall('x:word', namespace)
    assert words
    for word in words:
        bounds = word.attrib
        assert 0 <= float(bounds['xMin']) <= float(bounds['xMax']) <= width
        assert 0 <= float(bounds['yMin']) <= float(bounds['yMax']) <= height
    results.append({'page': number, 'width_pt': width, 'height_pt': height,
                    'selectable_words': len(words), 'all_word_bounds_inside_page': True})
text = '\n'.join(page.extract_text() for page in reader.pages)
for expected in ['82 visits', '09:00–18:00', 'Mira Chen', 'Owen Reed', 'Leila Noor',
                 'Sam Ortiz', '10:30', '11:00', '12:00', '13:00', '10:00',
                 'pending', 'step-free', 'emergency procedure', 'source_notes.md']:
    assert expected in text, expected
assert 'urgent exception' in text.lower()
(root / 'qa_results.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
print('PASS: 2 A4 pages; selectable text; all word bounds inside pages; required content tokens found.')
