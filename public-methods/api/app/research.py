"""Public investigations: anonymous reads, authenticated bounded collection."""
import hashlib
import hmac
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.research_connectors import collect_github, collect_naver, collect_opendart, collect_wikidata, failed
from app.research_store import ResearchStore, canonical, canonical_agent_uri, digest, public_payload
from app.utils import normalize_text

router = APIRouter(prefix="/research", tags=["public research"])
WEB = Path(__file__).resolve().parents[2] / "web" / "research"
if not WEB.exists():
    WEB = Path(__file__).resolve().parents[2].parent / "web" / "research"


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)
    public_source_only: Literal[True]
    qid: str | None = Field(default=None, pattern=r"^Q[1-9][0-9]{0,11}$")
    github_repo: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
    corp_code: str | None = Field(default=None, pattern=r"^[0-9]{8}$")
    sources: list[Literal["wikidata", "github", "opendart", "naver_news"]] = Field(default_factory=lambda: ["wikidata", "github"], min_length=1, max_length=4)
    news_query: str | None = Field(default=None, min_length=2, max_length=100)

    @field_validator("question", "news_query")
    @classmethod
    def public_text_only(cls, value):
        if value is not None and not value.strip():
            raise ValueError("non-empty public text required")
        if value is not None and re.search(r"closed://|personal_vault|Bearer\s+\S+|sk-[A-Za-z0-9]{12,}|(?:api_key|access_token|client_secret)\s*[:=]", value, re.I):
            raise ValueError("private references or credentials are not public research input")
        return value.strip() if value else value

    @model_validator(mode="after")
    def subject_required(self):
        if not (self.qid or self.corp_code or self.github_repo):
            raise ValueError("an explicit public subject identifier is required")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("duplicate sources")
        if self.github_repo and any(p in {".", ".."} for p in self.github_repo.split("/")):
            raise ValueError("invalid repository")
        return self


class AgentSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=3, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]+$")
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=1000)
    external_ids: dict[str, str] = Field(max_length=20)

    @field_validator("external_ids")
    @classmethod
    def bounded_ids(cls, value):
        if any(not key.strip() or len(key) > 80 or not item.strip() or len(item) > 300 for key, item in value.items()):
            raise ValueError("bounded non-empty external identifiers required")
        return value


class AgentFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: str = Field(min_length=1, max_length=100)
    value: JsonValue
    quote: str = Field(min_length=1, max_length=3000)

    @field_validator("value")
    @classmethod
    def bounded_value(cls, value):
        if len(canonical(value)) > 2000:
            raise ValueError("fact value exceeds 2000 characters")
        return value


class AgentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_uri: str = Field(min_length=8, max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    observed_at: AwareDatetime
    source_time: AwareDatetime | None = None
    source_excerpt: str = Field(min_length=1, max_length=3000)
    facts: list[AgentFact] = Field(min_length=1, max_length=12)

    @field_validator("source_uri")
    @classmethod
    def public_https(cls, value):
        canonical_agent_uri(value)
        return value

    @model_validator(mode="after")
    def exact_quotes(self):
        for fact in self.facts:
            if not fact.quote.strip() or fact.quote not in self.source_excerpt:
                raise ValueError("quote must be a continuous exact substring of submitted source_excerpt")
        return self


class AgentInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_source_only: Literal[True]
    question: str = Field(min_length=3, max_length=500)
    subject: AgentSubject
    agent_name: str = Field(min_length=1, max_length=100)
    sources: list[AgentSource] = Field(min_length=1, max_length=8)
    unresolved: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def public_bounded_input(self):
        data = self.model_dump(mode="json")
        if any(len(item) > 500 for item in self.unresolved):
            raise ValueError("unresolved question exceeds 500 characters")
        public_payload(data)
        def check(value):
            if isinstance(value, str):
                InvestigationRequest.public_text_only(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    check(key)
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(data)
        uris = [canonical_agent_uri(source.source_uri) for source in self.sources]
        if len(set(uris)) != len(uris):
            raise ValueError("duplicate source URI")
        return self


def research_read_only():
    return os.getenv("OPENAKASHIC_RESEARCH_READ_ONLY") == "1"


def require_research_key(x_openakashic_key: str | None = Header(default=None)):
    if research_read_only():
        raise HTTPException(403, "This public research process is read-only")
    expected = os.getenv("OPENAKASHIC_RESEARCH_WRITE_KEY") or os.getenv("OPENAKASHIC_WRITE_API_KEY")
    if not expected:
        raise HTTPException(503, "Research collection is locked until an operator write key is configured")
    if not x_openakashic_key or not hmac.compare_digest(expected.encode(), x_openakashic_key.encode()):
        raise HTTPException(401, "Missing or invalid X-OpenAkashic-Key")


@lru_cache(maxsize=4)
def store_for_path(path, read_only=False):
    resolved = Path(path).expanduser().resolve()
    if resolved.is_relative_to(Path(__file__).resolve().parents[2]):
        raise RuntimeError("research data must be outside Git")
    return ResearchStore(resolved, read_only=read_only)


def get_store():
    return store_for_path(os.getenv("OPENAKASHIC_RESEARCH_DB", str(Path.home() / ".local/share/openakashic/public-research/research.sqlite3")), research_read_only())


def with_answer(record):
    if record is None:
        raise HTTPException(404, "Investigation not found")
    result = dict(record)
    summary = []
    captions = {"name": "Wikidata 이름", "description": "출처 설명", "latest_release": "GitHub 최신 정식 릴리스 조회값",
                "company_name": "공시 대상 회사명", "reported_ceo": "기업개황에 기재된 대표자", "reported_address": "기업개황에 기재된 주소"}
    for item in record.get("facts", []):
        predicate = item.get("predicate")
        if item.get("source_id", "").startswith("agent_web:"):
            value = item["value"]
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            summary.append("에이전트 보고 · " + predicate + ": " + rendered[:300])
        elif predicate in captions:
            value = item["value"]
            if isinstance(value, dict):
                value = value.get("ko") or value.get("en") or json.dumps(value, ensure_ascii=False)
            if value:
                summary.append(captions[predicate] + ": " + str(value))
    cautions = ["지정한 대상과 출처에서 만든 근거 묶음입니다. 자유 질문 전체를 추론해 검증한 답변은 아닙니다.",
                "출처의 진술·관측값과 세계 사실의 독립 검증은 구분합니다. 첫 관측은 실제 발생·변경 시각을 뜻하지 않습니다."]
    if any(s.get("source_id", "").startswith("agent_web:") for s in record.get("source_results", [])):
        cautions.append("에이전트가 제출한 공개 출처 보고입니다. 출처 원문·대상 동일성·사실은 독립 검증하지 않았습니다. 인용 검사는 제출된 발췌문 내부의 연속 일치만 확인합니다.")
    for source in record.get("source_results", []):
        if source["status"] not in {"saved", "unchanged"}:
            cautions.append(source["source_id"] + ": " + source.get("reason", source["status"]))
        if source["source_id"] == "naver_news" and source["status"] in {"saved", "unchanged"}:
            cautions.append("뉴스 검색 제목·요약·링크만 확인했습니다. 관련성 후보이며 기사 본문·대상 동일성·사실 확정이 아닙니다.")
    unresolved = list(dict.fromkeys(item for source in record.get("source_results", [])
                                   for item in source.get("coverage", {}).get("unresolved", [])))
    if unresolved:
        result["unresolved"] = unresolved
        cautions.extend("미해결: " + item for item in unresolved)
    result["answer"] = {"mode": "source_grounded_bundle", "summary": summary, "cautions": cautions}
    actual = [c for c in result.get("changes", []) if c.get("kind") != "initial_observation"]
    result["changes_summary"] = {"differences_since_previous_success": len(actual),
                                 "initial_observations": len(result.get("changes", [])) - len(actual)}
    return result


def _repo_links(wikidata):
    if wikidata.get("status") != "ok":
        return set()
    claims = wikidata["evidence"][0]["content"]["claims"]
    return {str(row["value"]).rstrip("/").removesuffix(".git").lower()
            for row in claims.get("P1324", []) if isinstance(row.get("value"), str)}


def execute_investigation(payload, idempotency_key=None, store=None):
    store = store or get_store()
    request_data = payload.model_dump()
    fingerprint = digest(request_data)
    if idempotency_key:
        with store._connect() as db:
            row = db.execute("SELECT body,fingerprint FROM research_investigations WHERE idem_key=?", (idempotency_key,)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise ValueError("idempotency key request conflict")
            return with_answer(json.loads(row["body"]))
    results = []
    wiki = None
    # Wikidata is also the explicit identity evidence for an associated repository.
    if payload.qid and ("wikidata" in payload.sources or "github" in payload.sources):
        wiki = collect_wikidata(payload.qid)
        # A cross-source identity decision must travel with its own evidence,
        # even when Wikidata was fetched as a dependency for GitHub only.
        results.append(wiki)
    elif "wikidata" in payload.sources:
        results.append(failed("wikidata", "qid-required", "qid_required", "not_found"))
    label, description = payload.qid or payload.corp_code or payload.github_repo, ""
    external_ids = {}
    if wiki and wiki.get("status") == "ok":
        content = wiki["evidence"][0]["content"]
        label = content["labels"].get("ko") or content["labels"].get("en") or label
        description = content["descriptions"].get("ko") or content["descriptions"].get("en") or ""
        external_ids["wikidata"] = payload.qid
    if "github" in payload.sources:
        links = _repo_links(wiki or {})
        repo = payload.github_repo
        if repo is None and len(links) == 1:
            parsed = urlsplit(next(iter(links)))
            if parsed.hostname == "github.com":
                repo = parsed.path.strip("/")
        if payload.qid and (not repo or ("https://github.com/" + repo.lower()) not in links):
            results.append(failed("github", "repository-identity", "repository_relation_unverified"))
        elif repo:
            github = collect_github(repo)
            results.append(github)
            if github["status"] == "ok":
                external_ids["github"] = github["evidence"][0]["content"]["full_name"]
                if not payload.qid and not payload.corp_code:
                    label = external_ids["github"]
                    description = github["evidence"][0]["content"].get("description") or ""
        else:
            results.append(failed("github", "repository-required", "github_repository_required", "not_found"))
    if "opendart" in payload.sources:
        dart = collect_opendart(payload.corp_code)
        # Keep unverified cross-source identity separate instead of merging names.
        if payload.qid and dart["status"] == "ok":
            dart = failed("opendart", dart["scope_key"], "collect_company_as_separate_subject_until_identity_reviewed")
        results.append(dart)
        if dart["status"] == "ok":
            external_ids["opendart"] = payload.corp_code
            label = dart["evidence"][0]["content"]["corp_name"]
    if "naver_news" in payload.sources:
        results.append(collect_naver(payload.news_query or label))
    subject_id = ("wikidata:" + payload.qid if payload.qid else "opendart:" + payload.corp_code if payload.corp_code else "github:" + payload.github_repo.lower())
    subject = {"id": subject_id, "label": label, "description": description, "external_ids": external_ids}
    record = store.save_investigation(payload.question, subject, results, idempotency_key, fingerprint)
    return with_answer(record)


def execute_agent_investigation(payload, idempotency_key, store=None):
    """Import a bounded agent capture. Never fetch a submitted source URL."""
    store = store or get_store()
    results = []
    for source in payload.sources:
        uri = canonical_agent_uri(source.source_uri)
        coverage = {"origin": "agent_reported", "independently_verified": False,
                    "source_authenticity_verified": False, "world_truth_verified": False,
                    "identity_assignment": "operator_supplied_not_independently_verified",
                    "quote_validation": "continuous_exact_match_in_submitted_excerpt",
                    "selected_excerpt_only": True}
        facts = [fact.model_dump(mode="json") for fact in source.facts]
        results.append({"source_id": "agent_web:" + urlsplit(uri).hostname,
                        "scope_key": "agent-source:" + digest(uri), "status": "ok",
                        "coverage": dict(coverage, unresolved=payload.unresolved),
                        "evidence": [{"external_id": uri, "source_uri": source.source_uri,
                                      "title": source.title, "agent_name": payload.agent_name,
                                      "source_observed_at": source.observed_at.isoformat(),
                                      "source_time": source.source_time.isoformat() if source.source_time else None,
                                      "excerpt": source.source_excerpt, "coverage": coverage,
                                      "content": {"origin": "agent_reported", "independently_verified": False,
                                                  "title": source.title,
                                                  "reported_facts": facts}}],
                        "facts": [dict(fact, evidence_external_id=uri, epistemic_state="source_observation",
                                       origin="agent_reported", independently_verified=False) for fact in facts]})
    subject = dict(payload.subject.model_dump(), identity_assignment="operator_supplied_not_independently_verified")
    record = store.save_investigation(payload.question, subject, results,
                                      idempotency_key, digest(payload.model_dump(mode="json")))
    return with_answer(record)


@router.post("/api/agent-investigations", dependencies=[Depends(require_research_key)])
def create_agent_investigation(payload: AgentInvestigationRequest, idempotency_key: str = Header(min_length=8, max_length=128)):
    try:
        return execute_agent_investigation(payload, idempotency_key)
    except ValueError as exc:
        conflict = "idempotency" in str(exc)
        raise HTTPException(409 if conflict else 422, "Idempotency conflict" if conflict else "Invalid public evidence payload") from None


@router.get("/health")
def health():
    store = get_store()
    with store._connect() as db:
        count = db.execute("SELECT count(*) FROM research_investigations").fetchone()[0]
    return {"status": "ok", "storage_readable": True, "investigations": count,
            "source_configuration": {"wikidata": True, "github_public": True,
                "opendart": bool(os.getenv("OPENDART_API_KEY") or os.getenv("DART_API_KEY")),
                "naver_news": bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))},
            "external_sources_verified_by_health": False}


@router.get("/api/subjects")
def subjects(q: str = Query(default="", max_length=100)):
    data = get_store().list_subjects()
    if q:
        data["subjects"] = [s for s in data["subjects"] if normalize_text(q) in normalize_text(json.dumps(s, ensure_ascii=False))]
    return data


@router.get("/api/subjects/{subject_id:path}")
def subject(subject_id: str):
    item = get_store().get_subject(subject_id)
    if item is None:
        raise HTTPException(404, "Subject not found")
    return item


@router.get("/api/investigations")
def investigations():
    data = get_store().list_investigations()
    data["investigations"] = [with_answer(item) for item in data["investigations"]]
    return data


@router.post("/api/investigations", dependencies=[Depends(require_research_key)])
def create_investigation(payload: InvestigationRequest, idempotency_key: str = Header(min_length=8, max_length=128)):
    try:
        return execute_investigation(payload, idempotency_key)
    except ValueError as exc:
        raise HTTPException(409 if "idempotency" in str(exc) else 422, "Idempotency conflict" if "idempotency" in str(exc) else "Invalid public evidence payload") from None


@router.get("/api/investigations/{investigation_id}/export")
def export_investigation(investigation_id: str):
    record = get_store().export(investigation_id)
    if record is None:
        raise HTTPException(404, "Investigation not found")
    record["investigation"] = with_answer(record["investigation"])
    return JSONResponse(record, headers={"Content-Disposition": 'attachment; filename="investigation.json"'})


@router.get("/api/investigations/{investigation_id}")
def investigation(investigation_id: str):
    return with_answer(get_store().get_investigation(investigation_id))


@router.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "methods-explore.html")


