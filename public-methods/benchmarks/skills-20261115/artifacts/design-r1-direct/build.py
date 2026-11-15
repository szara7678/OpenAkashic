import json
from pathlib import Path
from html import escape
source = json.loads(Path('/task/input/centers.json').read_text())
cards = []
for location in source['locations']:
    access = 'Yes' if location['step_free'] is True else 'No' if location['step_free'] is False else 'Unknown — not confirmed'
    status = 'Open' if location['open'] else 'Closed'
    cards.append(f'''<article class="center {'closed' if not location['open'] else ''}" data-center-id="{escape(location['id'])}">
<div class="card-top"><span class="neighborhood">{escape(location['neighborhood'])} neighborhood</span><span class="status {'is-closed' if not location['open'] else ''}">{status}</span></div>
<h3>{escape(location['name'])}</h3>
<p class="services">{' · '.join(map(escape, location['services']))}</p>
<dl><div><dt>Hours</dt><dd>{escape(location['hours'])}</dd></div><div><dt>Step-free</dt><dd>{access}</dd></div></dl>
<p class="note">{escape(location['note'])}</p></article>''')
html = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>Find support | Cedar help desk</title>
<style>
:root{--ink:#203b3a;--paper:#f5f2e9;--leaf:#46745a;--amber:#b77a21;--line:#c6cfc7;--white:#fffefa}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}a{color:inherit}button,select,input{font:inherit}button,select{min-height:46px}button,select,input{accent-color:var(--leaf)}:focus-visible{outline:3px solid #203b3a;outline-offset:4px}.skip{position:absolute;left:16px;top:-100px;background:white;padding:12px;z-index:2}.skip:focus{top:12px}header{border-top:6px solid var(--leaf);border-bottom:1px solid var(--line)}.wrap{max-width:1120px;margin:auto;padding-inline:28px}.brand{display:flex;align-items:center;gap:14px;padding-block:21px}.mark{display:grid;place-items:center;width:40px;height:40px;background:var(--ink);color:var(--paper);font:28px Georgia,serif;border-radius:50%}.brand-name{font-weight:750;font-size:21px;letter-spacing:-.5px}.brand-subtitle{font-size:14px;color:#4e6259}main{padding-block:30px 48px}h1{font-size:clamp(30px,4vw,42px);line-height:1.15;letter-spacing:-1px;margin:0 0 10px}h2{font-size:22px;letter-spacing:-.35px;margin:0}h3{font-size:23px;line-height:1.25;letter-spacing:-.5px;margin:14px 0 7px}.intro{margin:0 0 22px;max-width:65ch;color:#4e6259}.notice{border-left:4px solid var(--amber);background:#efe6d1;padding:14px 18px;margin-bottom:26px}.notice p{margin:0}.notice strong{display:block;margin-bottom:3px}.filters{background:#e6ece4;border:1px solid var(--line);border-radius:8px;padding:20px;margin-bottom:28px}.filter-grid{display:grid;grid-template-columns:1fr 1fr 1fr auto;align-items:end;gap:20px}.field label{display:block;font-weight:650;margin-bottom:7px}select{display:block;width:100%;border:1px solid #7a8e80;border-radius:4px;padding:9px 32px 9px 12px;background:var(--white);color:var(--ink)}.check{min-height:46px;display:flex;align-items:center;gap:10px;font-weight:650;cursor:pointer}.check input{width:21px;height:21px;margin:0;flex-shrink:0}button{background:var(--white);border:1px solid #7a8e80;border-radius:4px;padding:9px 16px;color:var(--ink);font-weight:650;cursor:pointer}button:hover{background:#d9e3d7}.filter-help{font-size:14px;margin:15px 0 0;color:#4e6259}.results-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:16px}#result-count{margin:0;color:#4e6259;font-size:15px}#results{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.center{background:var(--white);border:1px solid var(--line);border-radius:6px;padding:22px;overflow-wrap:anywhere}.card-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.neighborhood{font-size:14px;color:#4e6259}.status{display:inline-flex;align-items:center;gap:6px;border-radius:30px;padding:3px 10px;background:#e5eee4;color:#294e32;font-size:13px;font-weight:750;white-space:nowrap}.status:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}.status.is-closed{background:#eee9df;color:#655b4c}.services{font-weight:650;margin:0 0 18px;color:var(--leaf)}dl{margin:0}dl>div{display:grid;grid-template-columns:86px 1fr;gap:10px;padding:5px 0}dt{color:#4e6259}dd{margin:0;font-weight:550}.note{border-top:1px solid #e0e4dc;margin:16px 0 0;padding-top:12px;font-size:14px;color:#4e6259}.closed{background:#f0eee6}#empty{padding:28px;border:1px dashed #7a8e80;border-radius:6px;background:var(--white)}#empty h3{margin-top:0}#empty p{margin-bottom:0}[hidden]{display:none!important}footer{border-top:1px solid var(--line);padding-block:22px;font-size:14px;color:#4e6259}footer p{margin:0}@media(max-width:760px){.filter-grid{grid-template-columns:1fr 1fr}.filter-grid button{justify-self:start}#results{grid-template-columns:1fr}}@media(max-width:440px){.wrap{padding-inline:18px}.brand{padding-block:16px}main{padding-top:24px}.filters{padding:16px}.filter-grid{grid-template-columns:1fr;gap:15px}.filter-grid button{width:100%}.results-heading{display:block}#result-count{margin-top:5px}.center{padding:18px}.notice{padding:12px 14px}}
</style></head><body>
<a class="skip" href="#main">Skip to directory</a>
<header><div class="wrap brand"><span class="mark" aria-hidden="true">C</span><div><div class="brand-name">Cedar</div><div class="brand-subtitle">Public help desk</div></div></div></header>
<main id="main" class="wrap"><h1>Find a place for support</h1><p class="intro">Browse local places for cooling and advice. Choose what you need to find a suitable open location.</p>
<aside class="notice" aria-label="Fixed snapshot notice"><p><strong>Fixed snapshot — not live availability</strong>Hours and open/closed status are from <time datetime="2026-07-18">18 July 2026</time>. They may have changed since this date.</p></aside>
<form class="filters" aria-label="Filter support locations"><div class="filter-grid">
<div class="field"><label for="neighborhood">Neighborhood</label><select id="neighborhood"><option value="">All</option><option>East</option><option>West</option><option>North</option></select></div>
<div class="field"><label for="service">Service</label><select id="service"><option value="">All</option><option>Cooling</option><option>Advice</option></select></div>
<label class="check" for="step-free"><input id="step-free" type="checkbox">Step-free only</label><button type="reset">Reset filters</button>
</div><p class="filter-help">Selecting any filter shows only locations marked open in the snapshot.</p></form>
<section aria-labelledby="locations-heading"><div class="results-heading"><h2 id="locations-heading">Support locations</h2><p id="result-count" role="status" aria-live="polite" aria-atomic="true">7 locations displayed</p></div>
<div id="results">__CARDS__</div><div id="empty" hidden><h3>No matching open locations</h3><p>Try another neighborhood or service, turn off Step-free only, or use Reset filters to see all locations.</p></div></section>
<noscript><p>Filtering needs JavaScript. All locations are listed above; check their snapshot status before choosing a location.</p></noscript></main>
<footer><div class="wrap"><p>Cedar public help desk · Offline directory · Snapshot: 18 July 2026</p></div></footer>
<script>
'use strict';
const directory = __DATA__;
const neighborhood = document.querySelector('#neighborhood');
const service = document.querySelector('#service');
const stepFree = document.querySelector('#step-free');
const cards = [...document.querySelectorAll('[data-center-id]')];
function updateResults() {
 const filtering = Boolean(neighborhood.value || service.value || stepFree.checked);
 let count = 0;
 directory.locations.forEach((location, index) => {
  const matches = (!filtering || location.open === true)
   && (!neighborhood.value || location.neighborhood === neighborhood.value)
   && (!service.value || location.services.includes(service.value))
   && (!stepFree.checked || location.step_free === true);
  cards[index].hidden = !matches;
  if (matches) count += 1;
 });
 document.querySelector('#result-count').textContent = `${count} ${filtering ? 'matching open' : ''} location${count === 1 ? '' : 's'} displayed`.replace(/  +/g, ' ');
 document.querySelector('#empty').hidden = count !== 0;
}
document.querySelector('form').addEventListener('change', updateResults);
document.querySelector('form').addEventListener('submit', event => event.preventDefault());
document.querySelector('form').addEventListener('reset', () => {
 neighborhood.value = ''; service.value = ''; stepFree.checked = false; updateResults();
});
</script></body></html>'''
Path('/work/index.html').write_text(html.replace('__CARDS__', '\n'.join(cards)).replace('__DATA__', json.dumps(source).replace('<', '\\u003c')))
