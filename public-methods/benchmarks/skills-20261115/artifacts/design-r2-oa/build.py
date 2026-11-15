import json
from pathlib import Path
from html import escape

data = json.loads(Path('/task/input/centers.json').read_text())
cards = []
for center in data['locations']:
    status = 'Open' if center['open'] else 'Closed'
    access = 'Yes' if center['step_free'] is True else 'No' if center['step_free'] is False else 'Unknown — not confirmed'
    services = ''.join('<span class="service">'+escape(service)+'</span>' for service in center['services'])
    cards.append(f'''<article class="card {'closed' if not center['open'] else ''}" data-center-id="{escape(center['id'])}">
    <div class="card-top"><span class="neighborhood">{escape(center['neighborhood'])} neighborhood</span><span class="status {'open' if center['open'] else 'shut'}">{status} <span class="snapshot-label">at snapshot</span></span></div>
    <h3>{escape(center['name'])}</h3><div class="services" aria-label="Services">{services}</div>
    <dl><div><dt>Hours</dt><dd>{escape(center['hours'])}</dd></div><div><dt>Step-free</dt><dd>{access}</dd></div></dl>
    <p class="note">{escape(center['note'])}</p></article>''')
html = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Find local support | Cedar help desk</title>
<style>
:root{color-scheme:light;--ink:#203b3a;--paper:#f5f2e9;--leaf:#46745a;--amber:#b77a21;--line:#d3dcd4;--muted:#50625b}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 'Segoe UI',Arial,sans-serif}button,select,input{font:inherit}a{color:inherit}.skip{position:absolute;top:-80px;left:16px;background:white;padding:12px;z-index:10}.skip:focus{top:12px}:focus-visible{outline:3px solid #925b0c;outline-offset:4px}header{background:var(--ink);color:white}.masthead{max-width:1120px;margin:auto;padding:18px 28px;display:flex;align-items:center;gap:14px}.mark{width:32px;height:32px;border:2px solid #cad9c7;border-radius:50% 50% 3px 50%;display:grid;place-items:center;font:bold 23px Georgia,serif}.brand{font-size:23px;font-weight:650}.department{border-left:1px solid #81978c;padding-left:14px;color:#e2e9df;font-size:15px}main{max-width:1120px;margin:auto;padding:28px}h1{font-size:clamp(30px,4vw,40px);line-height:1.15;letter-spacing:-1px;margin:0 0 10px}h2{font-size:22px;margin:0}h3{font-size:22px;line-height:1.25;margin:16px 0 12px}.intro{margin:0 0 22px;max-width:65ch;color:var(--muted)}.notice{border-left:4px solid var(--amber);background:#fff9e9;padding:14px 18px;margin-bottom:24px}.notice p{margin:2px 0}.filters{background:#e6ece3;border:1px solid #c7d4c5;border-radius:8px;padding:20px;margin-bottom:24px}.filter-grid{display:grid;grid-template-columns:1fr 1fr auto auto;align-items:end;gap:18px;margin-top:14px}.field label{display:block;font-weight:650;margin-bottom:6px}select{display:block;width:100%;min-height:46px;border:1px solid #7e9185;border-radius:4px;padding:8px 36px 8px 12px;background:white;color:var(--ink)}.check{display:flex;align-items:center;gap:8px;min-height:46px;font-weight:600;cursor:pointer;white-space:nowrap}input[type=checkbox]{width:21px;height:21px;accent-color:var(--leaf);margin:0}button{min-height:46px;padding:9px 16px;border:1px solid var(--ink);border-radius:4px;background:transparent;color:var(--ink);font-weight:600;cursor:pointer}button:hover{background:#d4dfd0}.filter-hint{color:var(--muted);font-size:14px;margin:12px 0 0}.results-heading{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:14px}#result-count{margin:0;color:var(--muted)}#results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{border:1px solid var(--line);border-top:4px solid var(--leaf);background:#fffef9;border-radius:6px;padding:20px;min-width:0}.card.closed{border-top-color:#89908b;background:#eeeee7}.card-top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px}.neighborhood{color:var(--muted)}.status{font-weight:700;border-radius:4px;padding:3px 7px}.open{background:#e3efdf;color:#2d5338}.shut{background:#dfdfd8;color:#424a45}.snapshot-label{font-weight:400}.services{display:flex;flex-wrap:wrap;gap:7px}.service{font-size:14px;border:1px solid #c6d3c5;border-radius:4px;padding:2px 9px}dl{margin:18px 0 12px}dl>div{display:grid;grid-template-columns:90px 1fr;gap:10px;margin:6px 0}dt{color:var(--muted)}dd{margin:0;font-weight:600;overflow-wrap:anywhere}.note{border-top:1px solid var(--line);padding-top:12px;margin:0;font-size:14px;color:var(--muted)}[hidden]{display:none!important}.empty{grid-column:1/-1;padding:28px;border:1px dashed #849b86;border-radius:6px;background:#fffef9}.empty h3{margin:0 0 8px}.empty p{margin:0}footer{max-width:1120px;margin:0 auto;padding:0 28px 28px;color:var(--muted);font-size:14px}noscript p{padding:16px;background:#fff9e9}
@media(max-width:760px){.filter-grid{grid-template-columns:1fr 1fr}.check{white-space:normal}#results{grid-template-columns:1fr}}@media(max-width:440px){main{padding:22px 18px}.masthead{padding:15px 18px;gap:10px}.department{padding-left:10px;font-size:14px}.filter-grid{grid-template-columns:1fr;gap:14px}.filters{padding:16px}.card{padding:18px}.check{min-height:40px}.notice{padding:12px 14px}footer{padding:0 18px 24px}}
</style></head><body>
<a class="skip" href="#main">Skip to directory</a>
<header><div class="masthead"><span class="mark" aria-hidden="true">C</span><span class="brand">Cedar</span><span class="department">Public help desk</span></div></header>
<main id="main"><h1>Find local support</h1><p class="intro">Find a place for cooling or advice. Choose what you need to see suitable support locations.</p>
<aside class="notice" aria-label="Fixed snapshot notice"><strong>Fixed snapshot — not live availability</strong><p>Hours and open / closed status are from <time datetime="2026-07-18">18 July 2026</time>. They may have changed since then.</p></aside>
<section class="filters" aria-labelledby="filter-heading"><h2 id="filter-heading">Find a suitable location</h2><div class="filter-grid">
<div class="field"><label for="neighborhood">Neighborhood</label><select id="neighborhood"><option value="">All</option><option>East</option><option>West</option><option>North</option></select></div>
<div class="field"><label for="service">Service</label><select id="service"><option value="">All</option><option>Cooling</option><option>Advice</option></select></div>
<label class="check" for="step-free"><input id="step-free" type="checkbox">Step-free only</label><button id="reset" type="button">Reset filters</button></div>
<p class="filter-hint" id="filter-hint">All locations are shown below. With any filter applied, only locations marked open in the snapshot are shown.</p></section>
<noscript><p>JavaScript is disabled. All locations are listed, but filters require JavaScript. Check each location’s snapshot status before choosing.</p></noscript>
<section aria-labelledby="locations-heading"><div class="results-heading"><h2 id="locations-heading">Support locations</h2><p id="result-count" role="status" aria-live="polite" aria-atomic="true">7 locations shown</p></div>
<div id="results">__CARDS__<div class="empty" id="empty" hidden><h3>No matching open locations</h3><p>Try another neighborhood or service, turn off Step-free only, or use Reset filters to see all locations.</p></div></div></section></main>
<footer>Cedar public help desk · Snapshot directory · No live updates</footer>
<script id="center-data" type="application/json">__DATA__</script>
<script>
'use strict';
const data = JSON.parse(document.getElementById('center-data').textContent);
const neighborhood = document.getElementById('neighborhood');
const service = document.getElementById('service');
const stepFree = document.getElementById('step-free');
const cards = [...document.querySelectorAll('#results [data-center-id]')];
function updateResults() {
  const active = Boolean(neighborhood.value || service.value || stepFree.checked);
  let count = 0;
  for (const card of cards) {
    const center = data.locations.find(location => location.id === card.dataset.centerId);
    const matches = (!active || center.open === true)
      && (!neighborhood.value || center.neighborhood === neighborhood.value)
      && (!service.value || center.services.includes(service.value))
      && (!stepFree.checked || center.step_free === true);
    card.hidden = !matches;
    if (matches) count++;
  }
  document.getElementById('result-count').textContent = `${count} ${count === 1 ? 'location' : 'locations'} shown`;
  document.getElementById('empty').hidden = count !== 0;
}
for (const control of [neighborhood, service, stepFree]) control.addEventListener('change', updateResults);
document.getElementById('reset').addEventListener('click', () => {
  neighborhood.value = '';
  service.value = '';
  stepFree.checked = false;
  updateResults();
});
</script></body></html>'''
Path('/work/index.html').write_text(html.replace('__CARDS__','\n'.join(cards)).replace('__DATA__',json.dumps(data).replace('<','\\u003c')))
