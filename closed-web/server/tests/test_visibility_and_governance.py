from __future__ import annotations

from contextlib import contextmanager
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

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


@contextmanager
def _temp_openakashic_env(owner: str = "alice"):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "server" / "logs").mkdir(parents=True, exist_ok=True)
        (root / "server" / "data").mkdir(parents=True, exist_ok=True)
        user_store = root / "server" / "data" / "users.json"
        user_store.write_text('{"users":[]}\n', encoding="utf-8")
        env = {
            "CLOSED_AKASHIC_PATH": str(root),
            "CLOSED_AKASHIC_USER_STORE_PATH": str(user_store),
            "CLOSED_AKASHIC_LOG_DIR": str(root / "server" / "logs"),
            "CLOSED_AKASHIC_FTS_INDEX_PATH": str(root / "server" / "logs" / "closed-notes-fts.sqlite3"),
            "CLOSED_AKASHIC_SEMANTIC_CACHE_PATH": str(root / "server" / "logs" / "semantic-index.json"),
            "CLOSED_AKASHIC_BEARER_TOKEN": "",
            "CLOSED_AKASHIC_DEFAULT_NOTE_OWNER": owner,
        }
        with mock.patch.dict(os.environ, env, clear=False):
            from app import config, mcp_server, site

            config.get_settings.cache_clear()
            original_main_settings = main.settings
            original_mcp_settings = mcp_server.settings
            main.settings = config.get_settings()
            mcp_server.settings = config.get_settings()
            site.invalidate_notes_cache()
            vault.invalidate_claim_id_cache()
            try:
                yield mcp_server
            finally:
                main.settings = original_main_settings
                mcp_server.settings = original_mcp_settings
                site.invalidate_notes_cache()
                vault.invalidate_claim_id_cache()
                config.get_settings.cache_clear()


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


def test_http_claim_defaults_to_private_and_requested():
    payload = main.NoteWriteRequest(
        path="personal_vault/projects/personal/openakashic/reference/test-claim.md",
        body="## Claim\n- claim text\n",
        kind="claim",
    )
    metadata = main._normalize_write_metadata(payload, _auth(authenticated=True, role="user", nickname="alice"))
    assert metadata["visibility"] == "private"
    assert metadata["publication_status"] == "requested"
    assert "core_api_id" not in metadata
    assert metadata["owner"] == "alice"


def test_http_claim_upsert_does_not_create_publication_request():
    with _temp_openakashic_env():
        payload = main.NoteWriteRequest(
            path="personal_vault/projects/personal/openakashic/reference/http-claim.md",
            body="## Claim\nHTTP claim writes enter only the guardrail queue.\n",
            kind="claim",
        )
        auth = _auth(authenticated=True, role="user", nickname="alice")

        with mock.patch.object(main, "request_publication") as request_publication:
            result = main.api_upsert_note(payload, auth)

        request_publication.assert_not_called()
        assert result["publication_request"] is None
        doc = vault.load_document(payload.path)
        assert doc.frontmatter["publication_status"] == "requested"
        assert vault.list_publication_requests() == []


def test_mcp_claim_upsert_does_not_create_publication_request():
    with _temp_openakashic_env() as mcp_server:
        path = "personal_vault/projects/personal/openakashic/reference/mcp-claim.md"
        auth = _auth(authenticated=True, role="user", nickname="alice")

        with mcp_server._auth_override(auth), mock.patch.object(mcp_server, "request_publication") as request_publication:
            result = mcp_server.upsert_note(
                path=path,
                body="## Claim\nMCP claim writes enter only the guardrail queue.\n",
                kind="claim",
            )

        request_publication.assert_not_called()
        assert result["publication_request"] is None
        doc = vault.load_document(path)
        assert doc.frontmatter["publication_status"] == "requested"
        assert vault.list_publication_requests() == []


def test_public_claim_owner_can_modify():
    note = {"visibility": "public", "kind": "claim", "owner": "alice"}
    assert main._can_modify_frontmatter(note, _auth(authenticated=True, role="user", nickname="alice")) is True
    assert main._can_modify_frontmatter(note, _auth(authenticated=True, role="user", nickname="bob")) is False


def test_guidance_payload_is_light_touch_and_claim_first():
    payload = openakashic_guidance_payload(public_base_url="https://knowledge.openakashic.com")
    assert payload["mode"] == "light"
    assert "claim" in payload["optional_settings_snippet"]
    assert "Do not rewrite your whole agent policy" in payload["non_goals"][0]
