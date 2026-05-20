from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import core_api_bridge, mcp_server, sagwan_loop, site, subordinate, vault
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


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _capsule_body(*, sources: str = "- https://example.com/source") -> str:
    summary = "This capsule exists only for smoke testing. " * 12
    return "\n".join(
        [
            "## Summary",
            summary,
            "",
            "## Key Points",
            "- First point",
            "- Second point",
            "",
            "## Cautions",
            "- First caution",
            "",
            "## Sources",
            sources,
        ]
    )


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
            stack.enter_context(mock.patch.object(sagwan_loop, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(core_api_bridge, "get_settings", return_value=fake_settings))
            stack.enter_context(mock.patch.object(mcp_server, "get_settings", return_value=fake_settings))
            mcp_server.settings = fake_settings
            site.invalidate_notes_cache()
            vault.invalidate_claim_id_cache()
            try:
                yield root
            finally:
                mcp_server.settings = original_mcp_settings
                site.invalidate_notes_cache()
                vault.invalidate_claim_id_cache()


class SagwanHealthFixesTests(unittest.TestCase):
    def test_post_internal_review_refreshes_duplicate_topic(self) -> None:
        with _temp_vault_env():
            target = vault.write_document(
                path="personal_vault/projects/ops/librarian/capsules/target-capsule.md",
                title="Target Capsule",
                kind="capsule",
                project="ops/librarian",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "visibility": "private", "publication_status": "none"},
                allow_owner_change=True,
            )
            admin_auth = AuthState(
                authenticated=True,
                role="admin",
                token_label="test",
                username="sagwan",
                nickname="sagwan",
                owner="sagwan",
                capabilities=["notes:read", "notes:write", "publication:manage"],
                display_name="sagwan",
            )
            with mock.patch.object(mcp_server, "auth_state_for_token", return_value=admin_auth):
                first = mcp_server._post_internal_review(
                    target=target.path,
                    stance="dispute",
                    rationale="Initial review rationale with enough detail to pass validation.",
                    evidence_urls=["https://example.com/first"],
                    topic="sagwan-revalidation",
                )
                second = mcp_server._post_internal_review(
                    target=target.path,
                    stance="dispute",
                    rationale="Refreshed review rationale replacing the previous body content.",
                    evidence_urls=["https://example.com/second"],
                    topic="sagwan-revalidation",
                )

            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "refreshed")
            refreshed = vault.load_document(first["path"])
            self.assertIn("Refreshed review rationale", refreshed.body)
            self.assertEqual(refreshed.frontmatter.get("evidence_urls"), ["https://example.com/second"])

    def test_sync_published_notes_respects_backoff_and_retries_after_24h(self) -> None:
        with _temp_vault_env():
            note_path = "personal_vault/projects/ops/librarian/capsules/core-sync-target.md"
            vault.write_document(
                path=note_path,
                title="Core Sync Target",
                kind="capsule",
                project="ops/librarian",
                body=_capsule_body(),
                metadata={
                    "owner": "busagwan",
                    "visibility": "private",
                    "publication_status": "published",
                    "core_sync_failure_count": 3,
                    "core_sync_last_failure_at": _iso(datetime.now(UTC)),
                    "core_sync_last_failure_reason": "sync_failed",
                },
                allow_owner_change=True,
            )

            sync_calls: list[str] = []

            def _fake_sync(*, note_path: str, **_: object) -> None:
                sync_calls.append(note_path)
                return None

            with mock.patch.object(subordinate, "sync_published_note", side_effect=_fake_sync), mock.patch.object(
                subordinate, "get_last_sync_failure_reason", return_value="network_error: refused"
            ), mock.patch.object(subordinate, "_remember_subordinate_note", return_value=None):
                summary = subordinate._sync_published_notes_to_core_api(limit=10)

            self.assertEqual(sync_calls, [])
            self.assertIn("1 skipped_backoff", summary)

            doc = vault.load_document(note_path)
            older = dict(doc.frontmatter)
            older["core_sync_last_failure_at"] = _iso(datetime.now(UTC) - timedelta(hours=25))
            vault.write_document(path=note_path, body=doc.body, metadata=older, allow_owner_change=True)

            with mock.patch.object(subordinate, "sync_published_note", side_effect=_fake_sync), mock.patch.object(
                subordinate, "get_last_sync_failure_reason", return_value="network_error: refused"
            ), mock.patch.object(subordinate, "_remember_subordinate_note", return_value=None):
                subordinate._sync_published_notes_to_core_api(limit=10)

            self.assertEqual(sync_calls, [note_path])
            retried = vault.load_document(note_path)
            self.assertTrue(bool(retried.frontmatter.get("core_sync_blocked")))

    def test_curate_system_health_writes_blocked_core_sync_request(self) -> None:
        with _temp_vault_env():
            blocked_path = "personal_vault/projects/ops/librarian/capsules/blocked-sync.md"
            vault.write_document(
                path=blocked_path,
                title="Blocked Sync",
                kind="capsule",
                project="ops/librarian",
                body=_capsule_body(),
                metadata={
                    "owner": "busagwan",
                    "visibility": "private",
                    "publication_status": "published",
                    "core_sync_blocked": True,
                    "core_sync_last_failure_reason": "network_error: refused",
                    "core_sync_last_failure_at": _iso(datetime.now(UTC) - timedelta(hours=1)),
                },
                allow_owner_change=True,
            )

            with mock.patch.object(subordinate, "list_subordinate_tasks", return_value=[]), mock.patch.object(
                sagwan_loop, "before_task_context", return_value={"combined": ""}
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli", return_value="## HEALTH\nStable\n\n## IMPROVEMENTS\n"
            ), mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"meta_min_interval_hours": 12}):
                result = sagwan_loop._curate_system_health()

            self.assertEqual(result["status"], "ok")
            request = vault.load_document("personal_vault/meta/improvement-requests/core-sync-blocked-notes.md")
            self.assertIn(blocked_path, request.body)
            self.assertIn("network_error: refused", request.body)

    def test_research_prompt_includes_recent_topics_and_duplicate_topic_is_blocked(self) -> None:
        with _temp_vault_env():
            now = datetime.now(UTC)
            research_log_body = "\n".join(
                [
                    "## Summary",
                    "Sagwan research history.",
                    "",
                    f"## {_iso(now - timedelta(hours=2))} research-gap",
                    "- topic: Expo EAS OTA Auth Token CI/CD",
                    "- queries: [\"q1\"]",
                    "- rationale: prior run",
                    "- model: claude",
                    "- max_fetches: 3",
                    "- capsule_path: personal_vault/projects/ops/librarian/capsules/one.md",
                    "- cited_urls: []",
                    "",
                    f"## {_iso(now - timedelta(hours=4))} research-gap",
                    "- topic: Another Research Topic",
                    "- queries: [\"q2\"]",
                    "- rationale: prior run",
                    "- model: claude",
                    "- max_fetches: 3",
                    "- capsule_path: personal_vault/projects/ops/librarian/capsules/two.md",
                    "- cited_urls: []",
                ]
            )
            vault.write_document(
                path=sagwan_loop._RESEARCH_LOG_PATH,
                title="Sagwan Research Log",
                kind="reference",
                project="ops/librarian",
                body=research_log_body,
                metadata={"owner": "sagwan", "visibility": "private", "publication_status": "none"},
                allow_owner_change=True,
            )
            recent_topics = sagwan_loop._list_recent_research_topics(max_age_days=7, max_entries=15)
            prompt = sagwan_loop._build_gap_selection_prompt(
                {"top_thin": [], "recent_gap_queries": [], "total_capsules": 0, "total_claims": 0},
                "",
                recent_topics,
            )
            self.assertIn("Recently researched", prompt)
            self.assertIn("Expo EAS OTA Auth Token CI/CD", prompt)
            self.assertIn("Another Research Topic", prompt)

            selection = json.dumps(
                {
                    "topic": "CI/CD Expo EAS OTA auth token",
                    "queries": ["expo eas ota auth token ci cd", "expo ota token rotation", "expo eas token fix"],
                    "rationale": "This is the same topic in a different order.",
                    "target_capsule_title": "Duplicate topic",
                }
            )
            with mock.patch.object(
                sagwan_loop,
                "load_sagwan_settings",
                return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3},
            ), mock.patch.object(
                sagwan_loop, "before_task_context", return_value={"distilled": ""}
            ), mock.patch.object(
                sagwan_loop, "recent_memory_tail", return_value=""
            ), mock.patch.object(
                sagwan_loop, "_inventory_knowledge_state", return_value={"top_thin": [], "recent_gap_queries": []}
            ), mock.patch.object(
                sagwan_loop, "load_librarian_settings", return_value={}
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli", return_value=selection
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=AssertionError("should not research duplicates")
            ):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "duplicate_topic_blocked")
            self.assertEqual(result["topic"], "CI/CD Expo EAS OTA auth token")

    def test_research_stage_retries_and_marks_training_only_without_citations(self) -> None:
        with _temp_vault_env():
            no_url_capsule = _capsule_body(sources="- Sources unavailable")
            dedup_proceed = json.dumps({"verdict": "proceed", "rationale": "No close existing coverage."})
            selection = json.dumps(
                {
                    "topic": "Fresh research topic",
                    "queries": ["fresh query one", "fresh query two", "fresh query three"],
                    "rationale": "A non-duplicate topic for grounding retry smoke coverage.",
                    "target_capsule_title": "Fresh Research Topic Capsule",
                }
            )
            with mock.patch.object(
                sagwan_loop,
                "load_sagwan_settings",
                return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3},
            ), mock.patch.object(
                sagwan_loop, "before_task_context", return_value={"distilled": ""}
            ), mock.patch.object(
                sagwan_loop, "recent_memory_tail", return_value=""
            ), mock.patch.object(
                sagwan_loop,
                "_inventory_knowledge_state",
                return_value={"top_thin": [], "recent_gap_queries": [], "total_capsules": 0, "total_claims": 0},
            ), mock.patch.object(
                sagwan_loop, "load_librarian_settings", return_value={}
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli", return_value=selection
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=[dedup_proceed, no_url_capsule, no_url_capsule]
            ) as invoke_tools:
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(invoke_tools.call_count, 3)
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["retry_attempted"])
            self.assertEqual(result["research_grounding"], "training_only")
            saved = vault.load_document(result["capsule_path"])
            self.assertEqual(saved.frontmatter.get("research_grounding"), "training_only")


if __name__ == "__main__":
    unittest.main()
