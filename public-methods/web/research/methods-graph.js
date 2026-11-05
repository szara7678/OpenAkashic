"use strict";
window.OpenAkashicMethodGraph = (() => {
  const names = {situation:"어떤 상황", goal:"이루려는 목적", method:"선택한 방법", source:"참고한 출처", outcome:"적용 보고", opinion:"의견과 질문",correction:"반영된 수정"};
  const roles = {success:"성공 보고", partial:"부분 적용 보고", failure:"실패 보고", unknown:"판단 미정"};
  function html(tag, text, cls) { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; }
  function svg(tag, attrs = {}) { const n = document.createElementNS("http://www.w3.org/2000/svg", tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); return n; }
  function render(data, host) {
    const groups = {};
    data.nodes.forEach((n) => (groups[n.kind] ||= []).push(n));
    const positions = {situation:[125,120],goal:[125,350],method:[455,235],source:[785,80],outcome:[785,235],opinion:[785,390],correction:[1050,235]};
    const canvas = svg("svg", {viewBox:"0 0 1180 470", role:"group", "aria-label":"상황과 목적, 방법, 출처, 적용 보고와 의견의 연결 지도"});
    const info = html("div", null, "methods-graph-info"); info.setAttribute("aria-live", "polite");
    function inspect(kind) {
      info.replaceChildren(html("h4", names[kind]));
      groups[kind].forEach((n) => {
        const item = html("div", null, "methods-graph-entry");
        if (n.status) item.append(html("small", roles[n.status] || n.status));
        item.append(html("p", n.label));
        if (n.url) { try { const u = new URL(n.url); if (["http:","https:"].includes(u.protocol)) {
          const a = html("a", "원래 출처 읽기 ↗"); a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer"; item.append(a);
        } } catch (_) {} }
        if (n.method_version) item.append(html("small", `방법 버전 ${n.method_version} · ${kind==="correction"?"변경 기록, 개선 효과 미검증":"작성자 보고"}`));
        if(n.version)item.append(html("small",`v${n.version}${n.historical?" · 이전 버전":" · 현재 버전"}`));
        item.append(html("code", n.id)); info.append(item);
      });
      if (kind === "outcome" || kind === "opinion") info.append(html("p", "제출자의 기록입니다. 독립 검증이나 실제 효과를 보증하지 않습니다.", "methods-muted"));
    }
    const relations = [["method","situation"],["method","goal"],["method","source"],["method","outcome"],["method","opinion"],["method","correction"]];
    relations.forEach(([a,b]) => {
      if (!groups[a] || !groups[b]) return;
      const [x1,y1] = positions[a], [x2,y2] = positions[b];
      canvas.append(svg("path", {d:`M ${x1} ${y1} C ${(x1+x2)/2} ${y1}, ${(x1+x2)/2} ${y2}, ${x2} ${y2}`, class:"methods-graph-line"}));
    });
    if (data.edges.some((e)=>e.relation==="comments_on") && groups.outcome && groups.opinion) canvas.append(svg("path", {d:"M 785 270 L 785 355", class:"methods-graph-line methods-graph-line-comment"}));
    Object.keys(groups).forEach((kind) => {
      const pos=positions[kind];if(!pos)return;const [x,y]=pos;
      const g = svg("g", {transform:`translate(${x-110},${y-38})`, tabindex:"0", role:"button", "aria-label":`${names[kind]} ${groups[kind].length}개 읽기`, class:"methods-graph-node"+(kind==="method"?" methods-graph-focus":"")});
      const title = svg("title"); title.textContent = groups[kind].map(n=>n.label).join(" / "); g.append(title);
      g.append(svg("rect", {width:220,height:76,rx:12}));
      const label = svg("text", {x:14,y:25,class:"methods-graph-kind"}); label.textContent = names[kind] + (groups[kind].length>1?` · ${groups[kind].length}`:"");g.append(label);
      const text = svg("text", {x:14,y:51});const labelText = groups[kind][0].label;text.textContent = labelText.length>16?labelText.slice(0,16)+"…":labelText;g.append(text);
      g.addEventListener("click",()=>inspect(kind));g.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();inspect(kind);}});canvas.append(g);
    });
    const map = html("div", null, "methods-graph-map"); map.append(canvas);
    host.replaceChildren(map, html("p", "실선은 방법과 기록의 연결, 점선은 적용 보고에 달린 의견입니다. 노드를 눌러 읽어보세요. 작은 화면에서는 지도를 좌우로 움직일 수 있습니다.", "methods-meta"), info);
    if (data.truncated.outcomes || data.truncated.opinions) host.append(html("p", "연결이 많은 방법은 적용 보고·의견 각각 최대 12개를 지도에 표시합니다. 아래 원문 표시 범위와 다를 수 있습니다.", "methods-muted"));
    const full=html("a","전체 지도에서 이 노하우의 연결 탐색 ↗");full.href="/?method="+encodeURIComponent(data.method_id);host.append(full);
    if(data.truncated.revisions)host.append(html("p","일부 버전 이력만 지도에 표시합니다.","methods-muted"));
    inspect("method");
  }
  return {render};
})();
