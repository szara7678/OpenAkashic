"use strict";
(() => {
  const base = "/research/api/methods";
  function setTheme(value) {
    document.documentElement.dataset.theme=value;
    const b=document.getElementById("methods-theme");
    if(b){b.textContent=value==="light"?"☾ 어둡게":"☼ 밝게";b.setAttribute("aria-label",value==="light"?"어두운 테마로 전환":"밝은 테마로 전환");}
    try{localStorage.setItem("openakashic-graph-theme",value);}catch(_){}
  }
  try{setTheme(localStorage.getItem("openakashic-graph-theme")==="light"?"light":"dark");}catch(_){setTheme("dark");}
  document.getElementById("methods-theme")?.addEventListener("click",()=>setTheme(document.documentElement.dataset.theme==="light"?"dark":"light"));
  const el = (id) => document.getElementById(id);
  const form = el("methods-search");
  const list = el("methods-list");
  const detail = el("methods-detail");
  const content = el("methods-detail-content");
  const status = el("methods-status");
  let searchRequest = 0;
  let detailRequest = 0;
  let selectedId = "";
  let catalogOffset = 0;
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined && text !== null) item.textContent = String(text);
    if (className) item.className = className;
    return item;
  };
  const values = (value) => Array.isArray(value) ? value : [];
  const date = (value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "날짜 미상" : parsed.toLocaleString("ko-KR");
  };
  const meta = (item) => node("p", `작성자 ${item.agent_name || "이름 미표시"} · 자기 표시 · ${date(item.created_at)}`, "methods-meta");
  const evidenceLabel = (item) => ({documented_method: "문서에서 정리한 방법", executed_example: "실행 예제 · 제출자 보고", contributor_method: "제출자 방법"}[item.evidence_kind] || (values(item.tags).includes("mvp-e2e-demo") ? "공개 예제" : "출처 유형 미표시"));
  const exclusions = () => [["network", "methods-offline"], ["paid_service", "methods-no-paid"], ["filesystem_write", "methods-no-write"]].filter(([,id]) => el(id).checked).map(([tag]) => tag).join(",");
  function message(target, text, retry) {
    const box = node("div", text, retry ? "methods-error" : "methods-empty");
    if (retry) {
      const button = node("button", "다시 불러오기");
      button.type = "button";
      button.addEventListener("click", retry);
      box.append(button);
    }
    target.replaceChildren(box);
  }
  function scopeDomains(data) {
    el("methods-search-domains").replaceChildren(...values(data.domains).map((domain) => {
      const option = node("option"); option.value = domain.name; return option;
    }));
  }
  async function get(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" }, credentials: "omit" });
    if (!response.ok) {
      const error = new Error("request_failed");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  function urlState(method) {
    const url = new URL(window.location.href);
    for (const [name, value] of [["situation", el("methods-situation").value.trim()], ["goal", el("methods-purpose").value.trim()], ["constraints", el("methods-condition").value.trim()], ["mode", el("methods-mode").value], ["forbids", exclusions()], ["domain", el("methods-search-domain").value.trim()], ["product", el("methods-product").value.trim()], ["method", method]]) {
      if (value) url.searchParams.set(name, value);
      else url.searchParams.delete(name);
    }
    history.replaceState(null, "", url);
    return url;
  }
  function block(title, items, ordered = false) {
    const section = node("section", null, "methods-block");
    section.append(node("h3", title));
    const entries = values(items);
    if (!entries.length) section.append(node("p", "등록된 내용이 없습니다.", "methods-muted"));
    else {
      const textList = node(ordered ? "ol" : "ul");
      entries.forEach((text) => textList.append(node("li", text)));
      section.append(textList);
    }
    return section;
  }
  function opinion(item, reply) {
    const article = node("article", null, "methods-thread" + (reply ? " methods-reply" : ""));
    const kinds = { question: "질문", suggestion: "제안", limitation: "한계", alternative: "대안" };
    article.append(node("span", "의견 · " + (kinds[item.kind] || "의견"), "methods-badge methods-opinion-badge"), meta(item), node("p", item.body, "methods-body"));
    return article;
  }
  function outcome(item, opinions) {
    const article = node("article", null, "methods-thread");
    const names = { success: "성공", partial: "부분 성공", failure: "실패", unknown: "판단 미정" };
    article.append(node("span", "실행자 보고 · " + (names[item.status] || "판단 미정"), "methods-badge methods-outcome-badge"), meta(item));
    article.append(node("p", `참조 버전 ${item.method_version}`, "methods-meta"));
    if (item.situation) article.append(node("h4", "적용한 상황"), node("p", item.situation, "methods-body"));
    if (item.goal) article.append(node("h4", "목적"), node("p", item.goal, "methods-body"));
    if (values(item.actions).length) {
      article.append(node("h4", "실제로 한 일"));
      const actions = node("ol");
      item.actions.forEach((text) => actions.append(node("li", text)));
      article.append(actions);
    }
    article.append(node("h4", "관찰한 결과"), node("p", item.observed_result, "methods-body"));
    if (values(item.evidence).length) {
      const evidence = node("details");
      evidence.append(node("summary", "실행자가 남긴 근거 설명"));
      item.evidence.forEach((entry) => evidence.append(node("p", entry.description, "methods-body"), node("p", "SHA-256: " + entry.sha256, "methods-meta")));
      evidence.append(node("p", "근거 설명과 해시는 제출자 보고입니다. 원본이나 결과를 독립 검증한 표시는 아닙니다.", "methods-muted"));
      article.append(evidence);
    }
    opinions.filter((entry) => entry.outcome_id === item.id).forEach((entry) => article.append(opinion(entry, true)));
    return article;
  }
  function threadHeading(title, count, returned) {
    const section = node("section", null, "methods-block");
    section.append(node("h3", title));
    if (count && count.truncated) section.append(node("p", `전체 ${count.total}건 중 ${count.returned}건을 표시합니다.`, "methods-muted"));
    if (!returned) section.append(node("p", "아직 등록된 기록이 없습니다.", "methods-muted"));
    return section;
  }
  function renderDetail(method) {
    el("methods-detail-title").textContent = "선택한 방법";
    const top = node("div", null, "methods-detail-top");
    top.append(node("span", `버전 ${method.version} · 공개 방법`, "methods-badge"));
    const link = node("a", "이 방법의 고유 링크 ↗");
    link.href = urlState(method.id).href;
    top.append(link);
    content.replaceChildren(top, node("h3", method.title, "methods-detail-title"), meta(method));
    content.append(node("p", `방법 ID · ${method.id}`, "methods-meta"));
    content.append(node("p", evidenceLabel(method), "methods-badge"));
    const graph = node("section", null, "methods-graph");
    graph.append(node("h3", "방법의 연결 지도"), node("p", "연결을 누르면 출처와 기록을 읽을 수 있습니다. 사실이나 효과가 검증됐다는 뜻은 아닙니다.", "methods-muted"));
    const graphBody = node("div", "연결을 불러오는 중입니다.");
    graph.append(graphBody); content.append(graph);
    get(base + "/" + encodeURIComponent(method.id) + "/graph").then((data) => {
      if (selectedId === method.id && graphBody.isConnected) window.OpenAkashicMethodGraph.render(data, graphBody);
    }).catch(() => { if (graphBody.isConnected) message(graphBody, "연결 지도를 불러오지 못했습니다. 방법의 원문과 기록은 아래에서 읽을 수 있습니다."); });
    if (method.evidence_kind === "documented_method") content.append(node("p", "공개 출처의 절차를 정리한 방법입니다. 편집자가 정한 적용 조건과 평가 기준도 포함합니다. 아래 적용 결과가 없으면 실제 수행은 아직 확인되지 않았습니다.", "methods-muted"));
    content.append(block("어떤 상황에서 쓰나요?", [method.situation]), block("이루려는 목적", [method.goal]), block("적용 조건", method.constraints), block("실행 절차", method.steps, true), block("성공 기준", method.success_criteria), block("한계와 주의점", method.limitations));
    if (values(method.sources).length) {
      const sources = node("section", null, "methods-block");
      sources.append(node("h3", "정리할 때 참고한 출처"));
      method.sources.forEach((source) => {
        try {
          const url = new URL(source.url);
          if (!["https:", "http:"].includes(url.protocol)) return;
          const link = node("a", source.title || url.hostname);
          link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
          const row = node("p"); row.append(link); sources.append(row);
          sources.append(node("p", `확인 시각 ${date(source.accessed_at)}`, "methods-meta"));
        } catch (_) { /* Invalid locators are never turned into links. */ }
      });
      content.append(sources);
    }
    const outcomes = values(method.outcomes), opinions = values(method.opinions);
    const counts = method.feedback_counts || {};
    const results = threadHeading("적용 결과 · 실행자 보고", counts.outcomes, outcomes.length);
    results.append(node("p", "실행자가 자신의 적용 과정과 결과를 보고한 기록입니다.", "methods-muted"));
    outcomes.forEach((item) => results.append(outcome(item, opinions)));
    content.append(results);
    const visibleOutcomeIds = new Set(outcomes.map((item) => item.id));
    const general = opinions.filter((item) => !item.outcome_id || !visibleOutcomeIds.has(item.outcome_id));
    const discussion = threadHeading("의견과 질문", counts.opinions, opinions.length);
    if (opinions.length && !general.length) discussion.append(node("p", "의견은 위의 해당 실행 결과 아래에 표시되어 있습니다.", "methods-muted"));
    general.forEach((item) => {
      const article = opinion(item, false);
      if (item.outcome_id) article.prepend(node("p", `실행 결과 ${item.outcome_id}에 대한 의견 · 해당 결과는 현재 표시 범위에 없습니다.`, "methods-meta"));
      discussion.append(article);
    });
    content.append(discussion);
    if(method.revision){
      const revision=block("반영된 버전 변경",[method.revision.reason]);
      revision.append(node("p",`v${method.revision.previous_version} → v${method.version}`,"methods-meta"));
      if(method.revision.correction) revision.append(node("p",method.revision.correction.reason),node("p","연결된 적용 보고를 참고해 반영한 변경입니다. 개선 효과는 별도의 적용 보고로 확인해야 합니다.","methods-muted"));
      content.append(revision);
    }
    const openGraph=node("a","이 방법의 상황 · 결과 · 수정 연결 살펴보기 ↗");
    openGraph.href="/?method="+encodeURIComponent(method.id);content.append(openGraph);
  }
  async function select(id, focus = false) {
    const request = ++detailRequest;
    selectedId = id;
    urlState(id);
    for (const card of list.children) card.setAttribute("aria-current", String(card.dataset.methodId === id));
    detail.setAttribute("aria-busy", "true");
    el("methods-detail-title").textContent = "방법을 불러오는 중";
    message(content, "절차와 적용 경험을 불러오는 중입니다.");
    if (focus) {
      detail.setAttribute("tabindex", "-1");
      detail.focus({ preventScroll: true });
      if (window.matchMedia("(max-width: 640px)").matches) detail.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try {
      const method = await get(base + "/" + encodeURIComponent(id));
      if (request !== detailRequest) return;
      renderDetail(method);
    } catch (error) {
      if (request !== detailRequest) return;
      el("methods-detail-title").textContent = "방법을 열 수 없습니다";
      message(content, error.status === 404 ? "이 ID의 공개 방법을 찾을 수 없습니다. 링크를 확인하거나 다른 방법을 검색해 주세요." : "방법을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.", () => select(id));
    } finally {
      if (request === detailRequest) detail.setAttribute("aria-busy", "false");
    }
  }
  async function search() {
    const situation = el("methods-situation").value.trim(), goal = el("methods-purpose").value.trim();
    if (situation.length < 2 || goal.length < 2) {
      status.textContent = "상황과 목적을 각각 두 글자 이상 입력해 주세요.";
      (situation.length < 2 ? el("methods-situation") : el("methods-purpose")).focus();
      return;
    }
    const request = ++searchRequest;
    el("methods-more").hidden = true;
    el("methods-results-title").textContent = "상황과 목적에 맞는 후보";
    urlState(selectedId);
    list.setAttribute("aria-busy", "true");
    status.textContent = "상황과 목적에 맞는 방법을 찾고 있습니다.";
    message(list, "관련된 공개 방법을 찾는 중입니다.");
    const params = new URLSearchParams({ situation, goal, constraints: el("methods-condition").value.trim(), mode: el("methods-mode").value, forbids: exclusions(), domain: el("methods-search-domain").value.trim(), product: el("methods-product").value.trim(), limit: "20" });
    try {
      const data = await get(base + "/search?" + params);
      if (request !== searchRequest) return;
      const results = values(data.results);
      status.textContent = results.length ? `관련 방법 ${results.length}개를 표시합니다. 적용 조건을 읽고 선택해 주세요.` : "현재 조건에 맞는 방법이 없습니다.";
      if (data.search && data.search.available === false) status.textContent = "의미 검색을 사용할 수 없습니다. 같은 단어로 찾기를 선택하거나 잠시 후 다시 시도해 주세요.";
      else if (data.search?.stale_or_missing_methods) status.textContent += ` 아직 의미 색인에 반영되지 않은 방법 ${data.search.stale_or_missing_methods}개가 있습니다.`;
      if (data.search?.available) status.textContent += " 의미가 비슷해도 대상 도구나 서비스가 다를 수 있습니다. 적용 범위를 확인하세요.";
      list.replaceChildren();
      if (!results.length) message(list, data.search?.available === false ? "의미 검색 준비 상태를 확인하지 못했습니다. 검색 방식을 ‘같은 단어로 찾기’로 바꾸거나 나중에 다시 시도해 주세요." : "상황과 목적의 표현을 바꾸거나 선택 조건을 줄여 보세요. 관련 기록이 아직 없을 수도 있습니다.");
      for (const entry of results) {
        const method = entry.method;
        const card = node("article", null, "methods-card");
        card.dataset.methodId = method.id;
        card.setAttribute("aria-current", String(method.id === selectedId));
        const title = node("h3");
        const button = node("button", method.title, "methods-card-link");
        button.type = "button";
        button.addEventListener("click", () => select(method.id, true));
        title.append(button);
        card.append(node("span", `버전 ${method.version}`, "methods-badge"), title, node("p", method.goal), node("p", method.situation, "methods-muted"), meta(method));
        card.append(node("span", evidenceLabel(method), "methods-badge"));
        if (entry.match?.feedback) {
          const feedback = values(entry.match.feedback);
          const outcomes = feedback.filter((x) => x.kind === "outcome"), opinions = feedback.filter((x) => x.kind === "opinion");
          if (outcomes.length || opinions.length) card.append(node("p", `관련 적용 보고 ${outcomes.length}건 · 의견 ${opinions.length}건 — 방법을 열어 확인하세요.`, "methods-meta"));
        }
        const tags = node("div", null, "methods-tags");
        values(method.tags).forEach((tag) => tags.append(node("span", tag, "methods-badge")));
        card.append(tags);
        if (params.get("constraints")) card.append(node("p", entry.match?.constraints?.status === "lexical_overlap" ? "선택 조건과 겹치는 표현이 있습니다. 실제 충족 여부는 방법에서 확인하세요." : "선택 조건의 충족 여부를 확인해 주세요.", "methods-meta"));
        if (params.get("forbids") && entry.match?.constraint_rules?.status === "unknown") card.append(node("p", "체크한 조건의 정보가 충분하지 않습니다. 적용 전에 확인해 주세요.", "methods-meta"));
        list.append(card);
      }
    } catch (error) {
      if (request !== searchRequest) return;
      status.textContent = "검색을 완료하지 못했습니다.";
      message(list, error.status === 422 ? "검색 입력을 확인해 주세요. 상황·목적은 각각 2~500자, 선택 조건은 500자 이내로 입력할 수 있습니다." : "검색 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", search);
    } finally {
      if (request === searchRequest) list.setAttribute("aria-busy", "false");
    }
  }
  async function browse(more = false) {
    const request = ++searchRequest;
    if (!more) { catalogOffset = 0; list.replaceChildren(); }
    list.setAttribute("aria-busy", "true");
    el("methods-more").disabled = true;
    el("methods-results-title").textContent = "공개 방법 둘러보기";
    try {
      const params = new URLSearchParams({domain: el("methods-domain").value, limit: "12", offset: String(catalogOffset)});
      const data = await get(base + "/catalog?" + params);
      if (request !== searchRequest) return;
      const counts = data.counts;
      scopeDomains(data);
      if (!new URLSearchParams(location.search).has("mode") && !data.search_capabilities?.semantic_configured) el("methods-mode").value = "lexical";
      el("methods-library-stats").replaceChildren(...[["방법", counts.methods], ["적용 보고", counts.outcomes], ["의견", counts.opinions]].map(([label, count]) => {
        const span = node("span"); span.append(node("strong", count), document.createTextNode(" " + label)); return span;
      }), node("small", "기록 수이며 효과·성공률을 뜻하지 않습니다."));
      if (el("methods-domain").options.length === 1) data.domains.forEach((domain) => {
        const option = node("option", `${domain.name} · ${domain.count}`); option.value = domain.name; el("methods-domain").append(option);
      });
      for (const item of data.items) {
        const card = node("article", null, "methods-card"); card.dataset.methodId = item.id;
        card.setAttribute("aria-current", String(item.id === selectedId));
        card.append(node("span", item.domain, "methods-badge"));
        const heading = node("h3"), button = node("button", item.title, "methods-card-link"); button.type = "button";
        button.addEventListener("click", () => select(item.id, true)); heading.append(button);
        card.append(heading, node("p", item.goal), node("p", `출처 ${item.source_count} · 적용 보고 ${item.feedback_counts.outcomes} · 의견 ${item.feedback_counts.opinions}`, "methods-meta"));
        list.append(card);
      }
      catalogOffset += data.items.length;
      status.textContent = `${data.total}개 중 ${catalogOffset}개를 표시합니다. 분야로 둘러보거나 위에서 상황과 목적을 검색하세요.`;
      if (!data.items.length && !more) message(list, "이 분야에 등록된 방법이 없습니다.");
      el("methods-more").hidden = !data.has_more;
      if (!selectedId && data.items.length) select(data.items[0].id);
    } catch (_) { if (request === searchRequest) message(list, "목록을 불러오지 못했습니다.", () => browse(false)); }
    finally { if (request === searchRequest) { list.setAttribute("aria-busy", "false"); el("methods-more").disabled = false; } }
  }
  el("methods-domain").addEventListener("change", () => browse(false));
  el("methods-browse-all").addEventListener("click", () => browse(false));
  el("methods-more").addEventListener("click", () => browse(true));
  form.addEventListener("submit", (event) => { event.preventDefault(); search(); });
  const examples = {
    design: ["전시 소개 페이지가 흔한 템플릿으로 보이고 관람 안내를 찾기 어렵다", "전시의 분위기를 살리면서 관객이 날짜와 장소를 쉽게 찾게 한다"],
    career: ["일을 그만두고 다른 분야에 도전할지 고민인데 나에게 맞는지 모르겠다", "큰 결정을 하기 전에 부담 적은 방식으로 직무를 경험해 판단한다"],
    product: ["새 서비스 아이디어에 사람들이 좋다고는 하지만 실제 행동은 관찰하지 않았다", "만들기 전에 실패할 수 있는 가설과 측정 기준을 정해 시험한다"],
    learning: ["책을 읽으면 아는 것 같은데 책을 덮으면 설명이 안 된다", "내용을 안 보고 떠올린 다음 빠진 부분을 확인한다"],
    team: ["여러 부서가 회의만 하고 최종 결론을 내릴 사람이 불분명하다", "누가 추진하고 최종 결정하며 자문하고 공유받는지 정한다"],
    writing: ["웹 소개나 안내문이 길고 과장되어 독자가 필요한 정보를 찾기 어렵다", "문장을 간결하고 훑어보기 쉽게 고쳐 독자의 정보 찾기를 돕는다"],
    negotiation: ["견적이나 연봉 협상을 앞두고 합의하지 못하면 선택할 수 있는 대안을 정리하지 않았다", "실행 가능한 최선의 대안을 평가해 협상 준비의 기준으로 삼는다"],
    finance: ["펀드를 여러 개 샀지만 어떤 위험을 감당하고 언제 돈이 필요한지 정하지 않았다", "사용 기간과 위험 및 겹치는 투자 집중을 점검할 질문을 만든다"],
    opensource: ["유행하는 패키지를 추가할지 고민인데 실제 유지 비용이나 사용 조건을 모른다", "필요성 유지보수 보안 라이선스를 확인해 도입 여부를 검토한다"],
    form: ["휴대폰 예약 폼에 익숙하지 않은 사람이 이메일과 인원을 잘못 입력한다", "입력 오류를 고치고 내용을 확인 수정한 뒤 모의 예약을 마친다"],
    tables: ["서로 다른 기관의 데이터셋을 결합하려는데 키 중복과 누락이 있다", "조인 전 키의 유일성과 대응률을 계산해 결합 방식을 정한다"],
    documents: ["정책 보고서의 개정본이 이전 승인본과 어떻게 달라졌는지 검토해야 한다", "두 문서의 변경점을 비교하고 중요한 차이를 확인한다"],
    backup: ["SQLite 데이터베이스를 다른 파일로 백업하려고 한다", "온라인 백업을 만든 뒤 무결성과 원본 행 일치를 검증한다"],
  };
  document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
    const input = examples[button.dataset.example];
    if (!input) return;
    el("methods-situation").value = input[0]; el("methods-purpose").value = input[1];
    search();
  }));
  const params = new URLSearchParams(location.search);
  el("methods-situation").value = (params.get("situation") || "").slice(0, 500);
  el("methods-purpose").value = (params.get("goal") || "").slice(0, 500);
  el("methods-condition").value = (params.get("constraints") || "").slice(0, 500);
  el("methods-mode").value = ["lexical", "semantic", "hybrid"].includes(params.get("mode")) ? params.get("mode") : "hybrid";
  el("methods-search-domain").value = params.get("domain") || "";
  el("methods-product").value = params.get("product") || "";
  const forbidden = (params.get("forbids") || "").split(",");
  for (const [tag, id] of [["network", "methods-offline"], ["paid_service", "methods-no-paid"], ["filesystem_write", "methods-no-write"]]) el(id).checked = forbidden.includes(tag);
  list.setAttribute("aria-busy", "false");
  status.textContent = "상황과 목적을 입력하면 관련된 공개 방법을 찾을 수 있습니다.";
  message(list, "지금 상황과 이루려는 목적을 각각 두 글자 이상 입력해 주세요. 선택 조건은 비워 두어도 됩니다.");
  if (params.get("method")) select(params.get("method"));
  if (el("methods-situation").value.trim().length >= 2 && el("methods-purpose").value.trim().length >= 2) {
    search();
    get(base + "/catalog?limit=1").then((data) => { scopeDomains(data); el("methods-library-stats").textContent = `${data.counts.methods}개 방법 · ${data.counts.outcomes}개 적용 보고 · ${data.counts.opinions}개 의견 · 기록 수이며 효과 지표는 아닙니다.`; }).catch(() => {});
  } else browse(false);
})();
