/* Behavioral event contracts for the real atlas script, without a browser.
 * The SVG/DOM and animation clock below are intentionally small fakes. These
 * tests establish JS routing and bounded rendering work, not physical touch,
 * CSS layout, hit testing, accessibility-tree output, or device performance.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function atlas({ reader = false, deferred = false } = {}) {
  const elements = new Map(), frames = new Map(), timers = [], choices = [];
  const requests = new Map();
  const counters = { rect: 0, ctm: 0, text: 0, viewport: 0, position: 0 };
  let frameId = 0;
  class Element {
    constructor(tag = 'div', id = '') {
      this.tagName = tag.toUpperCase(); this.id = id; this.children = [];
      this.dataset = {}; this.attributes = {}; this.listeners = new Map();
      this.hidden = true; this.value = ''; this.textContent = ''; this.open = false; this.scrollTop = 0;
      const classes = new Set();
      this.classList = { add: (...xs) => xs.forEach(x => classes.add(x)),
        remove: (...xs) => xs.forEach(x => classes.delete(x)), contains: x => classes.has(x),
        toggle: (x, on = !classes.has(x)) => { if (on) classes.add(x); else classes.delete(x); return on; } };
      this.style = { setProperty() {} }; this.captured = new Set();
    }
    set className(value) { for (const x of value.split(/\s+/)) this.classList.add(x); }
    setAttribute(k, v) {
      this.attributes[k] = String(v);
      if (k === 'class') this.className = v;
      if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, x) => x.toUpperCase())] = v;
      if (k === 'transform' && this.id === 'atlas-viewport') counters.viewport++;
      if (k === 'transform' && this.classList.contains('network-node')) counters.position++;
    }
    getAttribute(k) { return this.attributes[k] ?? null; }
    append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    insertBefore(node) { this.append(node); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); }
    matches(selector) {
      const attribute = selector.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);
      if (attribute) { const value = this.dataset[attribute[1].replace(/-([a-z])/g, (_, x) => x.toUpperCase())]; return value !== undefined && (attribute[2] === undefined || value === attribute[2]); }
      return selector.startsWith('.') ? this.classList.contains(selector.slice(1)) : this.tagName.toLowerCase() === selector;
    }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
    querySelectorAll(selector) { return this.children.flatMap(n => [ ...(n.matches(selector) ? [n] : []), ...n.querySelectorAll(selector) ]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    contains(target) { return target === this || this.children.some(n => n.contains(target)); }
    addEventListener(type, fn) { this.listeners.set(type, [...(this.listeners.get(type) || []), fn]); }
    dispatch(type, props = {}) {
      const pending = [], e = { type, target: this, button: 0, pointerType: 'touch', pointerId: 1, clientX: 100, clientY: 200,
        preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, stopImmediatePropagation() { this.stopped = true; }, ...props };
      for (const fn of this.listeners.get(type) || []) { pending.push(fn(e)); if (e.stopped) break; }
      e.done = Promise.all(pending); return e;
    }
    setPointerCapture(id) { this.captured.add(id); }
    hasPointerCapture(id) { return this.captured.has(id); }
    releasePointerCapture(id) { this.captured.delete(id); }
    getScreenCTM() { counters.ctm++; return { inverse: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }) }; }
    getBoundingClientRect() { counters.rect++; return this.id === 'atlas-map' ? { x: 0, y: 0, left: 0, top: 0, right: 390, bottom: 844, width: 390, height: 844 } : { x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
    getComputedTextLength() { counters.text++; return this.textContent.length * 6; }
    focus() { document.activeElement = this; }
    blur() { document.activeElement = document.body; }
  }
  const $ = id => { if (!elements.has(id)) elements.set(id, new Element('div', id)); return elements.get(id); };
  const document = new Element('document');
  document.getElementById = $; document.createElement = tag => new Element(tag);
  document.createElementNS = (_, tag) => new Element(tag);
  document.documentElement = new Element('html'); document.body = new Element('body');
  document.activeElement = document.body; document.hidden = false;
  document.querySelectorAll = () => [];
  $('atlas-depth').value = '0'; $('atlas-map').hidden = false;
  $('atlas-options').append(new Element('summary'));
  for (const tab of ['overview', 'steps', 'connections']) { const button = new Element('button'); button.dataset.recordTab = tab; $('atlas-record-tabs').append(button); }
  const href = 'https://atlas.example/';
  const location = { href, search: '' }, entries = [{ url: href, state: null }];
  let entry = 0;
  const updateLocation = url => { const u = new URL(url); location.href = u.href; location.search = u.search; };
  const history = {
    get state() { return entries[entry].state; },
    pushState(state, _, url) { entries.splice(entry + 1); entries.push({ state, url: String(url) }); entry++; updateLocation(url); },
    replaceState(state, _, url = location.href) { entries[entry] = { state, url: String(url) }; updateLocation(url); },
    back() { return this.go(-1); }, forward() { return this.go(1); },
    go(delta) { const next = entry + delta; if (next < 0 || next >= entries.length) return Promise.resolve(); entry = next; updateLocation(entries[entry].url); return context.window.dispatch('popstate', { state: this.state }).done; }
  };
  const detail = id => ({ situation: `Situation for ${id}`, goal: `Goal for ${id}`, steps: ['First action', 'Second action'], constraints: [], success_criteria: [], limitations: [] });
  const context = { document, URL, URLSearchParams, console,
    DOMPoint: class { constructor(x, y) { this.x = x; this.y = y; } matrixTransform(m) { return { x: this.x * m.a + this.y * m.c + m.e, y: this.x * m.b + this.y * m.d + m.f }; } },
    window: new Element('window'), location, history, readerMode: reader,
    localStorage: { getItem: () => null, setItem() {} },
    matchMedia: query => ({ matches: query.includes('reduced-motion'), addEventListener() {} }),
    performance: { now: () => 0 }, ResizeObserver: class { observe() {} },
    requestAnimationFrame: fn => { frames.set(++frameId, fn); return frameId; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
    // Network bootstrap remains pending; reader requests receive public fixtures.
    fetch: url => {
      if (!reader || url.includes('/network?')) return new Promise(() => {});
      const id = decodeURIComponent(url.split('/').at(-1));
      if (deferred) return new Promise(resolve => requests.set(id, () => resolve({ ok: true, json: async () => detail(id) })));
      return Promise.resolve({ ok: true, json: async () => detail(id) });
    } };
  const filename = process.env.ATLAS_SCRIPT || path.join(__dirname, '../research/methods-explore.js');
  const source = fs.readFileSync(filename, 'utf8');
  const hook = `
    globalThis.contract = {
      seed() {
        width = 390; height = 844; zoom = 1; shift = { x: 0, y: 0 }; motion = false;
        graph = { nodes: [
          { id: 'method-public:v1', kind: 'method', method_id: 'method-public', version: 1, label: 'Public method', domain: 'Public' },
          { id: 'category-public', kind: 'category', label: 'Public' }
        ], edges: [], domains: [], scope: { total_methods: 1, truncated: false } };
        if (globalThis.readerMode) {
          graph.nodes = [graph.nodes[0], { id: 'method-linked:v1', kind: 'method', method_id: 'method-linked', version: 1, label: 'Linked public method' }, { id: 'source-public', kind: 'source', label: 'Public source', url: 'https://example.com/source' }];
          graph.edges = [{ source: 'method-public:v1', target: 'source-public', relation: 'documented_by' }, { source: 'method-linked:v1', target: 'source-public', relation: 'documented_by' }];
        }
        visible = [...graph.nodes]; edges = [];
        for (const [i, n] of visible.entries()) { index.set(n.id, n); adj.set(n.id, []); points.set(n.id, { x: 100 + i * 150, y: 200, ax: 100 + i * 150, ay: 200, vx: 0, vy: 0 }); }
        for (const e of graph.edges) { adj.get(e.source).push({ id: e.target, relation: e.relation }); adj.get(e.target).push({ id: e.source, relation: e.relation }); }
        if (!globalThis.readerMode) choose = (...args) => globalThis.recordChoice(...args);
        draw();
      },
      prepareDismiss(viewWidth) {
        width = viewWidth;
        const unrelated = { id: 'method-unrelated:v1', kind: 'method', method_id: 'method-unrelated', version: 1, label: 'Unrelated public method' };
        graph.nodes.push(unrelated); index.set(unrelated.id, unrelated); adj.set(unrelated.id, []);
        points.set(unrelated.id, { x: 300, y: 500, ax: 300, ay: 500, vx: 0, vy: 0 });
        visible = [...graph.nodes]; selected = graph.nodes[0]; trail = [selected.id];
        $('atlas-depth').value = '2'; openInspector(); draw(); highlight(selected.id);
      },
      state: () => ({ zoom, shift: { ...shift }, pointers: pointers.size, drag: drag && { ...drag }, point: { ...points.get('method-public:v1') }, selectedId: selected?.id || null, recordTab }),
      open: (...args) => choose(...args),
      restore: () => restoreLocation(),
      labels: () => updateLabels(), reset: () => resetMap()
    };
  `;
  assert.ok(source.trimEnd().endsWith('})();'), 'atlas IIFE hook location');
  context.recordChoice = (...args) => choices.push(args);
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, hook + '\n})();'), context, { filename });
  context.contract.seed();
  function frame() { const callbacks = [...frames.values()]; frames.clear(); for (const fn of callbacks) fn(16); }
  function zero() { for (const key of Object.keys(counters)) counters[key] = 0; }
  async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve(); frame(); }
  function click(target, props = {}) {
    const event = document.dispatch('click', { target, detail: 1, ...props });
    if (!event.stopped) for (let n = target; n; n = n.parentElement) { if (event.stopped) break; n.onclick?.(event); for (const fn of n.listeners.get('click') || []) fn(event); }
    return event;
  }
  frame(); zero();
  return { $, map: $('atlas-map'), node: $('atlas-nodes').children[0],
    state: context.contract.state, labels: context.contract.labels, reset: context.contract.reset,
    prepareDismiss: context.contract.prepareDismiss, activeElement: () => document.activeElement,
    open: context.contract.open, restore: context.contract.restore, history, click, document, settle,
    resolveDetail: id => { assert.ok(requests.has(id), `pending detail ${id}`); requests.get(id)(); requests.delete(id); },
    counters, choices, frame, timers, zero };
}

test('captured node tap still selects when pointerup is retargeted to map', () => {
  const a = atlas();
  a.map.dispatch('pointerdown', { target: a.node });
  assert.equal(a.map.hasPointerCapture(1), true, 'node contact must be captured too');
  a.map.dispatch('pointermove', { clientX: 103, clientY: 201 });
  a.map.dispatch('pointerup', { clientX: 103, clientY: 201 });
  assert.equal(a.choices.length, 1);
  assert.equal(a.choices[0][0], 'method-public:v1');
});

test('retargeted node drag moves node instead of panning and never selects', () => {
  const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
  a.map.dispatch('pointermove', { clientX: 140, clientY: 230 });
  a.frame(); a.map.dispatch('pointerup', { clientX: 140, clientY: 230 });
  assert.equal(a.state().point.x, 140); assert.equal(a.state().point.y, 230);
  assert.equal(a.state().shift.x, 0); assert.equal(a.state().point.pinned, true);
  assert.equal(a.choices.length, 0);
});

test('pointerup consumes final position even before scheduled frame', () => {
  const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
  a.map.dispatch('pointermove', { clientX: 130, clientY: 210 });
  a.map.dispatch('pointerup', { clientX: 150, clientY: 220 });
  assert.equal(a.state().point.x, 150); assert.equal(a.state().point.y, 220);
  assert.equal(a.choices.length, 0);
});

test('cancel and lost capture clean gestures without selecting', () => {
  for (const type of ['pointercancel', 'lostpointercapture']) {
    const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
    a.map.dispatch(type); a.frame();
    assert.equal(a.state().pointers, 0, type); assert.equal(a.state().drag, null, type);
    a.map.dispatch('pointermove', { clientX: 170 }); a.frame();
    assert.equal(a.state().point.x, 100); assert.equal(a.choices.length, 0);
  }
});

test('pinch transitions to remaining finger pan without jump or tap', () => {
  const a = atlas(); a.map.dispatch('pointerdown');
  a.map.dispatch('pointerdown', { pointerId: 2, clientX: 200 });
  a.map.dispatch('pointermove', { pointerId: 2, clientX: 220 }); a.frame();
  a.map.dispatch('pointerup', { pointerId: 2, clientX: 220 });
  const before = a.state();
  a.map.dispatch('pointermove', { clientX: 120 }); a.frame();
  assert.equal(a.state().shift.x - before.shift.x, 20);
  assert.equal(a.state().zoom, before.zoom);
  a.map.dispatch('pointerup', { clientX: 120 });
  assert.equal(a.choices.length, 0); assert.equal(a.state().pointers, 0);
});

test('pointer bursts render at most once per frame and avoid layout reads', () => {
  const a = atlas(); a.map.dispatch('pointerdown'); a.zero();
  for (let x = 106; x <= 145; x++) a.map.dispatch('pointermove', { clientX: x });
  assert.equal(a.counters.viewport, 0, 'no eager transforms during input burst');
  assert.equal(a.counters.rect, 0, 'no layout measurements during input burst');
  assert.equal(a.counters.ctm, 0, 'no SVG matrix measurements during input burst');
  a.frame(); assert.ok(a.counters.viewport <= 1);
  assert.equal(a.state().shift.x, 45);
});

test('CSS coordinates convert through the captured SVG screen matrix', () => {
  const a = atlas();
  a.map.getScreenCTM = () => ({ inverse: () => ({ a: .5, b: 0, c: 0, d: .5, e: -10, f: -20 }) });
  a.map.dispatch('pointerdown', { target: a.node, clientX: 220, clientY: 440 });
  a.map.dispatch('pointermove', { clientX: 260, clientY: 460 });
  a.map.dispatch('pointerup', { clientX: 260, clientY: 460 });
  assert.equal(a.state().point.x, 120); assert.equal(a.state().point.y, 210);
});

test('unchanged labels reuse text measurements', () => {
  const a = atlas(); a.labels(); a.frame(); a.zero();
  for (let i = 0; i < 12; i++) { a.labels(); a.frame(); }
  assert.equal(a.counters.text, 0, 'unchanged text must use cached dimensions');
});

test('five CSS pixels start a drag while smaller jitter remains a tap', () => {
  for (const dx of [4, 5]) {
    const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
    a.map.dispatch('pointermove', { clientX: 100 + dx });
    a.map.dispatch('pointerup', { clientX: 100 + dx });
    assert.equal(a.choices.length, dx < 5 ? 1 : 0, `${dx}px movement`);
    assert.equal(a.state().point.x, dx < 5 ? 100 : 105);
  }
});

test('multi-pointer contact invalidates a node tap even without pinch movement', () => {
  const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
  a.map.dispatch('pointerdown', { pointerId: 2, clientX: 200 });
  a.map.dispatch('pointerup', { pointerId: 2, clientX: 200 });
  a.map.dispatch('pointerup');
  assert.equal(a.choices.length, 0);
  assert.equal(a.state().point.x, 100);
});

test('pointer compatibility click cannot select a captured tap twice', () => {
  const a = atlas(); a.map.dispatch('pointerdown', { target: a.node });
  a.map.dispatch('pointerup');
  a.node.onclick({ detail: 1 });
  assert.equal(a.choices.length, 1);
});

test('keyboard activation remains available after pointer routing changes', () => {
  const a = atlas();
  a.node.onkeydown({ key: 'Enter', preventDefault() {}, stopPropagation() {} });
  assert.equal(a.choices.length, 1); assert.equal(a.choices[0][2], true);
  a.node.onclick({ detail: 0 }); assert.equal(a.choices.length, 2);
  a.$('atlas-options').open = true; a.$('atlas-help').focus();
  a.$('atlas-help').onclick({ detail: 0 });
  assert.equal(a.$('atlas-options').open, false);
  assert.equal(a.$('atlas-help-panel').hidden, false);
  assert.equal(a.$('atlas-help').getAttribute('aria-expanded'), 'true');
  assert.equal(a.activeElement(), a.$('atlas-options').querySelector('summary'));
  const pointer = atlas(); pointer.$('atlas-options').open = true; pointer.$('atlas-help').focus();
  pointer.$('atlas-help').onclick({ detail: 1 });
  assert.equal(pointer.activeElement(), pointer.$('atlas-help'), 'pointer help activation does not steal focus');
});

test('reset closes help, shelf, controls and options with matching ARIA state', () => {
  const a = atlas();
  for (const [panel, trigger] of [['atlas-help-panel', 'atlas-help'], ['atlas-shelf', 'atlas-shelf-toggle'], ['atlas-controls', 'atlas-controls-toggle']]) {
    a.$(panel).hidden = false; a.$(trigger).setAttribute('aria-expanded', 'true');
  }
  a.$('atlas-options').open = true; a.reset();
  for (const [panel, trigger] of [['atlas-help-panel', 'atlas-help'], ['atlas-shelf', 'atlas-shelf-toggle'], ['atlas-controls', 'atlas-controls-toggle']]) {
    assert.equal(a.$(panel).hidden, true, panel); assert.equal(a.$(trigger).getAttribute('aria-expanded'), 'false', trigger);
  }
  assert.equal(a.$('atlas-options').open, false);
});

test('mobile return to all records clears dimming without opening the discovery panel', () => {
  for (const action of ['dismiss', 'reset', 'filter']) {
    const a = atlas(); a.prepareDismiss(390);
    assert.ok(a.$('atlas-nodes').children.some(n => n.classList.contains('dim')), 'fixture has an unrelated dimmed record');
    if (action !== 'dismiss') a.$('atlas-discovery-toggle').onclick();
    if (action === 'dismiss') a.$('atlas-inspector-close').onclick();
    else if (action === 'reset') a.$('atlas-reset').onclick();
    else a.$('atlas-domain').onchange();
    a.frame();
    assert.equal(a.$('atlas-inspector').hidden, true, action);
    assert.equal(a.state().selectedId, null, action);
    assert.equal(a.$('atlas-depth').value, '0', action);
    assert.equal(a.$('atlas-nodes').children.length, 2, 'both public methods remain in the full map');
    assert.ok(a.$('atlas-nodes').children.every(n => !n.classList.contains('dim')), action);
    assert.equal(a.$('atlas-discovery-content').hidden, true, action);
    assert.equal(a.$('atlas-discovery-toggle').getAttribute('aria-expanded'), 'false', action);
  }
  const desktop = atlas(); desktop.prepareDismiss(1100);
  desktop.$('atlas-inspector-close').onclick();
  assert.equal(desktop.$('atlas-discovery-content').hidden, false, 'desktop keeps expanded discovery');
  assert.equal(desktop.$('atlas-discovery-toggle').getAttribute('aria-expanded'), 'true');
});

const textOf = node => node.textContent + node.children.map(textOf).join(' ');
const tabButton = (a, tab) => a.$('atlas-record-tabs').querySelector(`[data-record-tab="${tab}"]`);

test('reader linked-card navigation and Back/Forward preserve each reading position', async () => {
  const a = atlas({ reader: true });
  await a.restore();
  assert.equal(a.activeElement(), a.document.body, 'initial unselected load does not move focus');
  await a.open('method-public:v1'); await a.settle();
  a.click(tabButton(a, 'connections'));
  a.$('atlas-inspector-expand').onclick(); a.$('atlas-inspector').scrollTop = 960;
  a.$('atlas-inspector').dispatch('scroll');
  const card = a.$('atlas-record').querySelectorAll('.path-card').find(n => textOf(n).includes('Linked public method'));
  assert.ok(card, 'shared public source provides a linked method');
  a.click(card.querySelector('button') || card.children[0]); await a.settle();
  assert.equal(a.state().selectedId, 'method-linked:v1');
  assert.equal(a.state().recordTab, 'overview'); assert.equal(a.$('atlas-inspector').scrollTop, 0);
  a.click(tabButton(a, 'steps')); a.$('atlas-inspector').scrollTop = 220;
  a.$('atlas-inspector').dispatch('scroll');
  await a.history.back(); await a.settle();
  assert.equal(a.state().selectedId, 'method-public:v1'); assert.equal(a.state().recordTab, 'connections');
  assert.equal(tabButton(a, 'connections').getAttribute('aria-pressed'), 'true');
  assert.equal(a.$('atlas-inspector').scrollTop, 960);
  assert.equal(a.$('atlas-inspector').classList.contains('is-tall'), true);
  await a.history.forward(); await a.settle();
  assert.equal(a.state().selectedId, 'method-linked:v1'); assert.equal(a.state().recordTab, 'steps');
  assert.equal(a.$('atlas-inspector').scrollTop, 220);
  await a.history.back(); await a.history.back(); await a.settle();
  assert.equal(a.state().selectedId, null);
  assert.equal(a.activeElement(), a.map, 'return from reader to map restores map focus');
});

test('reader linked method cards make the whole context a semantic action', async () => {
  const a = atlas({ reader: true }); await a.open('method-public:v1'); await a.settle();
  a.click(tabButton(a, 'connections'));
  const card = a.$('atlas-record').querySelectorAll('.path-card').find(n => textOf(n).includes('Linked public method'));
  assert.equal(card.tagName, 'BUTTON', 'entire linked card is a semantic action');
  assert.equal(card.querySelectorAll('button').length, 0, 'no nested buttons');
  a.click(card.children.at(-1)); await a.settle();
  assert.equal(a.state().selectedId, 'method-linked:v1');
});

test('reader next actions expose the next pane at its start', async () => {
  const a = atlas({ reader: true }); await a.open('method-public:v1'); await a.settle();
  const overview = a.$('atlas-record').querySelector('[data-record-pane="overview"]');
  const next = overview.querySelectorAll('.primary').find(n => textOf(n).includes('실행 순서'));
  assert.ok(next); a.$('atlas-inspector').scrollTop = 700; a.click(next);
  assert.equal(a.state().recordTab, 'steps'); assert.equal(a.$('atlas-inspector').scrollTop, 0);
  const steps = a.$('atlas-record').querySelector('[data-record-pane="steps"]');
  const connections = steps.querySelectorAll('button').find(n => textOf(n).includes('연결'));
  assert.ok(connections, 'steps offer a clear next action to connections');
  a.$('atlas-inspector').scrollTop = 500; a.click(connections, { detail: 0 });
  assert.equal(a.state().recordTab, 'connections'); assert.equal(a.$('atlas-inspector').scrollTop, 0);
  assert.equal(a.activeElement(), tabButton(a, 'connections'));
  assert.equal(a.$('atlas-record').querySelectorAll('.reading-route').length, 0, 'tab bar is the single reader navigation');
});

test('late public detail responses cannot replace a newer or restored reader', async () => {
  const a = atlas({ reader: true, deferred: true });
  const first = a.open('method-public:v1');
  const second = a.open('method-linked:v1');
  a.resolveDetail('method-linked'); await second;
  a.resolveDetail('method-public'); await first; await a.settle();
  assert.equal(a.state().selectedId, 'method-linked:v1');
  assert.ok(textOf(a.$('atlas-record')).includes('Situation for method-linked'));
  assert.ok(!textOf(a.$('atlas-record')).includes('Situation for method-public'));
  await a.history.back(); await a.settle();
  assert.equal(a.state().selectedId, 'method-public:v1');
  assert.ok(textOf(a.$('atlas-record')).includes('Situation for method-public'));
  assert.ok(!textOf(a.$('atlas-record')).includes('Situation for method-linked'));
  const b = atlas({ reader: true, deferred: true });
  const initial = b.open('method-public:v1'); b.resolveDetail('method-public'); await initial;
  const pending = b.open('method-linked:v1');
  await b.history.back(); await b.settle();
  b.resolveDetail('method-linked'); await pending; await b.settle();
  assert.equal(b.state().selectedId, 'method-public:v1');
  assert.ok(textOf(b.$('atlas-record')).includes('Situation for method-public'));
  assert.ok(!textOf(b.$('atlas-record')).includes('Situation for method-linked'));
});

test('captured graph tap consumes only its matching compatibility click', async () => {
  for (const permitted of ['second-click', 'new-contact', 'keyboard', 'different-pointer', 'different-position']) {
    const a = atlas({ reader: true });
    a.map.dispatch('pointerdown', { target: a.node, pointerId: 7 });
    a.map.dispatch('pointerup', { pointerId: 7 }); await a.settle();
    assert.equal(a.state().recordTab, 'overview');
    const button = tabButton(a, 'connections');
    const matching = { pointerId: 7, clientX: 100, clientY: 200 };
    if (permitted === 'second-click') {
      const ghost = a.click(button, matching);
      assert.equal(ghost.defaultPrevented, true); assert.equal(a.state().recordTab, 'overview');
    } else if (permitted === 'new-contact') a.document.dispatch('pointerdown', { target: button, pointerId: 8 });
    const props = permitted === 'keyboard' ? { ...matching, detail: 0 } : permitted === 'different-pointer' ? { ...matching, pointerId: 8 } : permitted === 'different-position' ? { ...matching, clientX: 120 } : matching;
    a.click(button, props);
    assert.equal(a.state().recordTab, 'connections', permitted);
  }
});
