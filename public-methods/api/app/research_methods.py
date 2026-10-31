"""Situation/goal method exchange: anonymous reads, keyed idempotent writes."""
import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.research import InvestigationRequest, get_store, require_research_key
from app.research_method_store import MethodNotFound, MethodStore
from app.research_store import public_payload, public_uri

router = APIRouter(prefix="/research/api/methods", tags=["public methods"])
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Short = Annotated[str, Field(min_length=1, max_length=100)]


def validate_public_text(value):
    """Reuse the public gate and reject private locators without opening them."""
    public_payload(value)
    if isinstance(value, str):
        # Optional source quotations may be empty; field schemas still enforce
        # non-empty titles, steps, and other required content.
        if value == "":
            return value
        text = InvestigationRequest.public_text_only(value)
        if re.search(
            r"closed[-_]akashic|file://|(?:[A-Za-z]:[\\/](?:Users|Documents)[\\/])"
            r"|/(?:home|Users|mnt/c/Users)/|[\\/](?:personal_vault|private_notes?|raw_notes?)(?:[\\/]|\b)"
            r"|(?:password|passwd|refresh_token|authorization)\s*[:=]",
            text, re.I,
        ):
            raise ValueError("private paths, raw notes, or credentials are not public method content")
        for url in re.findall(r"https?://[^\s<>]+", text):
            public_uri(url.rstrip(".,;)"))
        return text
    if isinstance(value, dict):
        return {key: validate_public_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [validate_public_text(item) for item in value]
    return value


class PublicSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_source_only: Literal[True]
    agent_name: Short

    @model_validator(mode="after")
    def public_content(self):
        validate_public_text(self.model_dump(mode="json"))
        return self


ConstraintLabel = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\-]{0,49}$")]


class ConstraintRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requires: list[ConstraintLabel] = Field(default_factory=list, max_length=20)
    forbids: list[ConstraintLabel] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def no_contradiction(self):
        if set(self.requires) & set(self.forbids):
            raise ValueError("a method cannot require and forbid the same condition")
        return self


class MethodSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Annotated[str, Field(min_length=8, max_length=2000)]
    title: Annotated[str, Field(min_length=2, max_length=300)]
    accessed_at: datetime
    quote: Annotated[str, Field(max_length=250)] = ""

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        public_uri(value)
        return value

    @field_validator("accessed_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source access time requires a timezone")
        return value


class MethodRequest(PublicSubmission):
    title: Annotated[str, Field(min_length=2, max_length=200)]
    situation: Annotated[str, Field(min_length=2, max_length=1000)]
    goal: Annotated[str, Field(min_length=2, max_length=1000)]
    constraints: list[Text] = Field(max_length=20)
    steps: list[Text] = Field(min_length=1, max_length=30)
    success_criteria: list[Text] = Field(min_length=1, max_length=20)
    limitations: list[Text] = Field(min_length=1, max_length=20)
    tags: list[Short] = Field(default_factory=list, max_length=12)
    evidence_kind: Literal["documented_method", "executed_example", "contributor_method"] = "contributor_method"
    sources: list[MethodSource] = Field(default_factory=list, max_length=8)
    constraint_rules: ConstraintRules = Field(default_factory=ConstraintRules)

    @model_validator(mode="after")
    def documented_source_required(self):
        if self.evidence_kind == "documented_method" and not self.sources:
            raise ValueError("documented methods require at least one public source")
        return self


class ArtifactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]
    description: Annotated[str, Field(min_length=1, max_length=500)]


class OutcomeRequest(PublicSubmission):
    method_version: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["success", "partial", "failure", "unknown"]
    situation: Annotated[str, Field(min_length=2, max_length=1000)]
    goal: Annotated[str, Field(min_length=2, max_length=1000)]
    actions: list[Text] = Field(min_length=1, max_length=30)
    observed_result: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence: list[ArtifactEvidence] = Field(default_factory=list, max_length=12)


class OpinionRequest(PublicSubmission):
    method_version: Annotated[int, Field(strict=True, ge=1)]
    kind: Literal["question", "suggestion", "limitation", "alternative"]
    body: Annotated[str, Field(min_length=1, max_length=2000)]
    outcome_id: Annotated[str, Field(min_length=1, max_length=100)] | None = None


def method_store():
    try:
        return MethodStore(get_store())
    except RuntimeError as exc:
        raise HTTPException(503, "Public method schema is not initialized for this read-only archive") from exc


def idempotency_key(idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
    if not re.fullmatch(r"[!-~]{1,200}", idempotency_key):
        raise HTTPException(422, "Idempotency-Key must be 1-200 visible ASCII characters")
    return idempotency_key


def write(operation):
    try:
        return operation()
    except MethodNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409 if "idempotency" in str(exc) else 422, str(exc)) from exc


@router.post("", status_code=201, dependencies=[Depends(require_research_key)])
def create_method(payload: MethodRequest, key: str = Depends(idempotency_key)):
    data = payload.model_dump(mode="json")
    # Preserve fingerprints for pre-extension clients retrying an existing key.
    for name in ("evidence_kind", "sources", "constraint_rules"):
        if name not in payload.model_fields_set:
            data.pop(name, None)
    return write(lambda: method_store().create_method(data, key))