@router.get("/pilot", include_in_schema=False)
def pilot():
    return FileResponse(WEB / "pilot.html")


@router.get("/memory", include_in_schema=False)
@router.get("/memory/", include_in_schema=False)
def memory_space_reader():
    return FileResponse(WEB / "memory.html")


@router.get("/time", include_in_schema=False)
@router.get("/time/", include_in_schema=False)
def time_reader():
    return FileResponse(WEB / "time.html")


@router.get("/methods", include_in_schema=False)
@router.get("/methods/", include_in_schema=False)
def methods_reader():
    return FileResponse(WEB / "methods-explore.html")


@router.get("/methods/design-lab", include_in_schema=False)
@router.get("/methods/design-lab/", include_in_schema=False)
def methods_design_lab():
    return FileResponse(WEB / "design-lab" / "index.html")


@router.get("/methods/design-lab/results.json", include_in_schema=False)
def methods_design_report():
    # One deliberately reviewed public report beside the public archive. No
    # user-controlled path, directory listing, or raw experiment state exposure.
    archive = os.environ.get("OPENAKASHIC_RESEARCH_DB")
    report = Path(archive).parent / "method-design-lab-report.json" if archive else None
    if report is None or not report.is_file():
        raise HTTPException(404, "Reviewed public design report is not available")
    return FileResponse(report, headers={"Cache-Control": "no-store"})


@router.get("/methods/design-lab/{asset}", include_in_schema=False)
def methods_design_lab_asset(asset: Literal["lab.js", "lab.css"]):
    return FileResponse(WEB / "design-lab" / asset)


@router.get("/methods/design-lab/{condition}/{asset}", include_in_schema=False)
def methods_design_example(
    condition: Literal["unaided", "direct", "retrieval"],
    asset: Literal["exhibition.html", "exhibition.css", "exhibition.js",
                   "workshop.html", "workshop.css", "workshop.js"],
):
    return FileResponse(WEB / "design-lab" / condition / asset)


@router.get("/{asset}", include_in_schema=False)
def asset(asset: Literal["app.js", "style.css", "pilot.js", "memory.js", "memory.css", "time.js", "time.css", "methods.js", "methods.css", "methods-graph.js", "methods-kpi.html", "methods-kpi.js", "methods-explore.js", "methods-explore.css", "evidence-kpi-20261101.html"]):
    return FileResponse(WEB / asset)


@router.get("/methods/library/", include_in_schema=False)
def methods_library():
    return FileResponse(WEB / "methods.html")
