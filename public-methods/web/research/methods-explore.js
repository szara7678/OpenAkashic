"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg", base = "/research/api/methods";
  const kinds = { category: "주제", situation: "상황", goal: "목적", method: "방법", outcome: "적용 결과", failure: "실패 보고", correction: "반영된 수정", source: "출처", opinion: "의견" };
  const relations = { categorized_as: "같은 주제로 분류", applies_in: "이 상황에 적용", pursues: "이 목적을 추구", documented_by: "참고한 출처", reported_application: "이 버전의 적용 보고", has_opinion: "이 버전에 남긴 의견", comments_on: "이 결과에 대한 의견", revises: "이전 버전에서 변경", implemented_by: "수정을 반영한 버전", addresses: "이 보고를 계기로 수정" };
  const statuses = { success: "성공 보고", partial: "부분 성공 보고", failure: "실패 보고", unknown: "판단 미정" };
  const index = new Map(), adj = new Map(), points = new Map(), cache = new Map(), pointers = new Map(), visited = new Set();
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let graph, selected = null, visible = [], edges = [], nodeElements = new Map(), edgeElements = [];
  let width = 1100, height = 760, zoom = 1, shift = { x: 0, y: 0 }, drag = null, suppressClick = false;
  let detailRequest = 0, animation = 0, ticks = 0, trail = [], filterTimer, cameraFrame = 0;
  let motion = !reduceMotion.matches, showAllLabels = false, lastFocusedNode = null;
  let recordTab = "overview", searchIndex = -1, searchItems = [], shareTimer;
  const map = $("atlas-map"), inspector = $("atlas-inspector");
  const role = n => n?.knowhow_role === "failure" ? "failure" : n?.kind;
  const label = n => kinds[role(n)] || "기록";
  const current = n => n.kind === "method" && !n.historical;
  const neighbors = id => adj.get(id) || [];
  const unique = list => [...new Map(list.map(x => [x.id, x])).values()];
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const svg = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const get = async path => { const r = await fetch(base + path, { credentials: "omit", headers: { Accept: "application/json" } }); if (!r.ok) throw Error("unavailable"); return r.json(); };
  const color = n => ["method", "category"].includes(n.kind) ? n.color || "var(--method)" : `var(--${role(n)})`;
  const short = (s, max = 22) => s.length > max ? s.slice(0, max) + "…" : s;

  function section(title, body, ordered = false) {
    const s = el("section", null, "record-section"); s.append(el("h3", title));
    if (Array.isArray(body)) { const list = el(ordered ? "ol" : "ul"); for (const x of body) list.append(el("li", x)); if (body.length) s.append(list); else s.append(el("p", "등록된 내용이 없습니다.", "quiet")); }
    else s.append(el("p", body || "등록된 내용이 없습니다."));
    return s;
  }
  function safeLink(title, url) {
    try { const u = new URL(url); if (!["https:", "http:"].includes(u.protocol)) return null; const a = el("a", title, "record-source"); a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; } catch { return null; }
  }
  function matchingMethods() {
    const q = $("atlas-filter").value.trim().toLocaleLowerCase(), domain = $("atlas-domain").value, filter = $("atlas-record-filter").value;
    return graph.nodes.filter(n => current(n) && (!domain || n.domain === domain) && (!q || [n.label, n.situation, n.goal, n.domain].some(x => x?.toLocaleLowerCase().includes(q))) && (!filter || graph.nodes.some(x => x.method_id === n.method_id && (filter === "reports" ? x.kind === "outcome" : filter === "failure" ? role(x) === "failure" : x.kind === "correction"))));
  }

  // Map coordinates survive selections. A detail click adds its recorded path;
  // switching to a local graph is an explicit, separate action.
  function view(fit = false) {
    if (!graph) return;
    const methods = matchingMethods(), families = new Set(methods.map(n => n.method_id)), ids = new Set(methods.map(n => n.id));
    const depth = Number($("atlas-depth").value);
    if (depth && selected) {
      ids.clear(); ids.add(selected.id); let frontier = [selected.id];
      for (let step = 0; step < depth; step++) { const next = []; for (const id of frontier) for (const n of neighbors(id)) if (!ids.has(n.id)) { ids.add(n.id); next.push(n.id); } frontier = next; }
      if (selected.kind === "method") for (const n of graph.nodes) if (n.method_id === selected.method_id) { ids.add(n.id); if (n.kind === "method") for (const a of neighbors(n.id)) if (index.get(a.id)?.kind !== "category") ids.add(a.id); }
    } else {
      for (const e of graph.edges) if (ids.has(e.source) && index.get(e.target)?.kind === "category") ids.add(e.target);
      for (const n of graph.nodes) if (families.has(n.method_id) && ["outcome", "correction"].includes(n.kind)) { ids.add(n.id); for (const a of neighbors(n.id)) if (index.get(a.id)?.kind === "method") ids.add(a.id); }
      if (selected) {
        ids.add(selected.id);
        for (const a of neighbors(selected.id)) ids.add(a.id);
        if (selected.method_id) for (const n of graph.nodes) if (n.method_id === selected.method_id) ids.add(n.id);
      }
      if ($("atlas-evidence").checked) for (const e of graph.edges) if (ids.has(e.source) && ["source", "opinion"].includes(index.get(e.target)?.kind)) ids.add(e.target);
    }
    visible = graph.nodes.filter(n => ids.has(n.id) && (!["source", "opinion"].includes(n.kind) || $("atlas-evidence").checked || selected?.id === n.id || depth > 0 || neighbors(selected?.id).some(x => x.id === n.id)));
    const shown = new Set(visible.map(n => n.id)); edges = graph.edges.filter(e => shown.has(e.source) && shown.has(e.target));
    const isInitial = points.size === 0;
    seedPoints(); draw();
    if (isInitial) { for (let i = 0; i < 150; i++) physics(); normalizeMobile(); positionElements(); }
    if (fit) fitVisible();
    if (isInitial && width > 720) startMotion(45);
    renderMethodList(methods);
    $("atlas-empty").hidden = visible.length > 0;
    $("atlas-visible").textContent = `${visible.length}개 기록 · ${edges.length}개 연결`;
    $("atlas-status").textContent = depth && selected ? `${label(selected)}의 주변 지도` : `${methods.length}개 방법을 탐험하세요${graph.scope.truncated ? " · 일부 범위" : ""}`;
    $("atlas-focus").disabled = !selected;
    $("atlas-focus").textContent = depth ? "전체 연결로 돌아가기" : "이 주변만 보기";
    $("atlas-focus").setAttribute("aria-pressed", String(Boolean(depth)));
    $("atlas-back").disabled = !(history.state?.atlasStep);
    document.querySelectorAll("[data-domain]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.domain === $("atlas-domain").value)));
    $("atlas-reports-start").setAttribute("aria-pressed", String($("atlas-record-filter").value === "reports"));
    $("atlas-failures-start").setAttribute("aria-pressed", String($("atlas-record-filter").value === "failure"));
    $("atlas-surprise").disabled = methods.length === 0;
  }
  function renderMethodList(methods) {
    const list = $("atlas-list"); list.replaceChildren();
    for (const n of methods) { const b = el("button", null); b.type = "button"; b.append(el("span", n.label), el("small", n.domain || "방법")); b.setAttribute("aria-pressed", String(n.id === selected?.id)); b.onclick = () => choose(n.id); list.append(b); }
    if (!methods.length) list.append(el("p", "검색어나 주제를 바꾸어 보세요.", "quiet"));
    $("atlas-list-count").textContent = methods.length;
  }
  function seedPoints() {
    const cats = graph.nodes.filter(n => n.kind === "category");
    cats.forEach((n, i) => {
      n.color = `var(--cluster-${i % 10})`;
      if (points.has(n.id)) return;
      const angle = i / cats.length * Math.PI * 2 - Math.PI / 2;
      const radius = i % 2 ? 1 : .72;
      const x = width / 2 + Math.cos(angle) * Math.max(140, width * .32) * radius;
      const y = height * .44 + Math.sin(angle) * Math.max(145, height * .29) * radius;
      points.set(n.id, { x, y, ax: x, ay: y, vx: 0, vy: 0 });
    });
    for (const n of graph.nodes.filter(current)) {
      const cat = neighbors(n.id).map(a => index.get(a.id)).find(x => x?.kind === "category"); n.color = cat?.color;
      if (points.has(n.id)) continue;
      const siblings = graph.nodes.filter(m => current(m) && m.domain === n.domain), j = siblings.indexOf(n);
      const a = j * 2.399963, radius = 50 + 24 * Math.sqrt(j + 1), center = points.get(cat?.id) || { x: width / 2, y: height / 2 };
      const x = center.x + Math.cos(a) * radius, y = center.y + Math.sin(a) * radius;
      points.set(n.id, { x, y, ax: x, ay: y, vx: 0, vy: 0 });
    }
    visible.forEach((n, i) => {
      if (points.has(n.id)) return;
      const parent = neighbors(n.id).map(a => points.get(a.id)).find(Boolean) || { x: width / 2, y: height / 2 };
      const a = i * 2.399963, x = parent.x + Math.cos(a) * 85, y = parent.y + Math.sin(a) * 85;
      points.set(n.id, { x, y, ax: x, ay: y, vx: 0, vy: 0 });
    });
  }
  function physics() {
    const ps = visible.map(n => points.get(n.id));
    for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) {
      const a = ps[i], b = ps[j], dx = a.x - b.x || .2, dy = a.y - b.y || .1, d2 = Math.max(25, dx * dx + dy * dy), d = Math.sqrt(d2);
      const f = Math.min(3, 250 / d2) + (d < 32 ? (32 - d) * .035 : 0);
      a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    for (const e of edges) {
      const a = points.get(e.source), b = points.get(e.target), dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
      const ideal = e.relation === "categorized_as" ? 95 : 78, f = (d - ideal) * .006;
      a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    visible.forEach((n, i) => { const p = ps[i]; if (p.pinned || drag?.node === n.id) { p.vx = p.vy = 0; return; } const force = n.kind === "category" ? .035 : .009; p.vx = (p.vx + (p.ax - p.x) * force) * .7; p.vy = (p.vy + (p.ay - p.y) * force) * .7; p.x += Math.max(-6, Math.min(6, p.vx)); p.y += Math.max(-6, Math.min(6, p.vy)); });
  }
  function startMotion(frames = 75) {
    if (!motion || reduceMotion.matches || document.hidden) return;
    ticks = Math.max(ticks, frames); if (animation) return;
    const tick = () => { physics(); positionElements(); if (--ticks > 0 && motion && !document.hidden) animation = requestAnimationFrame(tick); else { animation = 0; updateLabels(); } };
    animation = requestAnimationFrame(tick);
  }
  function stopMotion() { cancelAnimationFrame(animation); animation = 0; ticks = 0; }
  function draw() {
    $("atlas-edges").replaceChildren(); $("atlas-nodes").replaceChildren(); nodeElements = new Map(); edgeElements = [];
    for (const e of edges) {
      const line = svg("line", { class: "network-edge" + (e.relation === "categorized_as" ? " category" : ["documented_by", "has_opinion"].includes(e.relation) ? " evidence" : ""), "data-source": e.source, "data-target": e.target });
      const title = svg("title"); title.textContent = relations[e.relation] || "기록 연결"; line.append(title); $("atlas-edges").append(line); edgeElements.push([line, e]);
    }
    for (const n of visible) {
      const r = n.kind === "category" ? 8 + Math.min(4, neighbors(n.id).length / 4) : n.kind === "method" ? 5.5 + Math.min(3, neighbors(n.id).length * .25) : 5;
      const g = svg("g", { class: "network-node " + role(n), tabindex: "0", role: "button", "data-node-id": n.id, "aria-label": `${label(n)}: ${n.label.slice(0, 150)}`, "aria-pressed": String(selected?.id === n.id) });
      g.style.setProperty("--node-color", color(n)); g.append(svg("circle", { r: r + 13, class: "node-halo" }), svg("circle", { r: 20, class: "network-hit" }), svg("circle", { r, class: "node-core" }));
      const title = svg("title"); title.textContent = `${label(n)} · ${n.label}`; g.append(title);
      const text = svg("text", { x: 0, y: n.kind === "category" ? -21 : 23, "text-anchor": "middle" }); text.textContent = short(n.label, n.kind === "category" ? 20 : 18); g.append(text);
      g.onclick = e => { if (suppressClick || e.detail > 1) return; choose(n.id, true, e.detail === 0); };
      g.ondblclick = e => { e.preventDefault(); if (!suppressClick) { if (selected?.id !== n.id) choose(n.id); setLocal(2); } };
      g.onkeydown = e => { if (["Enter", " "].includes(e.key)) { e.preventDefault(); e.stopPropagation(); choose(n.id, true, true); } };
      g.onmouseenter = e => { if (drag) return; highlight(n.id); tooltip(n, e); };
      g.onmousemove = e => { if (!drag) tooltip(n, e); };
      g.onmouseleave = () => { highlight(selected?.id); $("atlas-tooltip").hidden = true; };
      g.onfocus = () => { stopMotion(); highlight(n.id); const b = g.getBoundingClientRect(); tooltip(n, { clientX: b.x + b.width / 2, clientY: b.y + b.height / 2 }); };
      g.onblur = () => { highlight(selected?.id); $("atlas-tooltip").hidden = true; };
      $("atlas-nodes").append(g); nodeElements.set(n.id, g);
    }
    positionElements(); highlight(selected?.id); transform();
  }
  function positionElements() {
    for (const [id, node] of nodeElements) { const p = points.get(id); node.setAttribute("transform", `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`); }
    for (const [line, e] of edgeElements) { const a = points.get(e.source), b = points.get(e.target); line.setAttribute("x1", a.x); line.setAttribute("y1", a.y); line.setAttribute("x2", b.x); line.setAttribute("y2", b.y); }
  }
  function highlight(id) {
    const near = new Set(id ? [id, ...neighbors(id).map(n => n.id)] : []);
    for (const [key, g] of nodeElements) { g.classList.toggle("dim", Boolean(id) && !near.has(key)); g.classList.toggle("selected", key === selected?.id); g.classList.toggle("neighbor", Boolean(id) && near.has(key)); g.classList.toggle("visited", visited.has(key)); g.setAttribute("aria-pressed", String(key === selected?.id)); }
    for (const [g, e] of edgeElements) { const active = e.source === id || e.target === id; g.classList.toggle("dim", Boolean(id) && !active); g.classList.toggle("highlight", active); }
    updateLabels(id);
  }
  function screenPoint(p) { return { x: width / 2 + shift.x + (p.x - width / 2) * zoom, y: height / 2 + shift.y + (p.y - height / 2) * zoom }; }
  function worldPoint(p) { return { x: (p.x - width / 2 - shift.x) / zoom + width / 2, y: (p.y - height / 2 - shift.y) / zoom + height / 2 }; }
  function updateLabels(hover) {
    const mapBounds = map.getBoundingClientRect();
    const obstacles = ["atlas-discovery", "atlas-controls", "atlas-inspector", "atlas-trail", "atlas-help-panel"].map($).filter(n => n && !n.hidden).map(n => {
      const b = n.getBoundingClientRect(); return { x: b.left - mapBounds.left - 8, y: b.top - mapBounds.top - 8, w: b.width + 16, h: b.height + 16 };
    });
    const occupied = [], ordered = [...visible].sort((a, b) => {
      const score = n => n.id === (hover || selected?.id) ? 1000 : n.kind === "category" ? 900 : neighbors(selected?.id).some(x => x.id === n.id) ? 800 : visited.has(n.id) ? 500 : neighbors(n.id).length;
      return score(b) - score(a);
    });
    for (const n of ordered) {
      const node = nodeElements.get(n.id), point = points.get(n.id);
      if (!node || !point) continue;
      const p = screenPoint(point);
      const text = node.querySelector("text"), labelScale = 1;
      text.style.fontSize = ((n.kind === "category" ? 13 : 12) * labelScale / zoom) + "px";
      text.setAttribute("y", (n.kind === "category" ? -21 : 23) / zoom);
      const w = text.getComputedTextLength() * zoom;
      const y = p.y + (n.kind === "category" ? -30 : 14), box = { x: p.x - w / 2 - 5, y, w: w + 10, h: 18 };
      const within = box.x > 8 && box.x + box.w < width - 8 && box.y > 8 && box.y + box.h < height - 8;
      const overlaps = occupied.some(b => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
      const important = n.id === selected?.id || n.id === hover;
      const covered = obstacles.some(b => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
      const detailed = width > 720 || zoom > 1.15 || n.kind === "category" || Boolean(selected) || $("atlas-domain").value || $("atlas-filter").value;
      const show = within && !covered && (important || ((detailed || showAllLabels) && !overlaps));
      node.classList.toggle("hint-label", show);
      if (show) occupied.push(box);
      node.querySelector(".network-hit").setAttribute("r", Math.max(17, 18 / zoom));
      const baseRadius = n.kind === "category" ? 8 + Math.min(4, neighbors(n.id).length / 4) : n.kind === "method" ? 5.5 + Math.min(3, neighbors(n.id).length * .25) : 5;
      node.querySelector(".node-core").setAttribute("r", Math.max(baseRadius, (n.kind === "category" ? 7 : 4) / zoom));
    }
  }

  function linkedCard(n, relation) {
    const card = el("div", null, "path-card"); card.style.setProperty("--node-color", color(n));
    card.append(el("span", n.kind === "outcome" ? statuses[n.status] || "적용 보고" : label(n), "path-role"));
    const b = el("button", n.label); b.type = "button"; b.onclick = () => choose(n.id); card.append(b);
    if (n.method_version) card.append(el("small", `방법 v${n.method_version}${n.kind === "correction" ? " · 반영된 변경" : " · 작성자 보고"}`));
    if (n.historical) card.append(el("small", `이전 버전 v${n.version}`));
    if (relation) card.title = relations[relation] || "연결된 기록";
    return card;
  }
  function openInspector() { closeSearch(); inspector.hidden = false; document.body.classList.add("inspector-open"); controls(false); $("atlas-help-panel").hidden = true; $("atlas-help").setAttribute("aria-expanded", "false"); setDiscovery(false); }
  function closeInspector(focus = false) {
    inspector.hidden = true; inspector.classList.remove("is-tall"); document.body.classList.remove("inspector-open");
    $("atlas-inspector-expand").setAttribute("aria-expanded", "false"); $("atlas-inspector-expand").textContent = "크게 읽기";
    if (focus) (nodeElements.get(lastFocusedNode) || map).focus({ preventScroll: true });
  }
  async function choose(id, push = true, keyboard = false, restore = false) {
    const n = index.get(id); if (!n) return;
    clearTimeout(filterTimer);
    selected = n; visited.add(id); lastFocusedNode = id; stopMotion(); $("atlas-tooltip").hidden = true;
    if (!restore) { trail = trail.at(-1) === id ? trail : [...trail, id].slice(-16); }
    const token = ++detailRequest;
    $("atlas-record-kicker").textContent = label(n) + (n.kind === "method" ? ` / v${n.version}` : "");
    $("atlas-record-title").textContent = n.kind === "outcome" ? statuses[n.status] || "적용 결과" : n.kind === "correction" ? "경험을 반영한 수정" : n.label;
    const panel = $("atlas-record"); panel.replaceChildren(); recordTab = "overview";
    $("atlas-share").textContent = "링크 복사";
    $("atlas-record-tabs").querySelector('[data-record-tab="steps"]').hidden = n.kind !== "method";
    const meta = el("details", null, "record-meta"); meta.append(el("summary", "기록 정보"), el("code", n.id, "record-id"));
    openInspector(); inspector.scrollTop = 0; view(false); renderTrail();
    if (push) writeHistory(true);
    if (!restore) requestAnimationFrame(() => keepSelectedInView());
    const related = el("section", null, "record-section record-neighbors"); related.append(el("h3", "이어서 탐험하기"));
    const rank = { method: 0, outcome: 1, correction: 2, situation: 3, goal: 4, category: 5, source: 6, opinion: 7 };
    const links = unique(neighbors(id)).sort((a, b) => (rank[index.get(a.id)?.kind] ?? 9) - (rank[index.get(b.id)?.kind] ?? 9));
    links.forEach(a => { const target = index.get(a.id); if (target) related.append(linkedCard(target, a.relation)); });
    const content = el("div", null, "record-content"), steps = el("div", null, "record-steps");
    content.dataset.recordPane = "overview"; steps.dataset.recordPane = "steps"; related.dataset.recordPane = "connections";
    if (!links.length) related.append(el("p", "아직 연결된 기록이 없습니다.", "quiet"));
    const jump = el("button", `연결된 기록 ${links.length}개 살펴보기 →`, "connection-jump"); jump.type = "button"; jump.onclick = () => setRecordTab("connections");
    panel.append(content, steps, related, meta); setRecordTab("overview");
    if (n.kind === "method") {
      const loading = el("p", "상황과 실행 기록을 불러오는 중…", "quiet"); content.append(loading); steps.append(el("p", "실행 순서를 불러오는 중…", "quiet"));
      try {
        const key = n.method_id + ":v" + n.version, d = cache.get(key) || await get("/" + encodeURIComponent(n.method_id) + (n.historical ? "/versions/" + n.version : ""));
        cache.set(key, d); if (token !== detailRequest) return; loading.remove();
        content.append(section("이런 상황에서", d.situation), section("이루려는 목적", d.goal));
        const pathLinks = links.map(a => index.get(a.id)).filter(x => ["outcome", "correction"].includes(x?.kind));
        if (pathLinks.length) { const s = el("section", null, "record-section"); s.append(el("h3", "적용 후 남은 기록")); pathLinks.forEach(x => s.append(linkedCard(x))); content.append(s); }
        steps.replaceChildren(section("따라 해 볼 순서", d.steps || [], true));
        const more = el("details", null, "record-more"); more.append(el("summary", "적용 조건 · 성공 기준 · 한계"), section("적용 조건", d.constraints || []), section("성공을 판단할 기준", d.success_criteria || []), section("한계와 주의점", d.limitations || [])); steps.append(more); more.open = true;
        if (d.revision) { content.append(section(`v${d.revision.previous_version}에서 달라진 점`, d.revision.reason)); if (d.revision.correction) content.append(section("반영한 수정", d.revision.correction.reason)); }
        if (d.sources?.length) { const sources = el("section", null, "record-section"); sources.append(el("h3", "원래 출처")); for (const source of d.sources) { const a = safeLink(source.title || source.url, source.url); if (a) sources.append(a, el("br")); } content.append(sources); }
        content.append(el("p", d.evidence_kind === "documented_method" ? "문서에서 정리한 방법입니다. 적용 결과는 실행자의 보고이며, 효과의 독립 검증과 구분합니다." : "기록된 방법과 적용 보고를 함께 읽고, 자신의 상황에 맞는지 확인하세요.", "record-warning"));
        const a = el("a", "방법과 적용 보고 전체 읽기 ↗", "record-source"); a.href = "/research/methods/library/?method=" + encodeURIComponent(n.method_id); content.append(a);
        const go = el("button", "실행 순서 살펴보기 →", "primary"); go.type = "button"; go.onclick = () => setRecordTab("steps"); content.append(go);
      } catch { if (token === detailRequest) { loading.textContent = "본문을 불러오지 못했습니다. 연결된 기록을 살펴보거나 다시 선택해 주세요."; steps.replaceChildren(el("p", "실행 순서를 불러오지 못했습니다. 방법을 다시 선택해 주세요.", "quiet")); } }
    } else if (n.kind === "source") {
      const a = safeLink("원래 출처 열기 ↗", n.url); if (a) content.append(a);
      content.append(section("이 출처와 연결된 방법", "아래 방법을 정리할 때 참고한 출처입니다. 같은 출처를 사용했다는 것이 독립적인 검증을 뜻하지는 않습니다."));
    } else if (n.kind === "category") content.append(el("p", `‘${n.label}’에 연결된 방법 ${links.filter(a => index.get(a.id)?.kind === "method").length}개. 관심 있는 방법으로 이어가 보세요.`, "quiet"));
    else if (n.kind === "correction") content.append(section("실제로 반영한 변경", n.label), section("이어지는 버전", `v${n.corrected_method_version}의 보고를 참고해 v${n.method_version}에 반영했습니다. 변경 이후의 효과는 별도 적용 보고로 확인합니다.`));
    else if (n.kind === "outcome") {
      content.append(section("실행자가 관찰한 결과", n.label), section("보고된 버전과 작성자", `방법 v${n.method_version} · ${n.reported_by || "작성자 미표시"} (자기 표시)`));
      try { const d = await get("/" + encodeURIComponent(n.method_id)); if (token !== detailRequest) return; const report = d.outcomes?.find(x => x.id === n.id); if (report) { if (report.situation) content.append(section("실제로 적용한 상황", report.situation)); if (report.goal) content.append(section("당시 목적", report.goal)); if (report.actions?.length) content.append(section("실제로 한 일", report.actions, true)); if (report.evidence?.length) content.append(section("작성자가 남긴 근거 설명", report.evidence.map(x => x.description))); } } catch { content.append(el("p", "추가 본문을 불러오지 못했습니다.", "quiet")); }
    } else content.append(section(n.kind === "opinion" ? "작성자가 남긴 의견" : label(n), n.label));
    if (token !== detailRequest) return;
    if (keyboard) $("atlas-inspector-close").focus({ preventScroll: true });
  }

  function setRecordTab(value) {
    recordTab = value;
    $("atlas-record-tabs").querySelectorAll("[data-record-tab]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.recordTab === value)));
    $("atlas-record").querySelectorAll("[data-record-pane]").forEach(n => { n.hidden = n.dataset.recordPane !== value; });
  }
  $("atlas-record-tabs").addEventListener("click", e => { const b = e.target.closest("[data-record-tab]"); if (b) { setRecordTab(b.dataset.recordTab); inspector.scrollTop = 0; } });
  $("atlas-share").onclick = async () => {
    const b = $("atlas-share"); clearTimeout(shareTimer);
    try { await navigator.clipboard.writeText(location.href); b.textContent = "복사했어요"; }
    catch { b.textContent = "주소창의 링크를 복사하세요"; }
    shareTimer = setTimeout(() => { b.textContent = "링크 복사"; }, 3000);
  };

  function availableRect() {
    const mobile = width <= 720, discovery = $("atlas-discovery"), graphRect = map.getBoundingClientRect();
    const bottom = !inspector.hidden && mobile ? Math.max(140, inspector.getBoundingClientRect().top - graphRect.top - 20) : height - 110;
    const top = mobile ? !inspector.hidden ? 115 : discovery.getBoundingClientRect().bottom - graphRect.top + 22 : 65;
    return { left: mobile ? 22 : !$("atlas-discovery-content").hidden ? discovery.getBoundingClientRect().right - graphRect.left + 30 : 45, top, right: !inspector.hidden && !mobile ? Math.max(220, inspector.getBoundingClientRect().left - graphRect.left - 35) : width - (mobile ? 22 : 35), bottom: Math.max(top + 100, bottom) };
  }
  function normalizeMobile() {
    if (width > 720 || !visible.length || selected) return;
    const ps = visible.map(n => points.get(n.id)), box = availableRect();
    const minX = Math.min(...ps.map(p => p.x)), maxX = Math.max(...ps.map(p => p.x)), minY = Math.min(...ps.map(p => p.y)), maxY = Math.max(...ps.map(p => p.y));
    const sx = Math.min(1, (box.right - box.left - 42) / Math.max(1, maxX - minX)), sy = Math.min(1.5, (box.bottom - box.top - 50) / Math.max(1, maxY - minY));
    for (const p of points.values()) { p.x = (box.left + box.right) / 2 + (p.x - (minX + maxX) / 2) * sx; p.y = (box.top + box.bottom) / 2 + (p.y - (minY + maxY) / 2) * sy; p.ax = p.x; p.ay = p.y; p.vx = p.vy = 0; }
  }
  function setDiscovery(open) {
    $("atlas-discovery-content").hidden = !open; $("atlas-discovery-toggle").setAttribute("aria-expanded", String(open)); $("atlas-discovery-toggle").setAttribute("aria-label", open ? "탐험 시작점 접기" : "탐험 시작점 펼치기"); $("atlas-discovery").classList.toggle("is-collapsed", !open);
    requestAnimationFrame(() => { const r = $("atlas-discovery").getBoundingClientRect(), m = map.getBoundingClientRect(); document.documentElement.style.setProperty("--trail-top", (r.bottom - m.top + 12) + "px"); updateLabels(); });
  }
  function keepSelectedInView() {
    if (!selected || !points.has(selected.id)) return;
    const p = screenPoint(points.get(selected.id)), box = availableRect();
    const pad = 35, target = { x: shift.x, y: shift.y };
    if (p.x < box.left + pad || p.x > box.right - pad) target.x += (box.left + box.right) / 2 - p.x;
    if (p.y < box.top + pad || p.y > box.bottom - pad) target.y += (box.top + box.bottom) / 2 - p.y;
    moveCamera(target);
  }
  function moveCamera(target) {
    cancelAnimationFrame(cameraFrame);
    if (reduceMotion.matches) { shift = target; transform(); return; }
    const start = { ...shift }, time = performance.now();
    const frame = now => { const p = Math.min(1, (now - time) / 220), ease = 1 - Math.pow(1 - p, 3); shift = { x: start.x + (target.x - start.x) * ease, y: start.y + (target.y - start.y) * ease }; transform(); if (p < 1) cameraFrame = requestAnimationFrame(frame); };
    cameraFrame = requestAnimationFrame(frame);
  }
  function transform() {
    $("atlas-viewport").setAttribute("transform", `translate(${width / 2 + shift.x} ${height / 2 + shift.y}) scale(${zoom}) translate(${-width / 2} ${-height / 2})`);
    $("atlas-zoom-label").textContent = Math.round(zoom * 100) + "%"; updateLabels();
  }
  function fitVisible() {
    cancelAnimationFrame(cameraFrame); if (!visible.length) return;
    const ps = visible.map(n => points.get(n.id)), xs = ps.map(p => p.x), ys = ps.map(p => p.y);
    const pad = width <= 720 ? 22 : 65, minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - 30, maxY = Math.max(...ys) + 30, box = availableRect();
    zoom = Math.max(.16, Math.min(1.7, (box.right - box.left) / (maxX - minX), (box.bottom - box.top) / (maxY - minY)));
    shift = { x: (box.left + box.right) / 2 - width / 2 - ((minX + maxX) / 2 - width / 2) * zoom, y: (box.top + box.bottom) / 2 - height / 2 - ((minY + maxY) / 2 - height / 2) * zoom }; transform();
  }
  function scale(factor, anchor = { x: width / 2, y: height / 2 }) {
    cancelAnimationFrame(cameraFrame); const next = Math.max(.16, Math.min(7, zoom * factor)), ratio = next / zoom;
    shift = { x: anchor.x - width / 2 - (anchor.x - width / 2 - shift.x) * ratio, y: anchor.y - height / 2 - (anchor.y - height / 2 - shift.y) * ratio }; zoom = next; transform();
  }
  function coords(x, y) { return new DOMPoint(x, y).matrixTransform(map.getScreenCTM().inverse()); }
  function tooltip(n, e) {
    const t = $("atlas-tooltip"), r = map.getBoundingClientRect(); t.replaceChildren(el("small", label(n)), el("strong", short(n.label, 85)));
    if (n.goal) t.append(el("span", short(n.goal, 100)));
    t.hidden = false; t.style.left = Math.max(8, Math.min(r.width - 280, e.clientX - r.left + 16)) + "px"; t.style.top = Math.max(8, Math.min(r.height - 120, e.clientY - r.top + 18)) + "px";
  }
  function controls(open, focus = true) { if (open) closeSearch(); $("atlas-controls").hidden = !open; document.body.classList.toggle("controls-open", open); $("atlas-controls-toggle").setAttribute("aria-expanded", String(open)); if (open) { if (width <= 720) closeInspector(); if (focus) $("atlas-filter").focus(); } }
  function renderTrail() {
    const nav = $("atlas-trail"); nav.replaceChildren(); nav.hidden = trail.length === 0;
    if (!trail.length) return;
    nav.append(el("span", "지나온 연결", "trail-label"));
    for (const id of trail.slice(-5)) { const n = index.get(id); if (!n) continue; const b = el("button", short(n.label, 16)); b.type = "button"; b.title = n.label; if (id === selected?.id) b.setAttribute("aria-current", "step"); b.onclick = () => choose(id); nav.append(b); }
    requestAnimationFrame(() => { nav.scrollLeft = nav.scrollWidth; });
  }
  function writeHistory(push) {
    const url = new URL(location.href); for (const key of ["node", "method", "depth", "domain", "q", "records"]) url.searchParams.delete(key);
    if (selected) url.searchParams.set("node", selected.id);
    if (Number($("atlas-depth").value)) url.searchParams.set("depth", $("atlas-depth").value);
    if ($("atlas-domain").value) url.searchParams.set("domain", $("atlas-domain").value);
    if ($("atlas-filter").value) url.searchParams.set("q", $("atlas-filter").value);
    if ($("atlas-record-filter").value) url.searchParams.set("records", $("atlas-record-filter").value);
    const previous = history.state?.atlasStep || 0, state = { atlasStep: push ? previous + 1 : previous, trail: [...trail] };
    if (push && url.href !== location.href) history.pushState(state, "", url); else history.replaceState({ ...state, atlasStep: previous }, "", url);
    $("atlas-back").disabled = !(history.state?.atlasStep);
  }
  function resetMap(updateHistory = true) {
    clearTimeout(filterTimer); closeSearch(); selected = null; ++detailRequest; trail = []; $("atlas-tooltip").hidden = true;
    for (const id of ["atlas-domain", "atlas-filter", "atlas-quick-search", "atlas-record-filter"]) $(id).value = "";
    $("atlas-depth").value = "0"; closeInspector(); controls(false); setDiscovery(true); renderTrail(); view(true); if (updateHistory) writeHistory(false);
  }
  function filtersChanged() {
    selected = null; ++detailRequest; $("atlas-depth").value = "0"; closeInspector(); view(true); writeHistory(false);
  }
  function setLocal(depth) { if (!selected) return; $("atlas-depth").value = String(depth); view(true); writeHistory(false); }
  function selectDomain(value) { if (!graph) return; clearTimeout(filterTimer); closeSearch(); if (value) setDiscovery(false); selected = null; ++detailRequest; $("atlas-domain").value = value; $("atlas-filter").value = $("atlas-quick-search").value = ""; $("atlas-record-filter").value = ""; $("atlas-depth").value = "0"; closeInspector(); controls(false); view(true); writeHistory(false); }
  function reportFilter(value) { if (!graph) return; selected = null; ++detailRequest; $("atlas-record-filter").value = $("atlas-record-filter").value === value ? "" : value; $("atlas-depth").value = "0"; closeInspector(); view(true); writeHistory(false); }
  function surprise() {
    if (!graph) return;
    let pool = matchingMethods().filter(n => !visited.has(n.id)); if (!pool.length) pool = matchingMethods().filter(n => n.id !== selected?.id);
    if (pool.length) choose(pool[Math.floor(Math.random() * pool.length)].id);
  }
  function theme(value) { document.documentElement.dataset.theme = value; const light = value === "light"; $("atlas-theme").setAttribute("aria-label", light ? "어두운 테마로 전환" : "밝은 테마로 전환"); const icon = svg("svg", { viewBox: "0 0 24 24", width: 18, height: 18, fill: "none", stroke: "currentColor", "stroke-width": 1.7, "aria-hidden": "true" });
    icon.append(svg("path", { d: light ? "M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z" : "M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" })); if (!light) icon.append(svg("circle", { cx: 12, cy: 12, r: 4 })); $("atlas-theme").replaceChildren(icon); try { localStorage.setItem("openakashic-graph-theme", value); } catch {} }
  try { theme(localStorage.getItem("openakashic-graph-theme") === "light" ? "light" : "dark"); } catch { theme("dark"); }
  $("atlas-theme").onclick = () => theme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  $("atlas-controls-toggle").onclick = () => controls($("atlas-controls").hidden);
  $("atlas-controls-close").onclick = () => { controls(false); $("atlas-controls-toggle").focus(); };
  $("atlas-inspector-close").onclick = () => closeInspector(true);
  $("atlas-inspector-expand").onclick = () => { const tall = inspector.classList.toggle("is-tall"); $("atlas-inspector-expand").setAttribute("aria-expanded", String(tall)); $("atlas-inspector-expand").textContent = tall ? "지도와 함께" : "크게 읽기"; };
  $("atlas-surprise").onclick = surprise; $("atlas-start").onclick = surprise;
  $("atlas-discovery-toggle").onclick = () => setDiscovery($("atlas-discovery-content").hidden);
  $("atlas-help").onclick = () => { const open = $("atlas-help-panel").hidden; $("atlas-help-panel").hidden = !open; $("atlas-help").setAttribute("aria-expanded", String(open)); };
  $("atlas-labels").onclick = () => { showAllLabels = !showAllLabels; $("atlas-labels").setAttribute("aria-pressed", String(showAllLabels)); updateLabels(); };
  $("atlas-motion").setAttribute("aria-pressed", String(motion));
  $("atlas-motion").onclick = () => { motion = !motion; $("atlas-motion").setAttribute("aria-pressed", String(motion)); if (motion) startMotion(); else stopMotion(); };
  reduceMotion.addEventListener("change", () => { if (reduceMotion.matches) { motion = false; stopMotion(); $("atlas-motion").setAttribute("aria-pressed", "false"); } });
  $("atlas-reset").onclick = () => resetMap(); $("atlas-fit").onclick = fitVisible;
  $("atlas-zoom-in").onclick = () => scale(1.25); $("atlas-zoom-out").onclick = () => scale(.8);
  $("atlas-focus").onclick = () => setLocal(Number($("atlas-depth").value) ? 0 : 2);
  $("atlas-back").onclick = () => history.back();
  $("atlas-expand").onclick = async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen(); } catch { $("atlas-status").textContent = "브라우저 전체 화면은 지원되지 않습니다. 현재 지도는 창 크기에 맞춰져 있습니다."; } };
  document.addEventListener("fullscreenchange", () => $("atlas-expand").setAttribute("aria-pressed", String(Boolean(document.fullscreenElement))));
  ["atlas-domain", "atlas-record-filter"].forEach(id => $(id).onchange = filtersChanged);
  function closeSearch() { $("atlas-search-results").hidden = true; searchIndex = -1; $("atlas-quick-search").setAttribute("aria-expanded", "false"); }
  function showSearch() {
    if (!graph) return;
    const results = $("atlas-search-results"), methods = matchingMethods(); results.replaceChildren(); searchItems = methods.slice(0, 8); searchIndex = -1;
    const summary = el("p", methods.length ? `${methods.length}개 방법 · 상황과 목적을 살펴보세요` : "일치하는 방법이 없습니다", "search-summary"); results.append(summary);
    for (const n of searchItems) {
      const b = el("button", null, "search-result"); b.type = "button"; b.append(el("small", n.domain || "방법"), el("strong", n.label), el("span", short(n.situation || n.goal || "", 90)));
      b.onclick = () => choose(n.id, true, true); results.append(b);
    }
    if (!methods.length) results.append(el("p", "짧은 단어로 검색하거나 필터에서 분야를 바꿔 보세요.", "search-empty"));
    if (methods.length > 8) { const more = el("button", `전체 ${methods.length}개를 목록에서 보기`, "search-more"); more.type = "button"; more.onclick = () => controls(true); results.append(more); }
    results.hidden = false; $("atlas-quick-search").setAttribute("aria-expanded", "true");
  }
  for (const id of ["atlas-filter", "atlas-quick-search"]) $(id).oninput = () => {
    $(id === "atlas-filter" ? "atlas-quick-search" : "atlas-filter").value = $(id).value; clearTimeout(filterTimer);
    filterTimer = setTimeout(() => { filtersChanged(); if (id === "atlas-quick-search" && document.activeElement === $(id)) showSearch(); }, 120);
  };
  $("atlas-quick-search").onfocus = () => { controls(false); showSearch(); };
  $("atlas-quick-search").setAttribute("aria-controls", "atlas-search-results");
  $("atlas-quick-search").setAttribute("aria-expanded", "false");
  $("atlas-quick-search").onkeydown = e => {
    if (e.key === "ArrowDown" || e.key === "Enter") {
      e.preventDefault(); clearTimeout(filterTimer); filtersChanged(); showSearch();
      const first = $("atlas-search-results").querySelector(".search-result"); if (first) { if (e.key === "Enter") first.click(); else first.focus(); }
    }
  };
  $("atlas-search-results").onkeydown = e => {
    if (!["ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault(); const buttons = [...$("atlas-search-results").querySelectorAll("button")], currentIndex = buttons.indexOf(document.activeElement), next = currentIndex + (e.key === "ArrowDown" ? 1 : -1);
    if (next < 0) $("atlas-quick-search").focus(); else buttons[Math.min(buttons.length - 1, next)]?.focus();
  };
  document.addEventListener("pointerdown", e => { if (!$("atlas-search-results").contains(e.target) && !e.target.closest(".quick-search")) closeSearch(); });
  document.addEventListener("focusin", e => { if (!$("atlas-search-results").contains(e.target) && e.target !== $("atlas-quick-search")) closeSearch(); });
  $("atlas-evidence").onchange = () => view(false);
  $("atlas-depth").onchange = () => { if (!selected) $("atlas-depth").value = "0"; view(true); writeHistory(false); };
  $("atlas-reports-start").onclick = () => reportFilter("reports"); $("atlas-failures-start").onclick = () => reportFilter("failure");

  map.addEventListener("wheel", e => { if (!graph || !e.deltaY) return; e.preventDefault(); const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? height : 1; scale(Math.exp(-Math.max(-200, Math.min(200, e.deltaY * unit)) * .0025), coords(e.clientX, e.clientY)); $("atlas-tooltip").hidden = true; }, { passive: false });
  map.addEventListener("pointerdown", e => {
    if (e.button !== 0 || !graph) return; cancelAnimationFrame(cameraFrame); stopMotion(); const p = coords(e.clientX, e.clientY);
    pointers.set(e.pointerId, p); suppressClick = false; const node = e.target.closest(".network-node")?.dataset.nodeId;
    drag = { pointer: e.pointerId, last: p, client: { x: e.clientX, y: e.clientY }, moved: false, node };
    if (!node) map.setPointerCapture(e.pointerId);
  });
  map.addEventListener("pointermove", e => {
    if (!pointers.has(e.pointerId)) return;
    const before = [...pointers.values()], p = coords(e.clientX, e.clientY); pointers.set(e.pointerId, p);
    if (pointers.size === 2) {
      const after = [...pointers.values()], oldDist = Math.hypot(before[0].x - before[1].x, before[0].y - before[1].y), newDist = Math.hypot(after[0].x - after[1].x, after[0].y - after[1].y), mid = { x: (before[0].x + before[1].x) / 2, y: (before[0].y + before[1].y) / 2 };
      if (oldDist > 2) scale(newDist / oldDist, mid); shift.x += (after[0].x + after[1].x) / 2 - mid.x; shift.y += (after[0].y + after[1].y) / 2 - mid.y; transform(); suppressClick = true; drag = null; return;
    }
    if (!drag || drag.pointer !== e.pointerId) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.client.x, e.clientY - drag.client.y) < 5) return;
    drag.moved = true; suppressClick = true;
    if (!map.hasPointerCapture(e.pointerId)) map.setPointerCapture(e.pointerId);
    if (drag.node) {
      const point = points.get(drag.node), world = worldPoint(p); point.x = world.x; point.y = world.y; point.ax = world.x; point.ay = world.y; point.pinned = true; point.vx = point.vy = 0;
      positionElements(); updateLabels(); startMotion(35);
    } else { shift.x += p.x - drag.last.x; shift.y += p.y - drag.last.y; transform(); }
    drag.last = p; $("atlas-tooltip").hidden = true;
  });
  function endPointer(e) {
    const moved = drag?.moved, node = drag?.node; pointers.delete(e.pointerId); drag = null;
    if (map.hasPointerCapture(e.pointerId)) map.releasePointerCapture(e.pointerId);
    if (moved && node) startMotion(45);
    setTimeout(() => { suppressClick = false; }, 0);
  }
  map.addEventListener("pointerup", endPointer); map.addEventListener("pointercancel", endPointer);
  map.addEventListener("lostpointercapture", e => { pointers.delete(e.pointerId); if (drag?.pointer === e.pointerId) drag = null; });
  map.addEventListener("dblclick", e => { if (!e.target.closest(".network-node")) scale(1.4, coords(e.clientX, e.clientY)); });
  map.addEventListener("keydown", e => {
    const move = e.shiftKey ? 100 : 40, shifts = { ArrowLeft: [move, 0], ArrowRight: [-move, 0], ArrowUp: [0, move], ArrowDown: [0, -move] };
    if (["+", "=", "-", "Home", ...Object.keys(shifts)].includes(e.key)) { e.preventDefault(); if (e.key === "Home") fitVisible(); else if (shifts[e.key]) { shift.x += shifts[e.key][0]; shift.y += shifts[e.key][1]; transform(); } else scale(e.key === "-" ? .8 : 1.25); }
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { if (!$("atlas-search-results").hidden) { closeSearch(); $("atlas-quick-search").blur(); } else if (!$("atlas-help-panel").hidden) { $("atlas-help-panel").hidden = true; $("atlas-help").setAttribute("aria-expanded", "false"); } else if (!$("atlas-controls").hidden) { controls(false); $("atlas-controls-toggle").focus(); } else if (!inspector.hidden) closeInspector(true); }
    if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) { e.preventDefault(); $("atlas-quick-search").focus(); }
  });
  function restoreLocation() {
    if (!graph) return; const q = new URLSearchParams(location.search);
    $("atlas-domain").value = q.get("domain") || ""; $("atlas-filter").value = $("atlas-quick-search").value = q.get("q") || "";
    $("atlas-record-filter").value = ["reports", "failure", "correction"].includes(q.get("records")) ? q.get("records") : "";
    $("atlas-depth").value = ["1", "2"].includes(q.get("depth")) ? q.get("depth") : "0";
    trail = (history.state?.trail || []).filter(id => index.has(id));
    const id = q.get("node"), method = q.get("method"), node = index.get(id) || graph.nodes.find(n => current(n) && n.method_id === method);
    if (node) { if (!trail.length) trail = [node.id]; choose(node.id, false, false, true); requestAnimationFrame(() => { fitVisible(); keepSelectedInView(); }); }
    else { selected = null; ++detailRequest; closeInspector(); renderTrail(); view(true); }
  }
  window.addEventListener("popstate", restoreLocation);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopMotion(); });
  const observer = new ResizeObserver(() => {
    const r = map.getBoundingClientRect(); if (!r.width || !r.height) return;
    const previousWidth = width, dx = r.width - width, dy = r.height - height; width = r.width; height = r.height; map.setAttribute("viewBox", `0 0 ${width} ${height}`);
    for (const p of points.values()) { p.x += dx / 2; p.ax += dx / 2; p.y += dy / 2; p.ay += dy / 2; }
    if (graph && width <= 720 && previousWidth > 720) normalizeMobile(); positionElements(); if (graph) { if (selected) { transform(); requestAnimationFrame(keepSelectedInView); } else fitVisible(); }
  }); observer.observe(map);
  (async () => {
    try {
      graph = await get("/network?limit=80"); for (const n of graph.nodes) { index.set(n.id, n); adj.set(n.id, []); }
      for (const e of graph.edges) { if (!index.has(e.source) || !index.has(e.target)) continue; adj.get(e.source).push({ id: e.target, relation: e.relation }); adj.get(e.target).push({ id: e.source, relation: e.relation }); }
      $("atlas-total").textContent = graph.scope.total_methods; $("atlas-feedback-count").textContent = graph.nodes.filter(n => n.kind === "outcome").length;
      const chips = $("atlas-domain-chips"); chips.replaceChildren();
      const all = el("button", "모든 주제"); all.type = "button"; all.dataset.domain = ""; all.onclick = () => selectDomain(""); chips.append(all);
      for (const d of graph.domains) {
        const option = el("option", `${d.name} · ${d.count}`); option.value = d.name; $("atlas-domain").append(option);
        const b = el("button", d.name); b.type = "button"; b.dataset.domain = d.name; const catIndex = graph.nodes.filter(n => n.kind === "category").findIndex(n => n.label === d.name); b.style.setProperty("--chip-color", `var(--cluster-${Math.max(0, catIndex) % 10})`); b.append(el("small", d.count)); b.onclick = () => selectDomain(d.name); chips.append(b);
      }
      if (width <= 720) setDiscovery(false);
      restoreLocation();
    } catch {
      $("atlas-status").textContent = "지도를 불러오지 못했습니다."; $("atlas-empty").hidden = false;
      $("atlas-empty").replaceChildren(el("strong", "잠시 연결이 끊겼습니다."), el("p", "새로고침하거나 목록에서 방법을 찾아보세요."));
      $("atlas-start").disabled = $("atlas-surprise").disabled = true;
    }
  })();
})();
