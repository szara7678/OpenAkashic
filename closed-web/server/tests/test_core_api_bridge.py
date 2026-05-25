"""core_api_bridge edge case 테스트.

네트워크를 실제로 호출하지 않도록 `_core_api_post`를 monkeypatch한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import core_api_bridge as bridge  # noqa: E402


# ─── confidence 파싱 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("high", 0.9),
        ("HIGH", 0.9),
        ("medium", 0.7),
        ("med", 0.7),
        ("low", 0.5),
        (0.42, 0.42),
        ("0.33", 0.33),
        (None, 0.75),
        ("", 0.75),
        ("garbage", 0.75),
        (2.0, 1.0),  # clamp
        (-1.0, 0.0),  # clamp
    ],
)
def test_coerce_confidence(raw, expected):
    assert bridge._coerce_confidence(raw) == pytest.approx(expected)


# ─── 섹션 파서 ────────────────────────────────────────────────────────────────

def test_extract_section_case_insensitive_and_alternates():
    body = "## Summary\n한 줄 요약\n\n## Outcome\n- 결과 1\n- 결과 2\n"
    assert bridge._extract_section(body, "summary") == "한 줄 요약"
    assert bridge._extract_section(body, "Key Points", "Outcome") == "- 결과 1\n- 결과 2"
    assert bridge._extract_section(body, "Nonexistent") == ""


def test_extract_bullets_strips_markers():
    text = "- alpha\n* beta\n+ gamma\n일반 문장"
    assert bridge._extract_bullets(text) == ["alpha", "beta", "gamma"]


def test_extract_evidence_links_markdown_and_bare():
    text = (
        "- 참조: [Doc](https://example.com/a)\n"
        "- https://example.com/b\n"
        "- personal_vault/projects/x/y.md\n"
        "- 의미 없는 줄\n"
    )
    uris = bridge._extract_evidence_links(text)
    assert "https://example.com/a" in uris
    assert "https://example.com/b" in uris
    assert "personal_vault/projects/x/y.md" in uris


# ─── sync_published_note 흐름 ─────────────────────────────────────────────────

class _FakeSettings:
    core_api_write_key = "test-key"
    core_api_url = "http://fake-core"
    public_base_url = "https://knowledge.openakashic.com"


@pytest.fixture
def fake_settings(monkeypatch):
    monkeypatch.setattr(bridge, "get_settings", lambda: _FakeSettings())
    return _FakeSettings()


def test_sync_skips_non_syncable_kinds(fake_settings, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "_core_api_post", lambda *a, **k: called.append(a) or {"id": "x"})
    result = bridge.sync_published_note(
        frontmatter={"kind": "playbook", "title": "Playbook X"},
        body="## Summary\n본문",
        note_path="personal_vault/x.md",
    )
    assert result is None
    assert called == []


def test_sync_skips_reference_kind(fake_settings, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "_core_api_post", lambda *a, **k: called.append(a) or {"id": "x"})
    result = bridge.sync_published_note(
        frontmatter={"kind": "reference", "title": "Reference X"},
        body="## Summary\n본문",
        note_path="personal_vault/x.md",
    )
    assert result is None
    assert called == []


def test_sync_skips_publication_request_even_if_published(fake_settings, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "_core_api_post", lambda *a, **k: called.append(a) or {"id": "x"})
    result = bridge.sync_published_note(
        frontmatter={"kind": "publication_request", "publication_status": "published", "title": "Request"},
        body="## Summary\nrequest metadata",
        note_path="personal_vault/projects/ops/librarian/publication_requests/request.md",
    )
    assert result is None
    assert called == []


def test_sync_skips_publication_request_path_defensively(fake_settings, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "_core_api_post", lambda *a, **k: called.append(a) or {"id": "x"})
    result = bridge.sync_published_note(
        frontmatter={"kind": "capsule", "publication_status": "published", "title": "Bad Request Artifact"},
        body="## Summary\nrequest metadata",
        note_path="personal_vault/projects/ops/librarian/publication_requests/request.md",
    )
    assert result is None
    assert called == []


def test_sync_idempotent_via_core_api_id(fake_settings, monkeypatch):
    patched = []
    monkeypatch.setattr(bridge, "_core_api_post", lambda *a, **k: {"id": "new"})
    monkeypatch.setattr(bridge, "_core_api_patch", lambda *a, **k: patched.append(a) or {"id": "existing-id"})
    result = bridge.sync_published_note(
        frontmatter={"kind": "capsule", "core_api_id": "existing-id"},
        body="## Summary\n...",
        note_path="personal_vault/x.md",
    )
    assert result == "existing-id"
    assert len(patched) == 1
    assert "/capsules/existing-id" in patched[0][0]


def test_sync_capsule_with_string_confidence(fake_settings, monkeypatch):
    posted: list[tuple[str, dict]] = []

    def _fake_post(path, payload, write_key, base_url):
        posted.append((path, payload))
        return {"id": "cap-123"}

    monkeypatch.setattr(bridge, "_core_api_post", _fake_post)
    monkeypatch.setattr(bridge, "_create_derived_claim", lambda *a, **k: None)
    body = (
        "## Summary\n전략 캡슐 요약\n\n"
        "## Key Points\n- 포인트 A\n- 포인트 B\n\n"
        "## Caveats\n- 주의 X\n"
    )
    result = bridge.sync_published_note(
        frontmatter={
            "kind": "capsule",
            "title": "Test Capsule",
            "confidence": "high",  # 문자열 — 과거에는 ValueError로 실패했다
            "tags": ["openakashic", "test"],
        },
        body=body,
        note_path="personal_vault/test.md",
    )
    assert result == "cap-123"
    assert len(posted) == 1
    path, payload = posted[0]
    assert path == "/capsules"
    assert payload["confidence"] == pytest.approx(0.9)
    assert payload["summary"] == ["전략 캡슐 요약"]
    assert [p["text"] for p in payload["key_points"]] == ["포인트 A", "포인트 B"]
    assert [p["text"] for p in payload["cautions"]] == ["주의 X"]
    assert payload["metadata"]["source_note"] == "personal_vault/test.md"


def test_sync_capsule_carries_contribution_metadata(fake_settings, monkeypatch):
    captured: dict = {}

    def _fake_post(path, payload, write_key, base_url):
        if path == "/capsules":
            captured.update(payload)
            return {"id": "cap-attr"}
        return {"id": "unused"}

    monkeypatch.setattr(bridge, "_create_derived_claim", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_core_api_post", _fake_post)

    result = bridge.sync_published_note(
        frontmatter={
            "kind": "capsule",
            "title": "Attributed Capsule",
            "contributed_by": "alice",
            "source_note_path": "personal_vault/feeds/source-claim.md",
            "source_note_kind": "claim",
            "source_claim_id": "c_pr3_seed",
        },
        body="## Summary\nAttributed summary.\n",
        note_path="personal_vault/capsule.md",
    )

    assert result == "cap-attr"
    assert captured["metadata"]["contributed_by"] == "alice"
    assert captured["metadata"]["source_note_path"] == "personal_vault/feeds/source-claim.md"
    assert captured["metadata"]["source_note_kind"] == "claim"
    assert captured["metadata"]["source_claim_id"] == "c_pr3_seed"


def test_sync_claim_without_evidence_uses_public_fallback(fake_settings, monkeypatch):
    calls: list[tuple[str, dict]] = []

    def _fake_post(path, payload, write_key, base_url):
        calls.append((path, payload))
        if path == "/claims":
            return {"id": "claim-7"}
        return {"id": "ev-1"}

    monkeypatch.setattr(bridge, "_core_api_post", _fake_post)

    result = bridge.sync_published_note(
        frontmatter={
            "kind": "claim",
            "title": "Test Claim",
            "confidence": "medium",
            "claim_role": "core",
        },
        body="## Claim\n- 이 시스템은 X를 보장한다.\n",
        note_path="personal_vault/claim.md",
    )
    assert result == "claim-7"
    claim_post = next(c for c in calls if c[0] == "/claims")
    assert claim_post[1]["claim_role"] == "core"
    assert claim_post[1]["confidence"] == pytest.approx(0.7)
    assert claim_post[1]["text"] == "이 시스템은 X를 보장한다."
    assert claim_post[1]["status"] == "accepted"

    evidence_posts = [c for c in calls if c[0] == "/evidences"]
    assert evidence_posts, "fallback evidence가 반드시 붙어야 한다"
    uri = evidence_posts[0][1]["source_uri"]
    assert "knowledge.openakashic.com" in uri
    assert "personal_vault/claim.md" in uri


def test_sync_claim_invalid_role_defaults_to_support(fake_settings, monkeypatch):
    captured: dict = {}

    def _fake_post(path, payload, write_key, base_url):
        if path == "/claims":
            captured.update(payload)
            return {"id": "c-1"}
        return {"id": "e-1"}

    monkeypatch.setattr(bridge, "_core_api_post", _fake_post)
    bridge.sync_published_note(
        frontmatter={
            "kind": "claim",
            "claim_role": "architecture",  # Core API 허용 role 아님
        },
        body="## Claim\n유효하지 않은 role 케이스.\n",
        note_path="personal_vault/c.md",
    )
    assert captured["claim_role"] == "support"


def test_sync_claim_updates_existing_core_api_record(fake_settings, monkeypatch):
    patched: list[tuple[str, dict]] = []
    evidences: list[tuple[str, dict]] = []

    def _fake_patch(path, payload, write_key, base_url):
        patched.append((path, payload))
        return {"id": "claim-existing"}

    def _fake_post(path, payload, write_key, base_url):
        evidences.append((path, payload))
        return {"id": "ev-1"}

    monkeypatch.setattr(bridge, "_core_api_patch", _fake_patch)
    monkeypatch.setattr(bridge, "_core_api_post", _fake_post)
    result = bridge.sync_published_note(
        frontmatter={
            "kind": "claim",
            "core_api_id": "claim-existing",
            "claim_review_status": "disputed",
            "confirm_count": 2,
            "dispute_count": 1,
        },
        body="## Claim\n기존 Core claim 업데이트 테스트.\n",
        note_path="personal_vault/existing-claim.md",
    )
    assert result == "claim-existing"
    assert patched
    path, payload = patched[0]
    assert path == "/claims/claim-existing"
    assert payload["metadata"]["claim_review_status"] == "disputed"
    assert payload["metadata"]["confirm_count"] == 2
    assert payload["metadata"]["dispute_count"] == 1
    assert any(call[0] == "/evidences" for call in evidences)


def test_sync_swallows_network_errors(fake_settings, monkeypatch, caplog):
    from urllib import error as urlerror

    def _boom(*a, **k):
        raise urlerror.URLError("connection refused")

    monkeypatch.setattr(bridge, "_core_api_post", _boom)
    result = bridge.sync_published_note(
        frontmatter={"kind": "capsule", "title": "Boom"},
        body="## Summary\nX",
        note_path="personal_vault/boom.md",
    )
    assert result is None  # 예외를 올리지 않고 None으로 조용히 실패
