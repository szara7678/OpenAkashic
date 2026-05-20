from __future__ import annotations

from contextlib import ExitStack, contextmanager
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import core_api_bridge, mcp_server, site, subordinate, vault
from app.auth import AuthState


class _FakeSettings:
    def __init__(self, root: Path) -> None:
        self.closed_akashic_path = str(root)
        self.default_note_owner = "tester"
        self.default_note_visibility = "private"
        self.writable_roots = "doc,personal_vault,assets"
        self.user_store_path = str(root / "server" / "data" / "users.json")
        self.public_base_url = "https://knowledge.openakashic.com"
        self.core_api_url = "http://fake-core"
        self.core_api_write_key = "fake-key"
        self.bearer_token = "test-token"
        self.admin_username = "admin"
        self.admin_nickname = "admin"

    @property
    def writable_root_list(self) -> list[str]:
        return ["doc", "personal_vault", "assets"]


@contextmanager
def _temp_vault_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "server" / "data").mkdir(parents=True, exist_ok=True)
        fake_settings = _FakeSettings(root)
        original_mcp_settings = mcp_server.settings
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(vault, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(site, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(subordinate, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(core_api_bridge, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(mcp_server, "get_settings", return_value=fake_settings))
            mcp_server.settings = fake_settings
            site.invalidate_notes_cache()
            vault.invalidate_claim_id_cache()
            try:
                yield
            finally:
                mcp_server.settings = original_mcp_settings
                site.invalidate_notes_cache()
                vault.invalidate_claim_id_cache()


def _capsule_body() -> str:
    return "\n".join(
        [
            "## Summary",
            "This capsule exists only for testing the maintenance review guard. " * 8,
            "",
            "## Key Points",
            "- First point",
            "- Second point",
            "",
            "## Cautions",
            "- First caution",
            "",
            "## Sources",
            "- https://example.com/source",
        ]
    )


def _admin_auth() -> AuthState:
    return AuthState(
        authenticated=True,
        role="admin",
        token_label="test",
        username="sagwan",
        nickname="sagwan",
        owner="sagwan",
        capabilities=["notes:read", "notes:write", "publication:manage"],
        display_name="sagwan",
    )


class MaintenanceReviewGuardTests(unittest.TestCase):
    def test_non_reviewable_internal_review_is_skipped(self) -> None:
        with _temp_vault_env():
            target = vault.write_document(
                path="personal_vault/projects/ops/librarian/reference/non-reviewable.md",
                title="Non Reviewable",
                kind="reference",
                project="ops/librarian",
                body="## Summary\nReference note.",
                metadata={"owner": "sagwan", "visibility": "private"},
                allow_owner_change=True,
            )

            result = mcp_server._post_internal_review(
                target=target.path,
                stance="dispute",
                rationale="This rationale is long enough, but the target kind should skip review.",
                topic="sagwan-maintenance-owner-guard",
            )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "non-reviewable-target")
            self.assertEqual(result["kind"], "reference")
            self.assertEqual(result["target"], target.path)

    def test_capsule_internal_review_still_creates_review(self) -> None:
        with _temp_vault_env():
            target = vault.write_document(
                path="personal_vault/projects/ops/librarian/capsules/reviewable.md",
                title="Reviewable Capsule",
                kind="capsule",
                project="ops/librarian",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "visibility": "private", "publication_status": "none"},
                allow_owner_change=True,
            )

            with mock.patch.object(mcp_server, "auth_state_for_token", return_value=_admin_auth()):
                result = mcp_server._post_internal_review(
                    target=target.path,
                    stance="dispute",
                    rationale="Capsule targets should keep creating internal reviews as they did before.",
                    topic="sagwan-maintenance-owner-guard",
                )

            self.assertEqual(result["status"], "created")
            self.assertEqual(result["targets"], target.path)
            self.assertEqual(result["stance"], "dispute")
            self.assertTrue(result["path"].startswith("personal_vault/"))


if __name__ == "__main__":
    unittest.main()
