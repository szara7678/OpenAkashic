from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import config, librarian, mcp_server, sagwan_loop, subordinate, vault


@contextmanager
def temp_closed_akashic_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "server" / "logs").mkdir(parents=True, exist_ok=True)
        user_store = root / "server" / "data" / "users.json"
        user_store.parent.mkdir(parents=True, exist_ok=True)
        user_store.write_text('{"users":[]}\n', encoding="utf-8")
        env = {
            "CLOSED_AKASHIC_PATH": str(root),
            "CLOSED_AKASHIC_USER_STORE_PATH": str(user_store),
            "CLOSED_AKASHIC_LOG_DIR": str(root / "server" / "logs"),
            "CLOSED_AKASHIC_FTS_INDEX_PATH": str(root / "server" / "logs" / "closed-notes-fts.sqlite3"),
            "CLOSED_AKASHIC_SEMANTIC_CACHE_PATH": str(root / "server" / "logs" / "semantic-index.json"),
            "CLOSED_AKASHIC_BEARER_TOKEN": "",
            "CLOSED_AKASHIC_DEFAULT_NOTE_OWNER": "aaron",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config.get_settings.cache_clear()
            try:
                yield root
            finally:
                config.get_settings.cache_clear()


class SagwanQualityFixesTests(unittest.TestCase):
    def test_invoke_claude_cli_with_tools_skips_permission_mode_when_no_tools(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(librarian.subprocess, "run", side_effect=fake_run):
            librarian._invoke_claude_cli_with_tools("test", tools=[])

        cmd = captured["cmd"]
        self.assertNotIn("--permission-mode", cmd)

    def test_invoke_claude_cli_with_tools_bypasses_permission_mode_when_tools_present(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(librarian.subprocess, "run", side_effect=fake_run):
            librarian._invoke_claude_cli_with_tools("test", tools=["WebSearch"])

        cmd = captured["cmd"]
        self.assertIn("--permission-mode", cmd)
        flag_index = cmd.index("--permission-mode")
        self.assertEqual(cmd[flag_index + 1], "bypassPermissions")

    def test_extract_source_urls_strips_backticks_and_trailing_punctuation(self) -> None:
        body = "## Sources\n- `https://foo.com/bar`\n- https://baz.com/qux."
        self.assertEqual(
            sagwan_loop._extract_source_urls(body),
            ["https://foo.com/bar", "https://baz.com/qux"],
        )

    def test_load_sagwan_settings_defaults_include_new_intervals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "sagwan-settings.json"
            with mock.patch.object(sagwan_loop, "sagwan_settings_path", return_value=settings_path):
                loaded = sagwan_loop.load_sagwan_settings()

        self.assertEqual(loaded["topic_min_interval_hours"], 12)
        self.assertEqual(loaded["meta_min_interval_hours"], 12)
        self.assertEqual(loaded["research_interval_sec"], 7200)

    def test_save_sagwan_settings_round_trips_new_intervals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "sagwan-settings.json"
            with mock.patch.object(sagwan_loop, "sagwan_settings_path", return_value=settings_path):
                saved = sagwan_loop.save_sagwan_settings(
                    {
                        "topic_min_interval_hours": 8,
                        "meta_min_interval_hours": 48,
                    }
                )
                reloaded = json.loads(settings_path.read_text(encoding="utf-8"))
                loaded = sagwan_loop.load_sagwan_settings()

        self.assertEqual(saved["topic_min_interval_hours"], 8)
        self.assertEqual(saved["meta_min_interval_hours"], 48)
        self.assertEqual(reloaded["topic_min_interval_hours"], 8)
        self.assertEqual(reloaded["meta_min_interval_hours"], 48)
        self.assertEqual(loaded["topic_min_interval_hours"], 8)
        self.assertEqual(loaded["meta_min_interval_hours"], 48)

    def test_curate_propose_topics_reads_interval_from_settings(self) -> None:
        state_doc = types.SimpleNamespace(frontmatter={"last_run_at": sagwan_loop._now_iso()}, body="")

        with mock.patch.object(
            sagwan_loop,
            "load_sagwan_settings",
            return_value={"topic_min_interval_hours": 12},
        ), mock.patch("app.vault.load_document", return_value=state_doc):
            result = sagwan_loop._curate_propose_topics()

        self.assertEqual(result["status"], "cooldown")

    def test_curate_system_health_reads_interval_from_settings(self) -> None:
        state_doc = types.SimpleNamespace(frontmatter={"last_run_at": sagwan_loop._now_iso()}, body="")

        with mock.patch.object(
            sagwan_loop,
            "load_sagwan_settings",
            return_value={"meta_min_interval_hours": 12},
        ), mock.patch("app.vault.load_document", return_value=state_doc):
            result = sagwan_loop._curate_system_health()

        self.assertEqual(result["status"], "cooldown")

    def test_curate_research_gaps_skip_existing_coverage_skips_research_stage(self) -> None:
        with temp_closed_akashic_env():
            tool_calls: list[list[str]] = []

            def fake_tool_call(prompt, **kwargs):
                tools = list(kwargs.get("tools") or [])
                tool_calls.append(tools)
                if tools and tools[0].startswith("mcp__openakashic__"):
                    return '{"verdict":"skip","existing_path":"personal_vault/projects/ops/librarian/capsules/Modal UI.md","rationale":"already covered"}'
                raise AssertionError("research stage should not run after skip verdict")

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"modal ui","queries":["modal accessibility","modal state management"],"rationale":"gap","target_capsule_title":"Modal UI Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=fake_tool_call):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "skip_existing_coverage")
            self.assertEqual(len(tool_calls), 1)
            self.assertIn("mcp__openakashic__search_akashic", tool_calls[0])
            log_doc = vault.load_document("personal_vault/projects/ops/librarian/activity/research-log.md")
            self.assertTrue(str(log_doc.frontmatter.get("last_run_at") or "").strip())
            self.assertIn("status: skipped_duplicate", log_doc.body)
            self.assertIn("existing_path: personal_vault/projects/ops/librarian/capsules/Modal UI.md", log_doc.body)

    def test_curate_research_gaps_refines_topic_before_research(self) -> None:
        with temp_closed_akashic_env():
            research_prompts: list[str] = []

            def fake_tool_call(prompt, **kwargs):
                tools = list(kwargs.get("tools") or [])
                if tools and tools[0].startswith("mcp__openakashic__"):
                    return json.dumps(
                        {
                            "verdict": "refine",
                            "new_topic": "Modal accessibility for screen readers",
                            "new_queries": ["screen reader modal accessibility", "aria modal focus trap"],
                            "rationale": "narrow the topic",
                        }
                    )
                research_prompts.append(prompt)
                return "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- https://example.com/a\n"

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"modal ui","queries":["modal accessibility"],"rationale":"gap","target_capsule_title":"modal ui Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=fake_tool_call):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "ok")
            self.assertTrue(research_prompts)
            self.assertIn("Modal accessibility for screen readers", research_prompts[0])
            self.assertIn("screen reader modal accessibility", research_prompts[0])

    def test_curate_research_gaps_proceeds_normally(self) -> None:
        with temp_closed_akashic_env():
            tool_calls: list[list[str]] = []

            def fake_tool_call(prompt, **kwargs):
                tools = list(kwargs.get("tools") or [])
                tool_calls.append(tools)
                if tools and tools[0].startswith("mcp__openakashic__"):
                    return '{"verdict":"proceed","rationale":"no overlap"}'
                return "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- https://example.com/a\n"

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"modal ui","queries":["modal accessibility"],"rationale":"gap","target_capsule_title":"Modal UI Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=fake_tool_call):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(tool_calls), 2)

    def test_curate_research_gaps_marks_supplement_target_when_dedup_requests_extension(self) -> None:
        with temp_closed_akashic_env():
            extend_path = "personal_vault/projects/ops/librarian/capsules/Existing Modal Capsule.md"

            def fake_tool_call(prompt, **kwargs):
                tools = list(kwargs.get("tools") or [])
                if tools and tools[0].startswith("mcp__openakashic__"):
                    return json.dumps(
                        {
                            "verdict": "supplement",
                            "extend_path": extend_path,
                            "rationale": "existing capsule is thin",
                        }
                    )
                return "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- https://example.com/a\n"

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"modal ui","queries":["modal accessibility"],"rationale":"gap","target_capsule_title":"Modal UI Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=fake_tool_call):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["research_supplement_to"], extend_path)
            doc = vault.load_document(result["capsule_path"])
            self.assertEqual(doc.frontmatter.get("research_supplement_to"), extend_path)

    def test_curate_research_gaps_marks_training_only_when_retry_still_has_no_urls(self) -> None:
        with temp_closed_akashic_env():
            outputs = [
                '{"verdict":"proceed","rationale":"ok"}',
                "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- none\n",
                "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- still none\n",
            ]

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"expo issue","queries":["expo token"],"rationale":"gap","target_capsule_title":"Expo Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=outputs):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["research_grounding"], "training_only")
            doc = vault.load_document(result["capsule_path"])
            self.assertEqual(doc.frontmatter.get("research_grounding"), "training_only")
            self.assertEqual(int(doc.frontmatter.get("research_retry_count") or 0), 1)

    def test_curate_research_gaps_keeps_web_grounded_without_retry(self) -> None:
        with temp_closed_akashic_env():
            tool_calls: list[list[str]] = []

            def fake_tool_call(prompt, **kwargs):
                tools = list(kwargs.get("tools") or [])
                tool_calls.append(tools)
                if tools and tools[0].startswith("mcp__openakashic__"):
                    return '{"verdict":"proceed","rationale":"ok"}'
                return "## Summary\n" + ("body\n" * 120) + "\n## Sources\n- https://example.com/a\n"

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"research_enabled": True, "research_interval_sec": 7200, "research_max_fetches": 3}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}), \
                 mock.patch.object(sagwan_loop, "recent_memory_tail", return_value=""), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value='{"topic":"expo issue","queries":["expo token"],"rationale":"gap","target_capsule_title":"Expo Capsule"}'), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli_with_tools", side_effect=fake_tool_call):
                result = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["research_grounding"], "web_grounded")
            self.assertEqual(len(tool_calls), 2)

    def test_sync_published_notes_to_core_api_honors_backoff_after_three_failures(self) -> None:
        with temp_closed_akashic_env():
            subordinate.ensure_subordinate_workspace()
            note_path = "personal_vault/projects/ops/librarian/reference/blocked-sync.md"
            vault.write_document(
                path=note_path,
                title="Blocked Sync",
                kind="capsule",
                project="ops/librarian",
                status="active",
                body="## Summary\nbody\n## Sources\n- https://example.com\n",
                metadata={
                    "publication_status": "published",
                    "visibility": "private",
                    "owner": "sagwan",
                    "core_sync_failure_count": 3,
                    "core_sync_last_failure_at": subordinate._now_iso(),
                    "core_sync_last_failure_reason": "timeout",
                },
                allow_owner_change=True,
            )
            sync_mock = mock.Mock(return_value=None)
            with mock.patch.object(subordinate, "sync_published_note", sync_mock):
                result = subordinate._sync_published_notes_to_core_api(limit=10)
            self.assertIn("skipped_backoff", result)
            sync_mock.assert_not_called()

            doc = vault.load_document(note_path)
            older = sagwan_loop._parse_iso_datetime(doc.frontmatter["core_sync_last_failure_at"]) - timedelta(hours=25)
            older_iso = older.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            vault.write_document(
                path=note_path,
                body=doc.body,
                metadata={**doc.frontmatter, "core_sync_last_failure_at": older_iso},
                allow_owner_change=True,
            )
            with mock.patch.object(subordinate, "sync_published_note", sync_mock):
                subordinate._sync_published_notes_to_core_api(limit=10)
            sync_mock.assert_called_once()

    def test_curate_system_health_writes_blocked_core_sync_request(self) -> None:
        with temp_closed_akashic_env():
            blocked_path = "personal_vault/projects/ops/librarian/reference/blocked-sync.md"
            vault.write_document(
                path=blocked_path,
                title="Blocked Sync",
                kind="capsule",
                project="ops/librarian",
                status="active",
                body="## Summary\nbody\n## Sources\n- https://example.com\n",
                metadata={
                    "publication_status": "published",
                    "visibility": "private",
                    "owner": "sagwan",
                    "core_sync_blocked": True,
                    "core_sync_last_failure_reason": "bridge timeout",
                    "core_sync_last_failure_at": "2026-04-25T00:00:00Z",
                },
                allow_owner_change=True,
            )
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value={"meta_min_interval_hours": 12}), \
                 mock.patch.object(sagwan_loop, "before_task_context", return_value={"combined": ""}), \
                 mock.patch.object(sagwan_loop, "load_librarian_settings", return_value={"model": "claude-sonnet-4-6"}), \
                 mock.patch.object(sagwan_loop, "_invoke_claude_cli", return_value="## HEALTH\nok\n\n## IMPROVEMENTS\n"):
                result = sagwan_loop._curate_system_health()

            self.assertEqual(result["status"], "ok")
            request_doc = vault.load_document("personal_vault/meta/improvement-requests/core-sync-blocked-notes.md")
            self.assertIn("bridge timeout", request_doc.body)
            self.assertIn(blocked_path, request_doc.body)

    def test_post_internal_review_refreshes_existing_review_without_double_counting(self) -> None:
        with temp_closed_akashic_env():
            target = "personal_vault/projects/ops/librarian/capsules/Modal Capsule.md"
            vault.write_document(
                path=target,
                title="Modal Capsule",
                kind="capsule",
                project="ops/librarian",
                status="active",
                body="## Summary\nmodal\n## Sources\n- https://example.com\n",
                metadata={"visibility": "private", "owner": "busagwan"},
                allow_owner_change=True,
            )

            first = mcp_server._post_internal_review(
                target=target,
                topic="modal-a11y",
                stance="dispute",
                rationale="First rationale explains the original dispute clearly.",
            )
            second = mcp_server._post_internal_review(
                target=target,
                topic="modal-a11y",
                stance="dispute",
                rationale="Second rationale replaces the first review body with refreshed detail.",
                evidence_urls=["https://example.com/review", "https://example.com/review"],
            )

            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "refreshed")
            review_doc = vault.load_document(second["path"])
            self.assertIn("Second rationale replaces the first review body with refreshed detail.", review_doc.body)
            self.assertEqual(review_doc.frontmatter.get("evidence_urls"), ["https://example.com/review"])
            parent_doc = vault.load_document(target)
            self.assertEqual(int(parent_doc.frontmatter.get("dispute_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()
