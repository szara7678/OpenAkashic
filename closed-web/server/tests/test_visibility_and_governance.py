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
