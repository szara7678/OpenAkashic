from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.fts_search import FTSDocument, lexical_rank  # noqa: E402
from app.site import _claim_trust_multiplier, _normalize_claim_review_status  # noqa: E402


class _FakeSettings:
    def __init__(self, fts_index_path: str):
        self.fts_index_path = fts_index_path


def test_sqlite_fts_lexical_rank_returns_hits(tmp_path, monkeypatch):
    db_path = tmp_path / "notes-fts.sqlite3"
    monkeypatch.setattr("app.fts_search.get_settings", lambda: _FakeSettings(str(db_path)))
    docs = [
        FTSDocument(
            path="doc/general/openakashic.md",
            slug="openakashic",
            title="OpenAkashic Search Notes",
            summary="FTS retrieval implementation note",
            kind="reference",
            project="openakashic",
            owner="alice",
            tags=["search", "fts"],
            body="SQLite FTS5 replaces substring scanning for lexical retrieval.",
        ),
        FTSDocument(
            path="doc/general/other.md",
            slug="other",
            title="Other Note",
            summary="unrelated",
            kind="reference",
            project="misc",
            owner="bob",
            tags=["misc"],
            body="Nothing about the target query here.",
        ),
    ]
    ranked = lexical_rank("sqlite lexical retrieval", docs, limit=5)
    assert "openakashic" in ranked
    assert ranked["openakashic"]["score"] > 0


def test_claim_review_status_prefers_dispute_and_publication_states():
    assert _normalize_claim_review_status({"publication_status": "superseded"}, kind="claim", confirm_count=3, dispute_count=0) == "superseded"
    assert _normalize_claim_review_status({"publication_status": "needs_merge"}, kind="claim", confirm_count=0, dispute_count=0) == "merged"
    assert _normalize_claim_review_status({}, kind="claim", confirm_count=0, dispute_count=2) == "disputed"
    assert _normalize_claim_review_status({}, kind="claim", confirm_count=2, dispute_count=0) == "confirmed"
    assert _normalize_claim_review_status({}, kind="reference", confirm_count=2, dispute_count=0) == "unreviewed"


def test_claim_trust_multiplier_penalizes_disputes_and_superseded():
    confirmed = _claim_trust_multiplier("confirmed", confirm_count=3, dispute_count=0)
    disputed = _claim_trust_multiplier("disputed", confirm_count=3, dispute_count=1)
    superseded = _claim_trust_multiplier("superseded", confirm_count=3, dispute_count=0)
    assert confirmed > 1.0
    assert disputed < confirmed
    assert superseded < disputed