@router.get("/search")
def search_methods(
    situation: Annotated[str, Query(min_length=2, max_length=500)],
    goal: Annotated[str, Query(min_length=2, max_length=500)],
    constraints: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    mode: Literal["lexical", "semantic", "hybrid"] = "lexical",
    requires: Annotated[str, Query(max_length=500)] = "",
    forbids: Annotated[str, Query(max_length=500)] = "",
):
    try:
        situation, goal = validate_public_text(situation), validate_public_text(goal)
        constraints = validate_public_text(constraints) if constraints else ""
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    labels = []
    for value in (requires, forbids):
        entries = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
        if len(entries) > 20 or any(not re.fullmatch(r"[a-z][a-z0-9_\-]{0,49}", item) for item in entries):
            raise HTTPException(422, "conditions must be comma-separated lowercase labels")
        labels.append(entries)
    if set(labels[0]) & set(labels[1]):
        raise HTTPException(422, "a query cannot require and forbid the same condition")
    store = method_store()
    if mode == "lexical" and not any(labels):
        return store.search(situation, goal, constraints, limit)
    from app.research_method_search import search_methods as ranked_search
    return ranked_search(store, situation, goal, constraints, limit,
                         mode=mode, requires=labels[0], forbids=labels[1])


@router.get("/context")
def method_context(
    situation: Annotated[str, Query(min_length=2, max_length=500)],
    goal: Annotated[str, Query(min_length=2, max_length=500)],
    constraints: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=5)] = 3,
    mode: Literal["lexical", "semantic", "hybrid"] = "hybrid",
    requires: Annotated[str, Query(max_length=500)] = "",
    forbids: Annotated[str, Query(max_length=500)] = "",
    max_tokens: Annotated[int, Query(ge=256, le=2048)] = 1024,
):
    from app.research_method_context import pack_context
    result = search_methods(situation, goal, constraints, limit, mode, requires, forbids)
    return pack_context(result, max_tokens)


@router.get("/bundle")
def method_bundle(
    situation: Annotated[str, Query(min_length=2, max_length=500)],
    goal: Annotated[str, Query(min_length=2, max_length=500)],
    constraints: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=5)] = 3,
    mode: Literal["lexical", "semantic", "hybrid"] = "hybrid",
    requires: Annotated[str, Query(max_length=500)] = "",
    forbids: Annotated[str, Query(max_length=500)] = "",
    max_tokens: Annotated[int, Query(ge=256, le=4096)] = 1024,
):
    from app.research_method_context import pack_bundle
    result = search_methods(situation, goal, constraints, limit, mode, requires, forbids)
    return pack_bundle(result, max_tokens)


@router.get("/evidence")
def method_evidence(
    query: Annotated[str, Query(min_length=2, max_length=4000)],
    max_tokens: Annotated[int, Query(ge=1024, le=4096)] = 1024,
    mode: Literal["source", "method"] = "source",
):
    from app.research_method_evidence import evidence_packet
    return evidence_packet(query, max_tokens, mode,
                           store=method_store() if mode == "method" else None)


@router.get("/catalog")
def method_catalog(
    domain: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=24)] = 12,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    from app.research_method_graph import catalog
    try:
        return catalog(method_store(), validate_public_text(domain) if domain else "", limit, offset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{method_id}/graph")
def get_method_graph(method_id: Annotated[str, Field(min_length=1, max_length=100)]):
    from app.research_method_graph import method_graph
    try:
        return method_graph(method_store().get(method_id))
    except MethodNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/network")
def method_network(domain: Annotated[str, Query(max_length=100)] = "", limit: Annotated[int, Query(ge=1, le=100)] = 80, focus: Annotated[str, Query(max_length=100, pattern=r"^[A-Za-z0-9_:\-]*$")] = "", depth: Annotated[int, Query(ge=1, le=2)] = 1):
    from app.research_method_graph import network_graph
    try:
        validate_public_text(domain)
        return network_graph(method_store(), domain, limit, focus, depth)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/evaluation/report")
def method_evaluation_report():
    from pathlib import Path
    from fastapi.responses import FileResponse
    report = Path(method_store().db_path).parent / "method-kpi.json"
    if not report.is_file() or report.stat().st_size > 4 * 1024 * 1024:
        raise HTTPException(404, "Reviewed public method evaluation is not available")
    return FileResponse(report, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/{method_id}")
def get_method(method_id: Annotated[str, Field(min_length=1, max_length=100)]):
    try:
        return method_store().get(method_id)
    except MethodNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{method_id}/outcomes", status_code=201, dependencies=[Depends(require_research_key)])
def add_outcome(method_id: str, payload: OutcomeRequest, key: str = Depends(idempotency_key)):
    return write(lambda: method_store().add_outcome(method_id, payload.model_dump(mode="json"), key))


@router.post("/{method_id}/opinions", status_code=201, dependencies=[Depends(require_research_key)])
def add_opinion(method_id: str, payload: OpinionRequest, key: str = Depends(idempotency_key)):
    return write(lambda: method_store().add_opinion(method_id, payload.model_dump(mode="json"), key))
