from __future__ import annotations

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.auth import AuthState  # noqa: E402
from app import main  # noqa: E402
from app import librarian  # noqa: E402
from app import vault  # noqa: E402
from app.guidance import openakashic_guidance_payload  # noqa: E402


def _auth(*, authenticated: bool, role: str, nickname: str) -> AuthState:
    return AuthState(
        authenticated=authenticated,
        role=role,
        token_label=role,
        username=nickname,
        nickname=nickname,
        owner=nickname,
        capabilities=[],
        display_name=nickname,
    )


def test_http_api_can_read_shared_notes_for_authenticated_users():
    note = {"visibility": "shared", "owner": "alice"}
    assert main._can_read_frontmatter(note, _auth(authenticated=True, role="user", nickname="bob")) is True
    assert main._can_read_frontmatter(note, _auth(authenticated=False, role="anonymous", nickname="anonymous")) is False


def test_vault_normalizes_shared_visibility():
    assert vault._normalize_visibility("shared") == "shared"
    assert vault._normalize_visibility("source_shared") == "shared"
    assert vault._normalize_visibility("shared_source") == "shared"


def test_publication_status_accepts_curation_states():
    assert vault._normalize_publication_status("needs_merge") == "needs_merge"
    assert vault._normalize_publication_status("needs_evidence") == "needs_evidence"
    assert vault._normalize_publication_status("superseded") == "superseded"


def test_librarian_defaults_disable_exec_command():
    defaults = librarian._default_librarian_settings()
    assert "exec_command" not in defaults["enabled_tools"]
    assert "search_notes" in defaults["enabled_tools"]


def test_http_claim_defaults_to_public_and_published_for_non_admin():
    payload = main.NoteWriteRequest(
        path="personal_vault/projects/personal/openakashic/reference/test-claim.md",
        body="## Claim\n- claim text\n",
        kind="claim",
    )
    metadata = main._normalize_write_metadata(payload, _auth(authenticated=True, role="user", nickname="alice"))
    assert metadata["visibility"] == "public"
    assert metadata["publication_status"] == "published"
    assert metadata["owner"] == "alice"


def test_public_claim_owner_can_modify():
    note = {"visibility": "public", "kind": "claim", "owner": "alice"}
    assert main._can_modify_frontmatter(note, _auth(authenticated=True, role="user", nickname="alice")) is True
    assert main._can_modify_frontmatter(note, _auth(authenticated=True, role="user", nickname="bob")) is False


def test_guidance_payload_is_light_touch_and_claim_first():
    payload = openakashic_guidance_payload(public_base_url="https://knowledge.openakashic.com")
    assert payload["mode"] == "light"
    assert "claim" in payload["optional_settings_snippet"]
    assert "Do not rewrite your whole agent policy" in payload["non_goals"][0]
