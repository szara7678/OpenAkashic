from __future__ import annotations

from contextlib import ExitStack, contextmanager
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.auth import AuthState  # noqa: E402


def _auth(nickname: str = "alice") -> AuthState:
    return AuthState(
        authenticated=True,
        role="user",
        token_label="test",
        username=nickname,
        nickname=nickname,
        owner=nickname,
        capabilities=[],
        display_name=nickname,
    )


@contextmanager
def _temp_openakashic_env():
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
            "CLOSED_AKASHIC_DEFAULT_NOTE_OWNER": "alice",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            from app import config, mcp_server, site, vault

            config.get_settings.cache_clear()
            original_mcp_settings = mcp_server.settings
            mcp_server.settings = config.get_settings()
            site.invalidate_notes_cache()
            vault.invalidate_claim_id_cache()
            try:
                yield vault, mcp_server
            finally:
                mcp_server.settings = original_mcp_settings
                site.invalidate_notes_cache()
                vault.invalidate_claim_id_cache()
                config.get_settings.cache_clear()


def test_claim_contribution_status_returns_state_timestamp_and_reviewer_notes_by_path():
    with _temp_openakashic_env() as (vault, mcp_server):
        path = "personal_vault/projects/personal/openakashic/reference/rejected-claim.md"
        vault.write_document(
            path=path,
            title="Rejected Claim",
            kind="claim",
            project="personal/openakashic",
            body="## Claim\nOpenAkashic status checks expose reviewer notes.\n",
            metadata={
                "owner": "alice",
                "created_by": "alice",
                "visibility": "private",
                "publication_status": "guardrail_rejected",
                "publication_requested_at": "2026-05-22T01:02:03Z",
                "publication_requested_by": "alice",
                "guardrail_decided_at": "2026-05-22T02:00:00Z",
                "guardrail_decided_by": "sagwan",
                "guardrail_reject_reason": "needs a clearer source signal",
            },
        )

        with mcp_server._auth_override(_auth("alice")):
            result = mcp_server.claim_contribution_status(path=path)

    assert result["status"] == "ok"
    assert result["count"] == 1
    claim = result["claims"][0]
    assert claim["path"] == path
    assert claim["state"] == "guardrail_rejected"
    assert claim["submitted_at"] == "2026-05-22T01:02:03Z"
    assert claim["submitted_by"] == "alice"
    assert claim["reviewer_notes"][0]["stage"] == "guardrail_reject"
    assert claim["reviewer_notes"][0]["note"] == "needs a clearer source signal"


def test_claim_contribution_status_can_find_claim_by_query():
    with _temp_openakashic_env() as (vault, mcp_server):
        path = "personal_vault/projects/personal/openakashic/reference/queryable-claim.md"
        vault.write_document(
            path=path,
            title="Queryable Contribution Status Claim",
            kind="claim",
            project="personal/openakashic",
            body="## Claim\nPR3 query lookup finds contribution status for submitted claims.\n",
            metadata={
                "owner": "alice",
                "created_by": "alice",
                "visibility": "private",
                "publication_status": "guardrail_passed",
                "publication_requested_at": "2026-05-22T03:00:00Z",
                "guardrail_pass_reason": "specific and scoped",
            },
        )

        with mcp_server._auth_override(_auth("alice")):
            result = mcp_server.claim_contribution_status(query="Queryable Contribution Status", limit=3)

    assert result["status"] == "ok"
    assert [claim["path"] for claim in result["claims"]] == [path]
    assert result["claims"][0]["state"] == "guardrail_passed"


def test_claim_seed_generated_capsule_preserves_submitter_attribution():
    with _temp_openakashic_env() as (vault, _mcp_server):
        from app import sagwan_loop, site

        seed_path = "personal_vault/feeds/pr3-claim-seed.md"
        vault.write_document(
            path=seed_path,
            title="PR3 Claim Seed",
            kind="claim",
            project="feeds",
            body="## Claim\n" + ("A submitted claim can seed a later public capsule. " * 12),
            metadata={
                "owner": "alice",
                "created_by": "alice",
                "publication_requested_by": "alice",
                "claim_id": "c_pr3_seed",
                "visibility": "private",
                "publication_status": "guardrail_passed",
            },
        )
        capsule_body = (
            "## Summary\n"
            + ("This capsule summarizes the submitted claim with preserved provenance. " * 12)
            + "\n\n## Key Points\n- Provenance survives generation.\n\n## Cautions\n- Review before publishing.\n\n## Sources\n- seed\n"
        )

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(site, "search_closed_notes", return_value={"results": []}))
            stack.enter_context(mock.patch.object(sagwan_loop, "before_task_context", return_value={"combined": ""}))
            stack.enter_context(mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value=capsule_body))
            stack.enter_context(mock.patch.object(sagwan_loop, "remember", return_value=None))
            result = sagwan_loop._curate_generate_capsules()

        assert result["generated"] == 1
        capsule = vault.load_document(result["path"])
        assert capsule.frontmatter["source_note_path"] == seed_path
        assert capsule.frontmatter["source_note_kind"] == "claim"
        assert capsule.frontmatter["contributed_by"] == "alice"
        assert capsule.frontmatter["source_claim_id"] == "c_pr3_seed"
