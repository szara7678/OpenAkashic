"""Owner-keyed method revisions; public reads never initialize schema.

A correction declares a change to the recorded procedure, not proven improved
execution. Original versions and their outcome links remain immutable.
"""
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.research import require_research_key
from app.research_methods import MethodRequest, Text, idempotency_key, method_store, validate_public_text
from app.research_method_store import METADATA, MethodNotFound
from app.research_store import canonical, digest

router = APIRouter(prefix="/research/api/methods", tags=["owner method revisions"])


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome_id: Annotated[str, Field(min_length=1, max_length=100)]
    method_version: Annotated[int, Field(strict=True, ge=1)]
    reason: Text


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    method: MethodRequest
    reason: Text
    correction: Correction | None = None

    @model_validator(mode="after")
    def public_content(self):
        validate_public_text(self.model_dump(mode="json"))
        return self


class VersionConflict(ValueError):
    pass


def _has_revisions(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='method_revisions'").fetchone() is not None


def revisions(store, method_id, limit=100, offset=0):
    """Read snapshots if installed, otherwise expose the existing v1 unchanged."""
    with store.archive._connect() as db:
        current = db.execute("SELECT body FROM method_methods WHERE id=?", (method_id,)).fetchone()
        if current is None:
            raise MethodNotFound("Method not found")
        if not _has_revisions(db):
            items = [json.loads(current["body"])] if offset == 0 else []
            total = 1
        else:
            total = db.execute("SELECT count(*) FROM method_revisions WHERE method_id=?", (method_id,)).fetchone()[0]
            items = [json.loads(row["body"]) for row in db.execute(
                "SELECT body FROM method_revisions WHERE method_id=? ORDER BY version DESC LIMIT ? OFFSET ?",
                (method_id, limit, offset))]
            # Methods created after ledger initialization still have only current v1.
            if not total:
                total = 1
                items = [json.loads(current["body"])] if offset == 0 else []
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(items) < total}


def revise(store, method_id, payload, key):
    if store.read_only:
        raise ValueError("This public research process is read-only")
    data = payload.model_dump(mode="json")
    fingerprint = digest({"kind": "method_revision", "method_id": method_id, "payload": data})
    with store.archive._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT fingerprint,response FROM method_idempotency WHERE key=?", (key,)).fetchone()
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise VersionConflict("idempotency key request conflict")
            return json.loads(prior["response"])
        row = db.execute("SELECT body FROM method_methods WHERE id=?", (method_id,)).fetchone()
        if row is None:
            raise MethodNotFound("Method not found")
        current = json.loads(row["body"])
        if current["version"] != data["expected_version"]:
            raise VersionConflict("expected_version does not match the current method version")
        if data["correction"]:
            correction = data["correction"]
            outcome = db.execute("SELECT method_id,method_version FROM method_outcomes WHERE id=?",
                                 (correction["outcome_id"],)).fetchone()
            if outcome is None or outcome["method_id"] != method_id or outcome["method_version"] != correction["method_version"]:
                raise ValueError("correction outcome must belong to this method and exact recorded version")
        now = datetime.now(timezone.utc).isoformat()
        result = {**data["method"], **METADATA, "id": method_id,
                  "version": current["version"] + 1, "created_at": current["created_at"],
                  "updated_at": now,
                  "revision": {"previous_version": current["version"], "reason": data["reason"],
                               "correction": data["correction"],
                               "verification": "owner_reported_change_not_verified_improvement"}}
        db.execute("""CREATE TABLE IF NOT EXISTS method_revisions (
            method_id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(method_id, version))""")
        db.execute("INSERT OR IGNORE INTO method_revisions VALUES (?,?,?)",
                   (method_id, current["version"], canonical(current)))
        db.execute("INSERT INTO method_revisions VALUES (?,?,?)", (method_id, result["version"], canonical(result)))
        db.execute("UPDATE method_methods SET version=?,body=? WHERE id=?",
                   (result["version"], canonical(result), method_id))
        db.execute("INSERT INTO method_idempotency VALUES (?,?,?)", (key, fingerprint, canonical(result)))
    return result


@router.post("/{method_id}/revisions", status_code=201, dependencies=[Depends(require_research_key)])
def create_revision(method_id: str, payload: RevisionRequest, key: str = Depends(idempotency_key)):
    try:
        return revise(method_store(), method_id, payload, key)
    except MethodNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except VersionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{method_id}/revisions")
def list_revisions(method_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                   offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    try:
        return {"schema": "method-revisions-v1", "method_id": method_id,
                **revisions(method_store(), method_id, limit, offset)}
    except MethodNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{method_id}/versions/{version}")
def get_version(method_id: str, version: Annotated[int, Field(ge=1)]):
    store = method_store()
    with store.archive._connect() as db:
        if _has_revisions(db):
            row = db.execute("SELECT body FROM method_revisions WHERE method_id=? AND version=?",
                             (method_id, version)).fetchone()
            if row:
                return json.loads(row["body"])
        row = db.execute("SELECT body FROM method_methods WHERE id=? AND version=?", (method_id, version)).fetchone()
        if row:
            return json.loads(row["body"])
    raise HTTPException(404, "Method version not found")
