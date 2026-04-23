from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.fts_search import FTSDocument, lexical_rank  # noqa: E402
from app import mcp_server  # noqa: E402
from app import subordinate  # noqa: E402
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


def test_detect_akashic_quality_issue_flags_claim_only_weak_results():
    response = {
        "results": {
            "claims": [
                {"text": "claim a", "score": 0.19, "claim_review_status": "unreviewed"},
                {"text": "claim b", "score": 0.18, "claim_review_status": "unreviewed"},
            ],
            "capsules": [],
        },
        "meta": {"has_conflict": False},
    }
    reasons = mcp_server._detect_akashic_quality_issues(
        query="busagwan sagwan 역할 차이",
        response=response,
        include=None,
    )
    assert "no_capsule_hits" in reasons
    assert "claim_only_results" in reasons
    assert "weak_claim_match" in reasons
    assert "claim_only_unreviewed" in reasons


def test_analyze_search_quality_signals_creates_improvement_request(tmp_path, monkeypatch):
    signal_path = tmp_path / "search-quality-signals.jsonl"
    signal_path.write_text(
        (
            '{"ts":"2026-04-23T00:00:00Z","tool":"search_akashic","query":"Busagwan Sagwan 역할 차이",'
            '"reasons":["no_capsule_hits","claim_only_results"],"counts":{"claims":3,"capsules":0},'
            '"top_claim":{"text":"claim a","score":0.19,"confidence":0.9,"claim_review_status":"unreviewed"},'
            '"top_capsule":{},"meta":{"has_conflict":false}}\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.mcp_server.search_quality_signals_path", lambda: signal_path)
    monkeypatch.setattr("app.subordinate.list_note_paths", lambda: [])
    monkeypatch.setattr("app.subordinate._remember_subordinate_note", lambda *args, **kwargs: None)
    created: dict[str, dict[str, object]] = {}

    def _fake_write_document(*, path, body, metadata, **kwargs):
        created[path] = {"body": body, "metadata": metadata}
        return None

    monkeypatch.setattr("app.subordinate.write_document", _fake_write_document)

    summary = subordinate._analyze_search_quality_signals(max_new=5)

    assert summary == "analyze_search_quality_signals: 1 new, 0 updated"
    assert signal_path.read_text(encoding="utf-8") == ""
    assert len(created) == 1
    created_path = next(iter(created.keys()))
    created_note = created[created_path]
    assert created_path.startswith("personal_vault/meta/improvement-requests/search-quality-")
    assert "Repeated low-quality public search result" in str(created_note["body"])
    assert "search-quality" in list(created_note["metadata"]["tags"])
