from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


ClaimStatus = Literal["pending", "accepted", "rejected"]
ClaimRole = Literal["core", "support", "caution", "conflict", "example"]


class MentionInput(BaseModel):
    mention_text: str
    role: str | None = None
    entity_id: UUID | None = None


class ClaimCreate(BaseModel):
    text: str = Field(min_length=1)
    status: ClaimStatus = "accepted"
    confidence: float = Field(default=0.5, ge=0, le=1)
    source_weight: float = Field(default=0.5, ge=0, le=1)
    claim_role: ClaimRole = "support"
    metadata: dict[str, Any] = Field(default_factory=dict)
    mentions: list[MentionInput] = Field(default_factory=list)


class ClaimUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    status: ClaimStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_weight: float | None = Field(default=None, ge=0, le=1)
    claim_role: ClaimRole | None = None
    metadata: dict[str, Any] | None = None


class ClaimStatusUpdate(BaseModel):
    status: ClaimStatus


class EvidenceCreate(BaseModel):
    claim_id: UUID
    source_type: str = Field(min_length=1)
    source_uri: str | None = None
    excerpt: str | None = None
    hash: str | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapsulePoint(BaseModel):
    text: str
    claim_id: UUID | None = None


class CapsuleCreate(BaseModel):
    title: str = Field(min_length=1)
    summary: list[str] = Field(default_factory=list)
    key_points: list[CapsulePoint] = Field(default_factory=list)
    cautions: list[CapsulePoint] = Field(default_factory=list)
    source_claim_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityCreate(BaseModel):
    entity_key: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    entity_type: str = "concept"
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryFilters(BaseModel):
    status: list[ClaimStatus] = Field(default_factory=lambda: ["accepted"])


class QueryOptions(BaseModel):
    expand_mentions: bool = True
    expand_related_claims: bool = True


QueryMode = Literal["compact", "standard", "full"]


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    include: list[Literal["claims", "evidences", "evidence", "capsules"]] = Field(
        default_factory=lambda: ["capsules", "claims"]
    )
    mode: QueryMode = "standard"
    fields: list[str] = Field(default_factory=list)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    options: QueryOptions = Field(default_factory=QueryOptions)
