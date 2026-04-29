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

from app import core_api_bridge, librarian, mcp_server, sagwan_loop, site, subordinate, vault


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
        self.librarian_provider = "claude-cli"
        self.librarian_model = "claude-sonnet-4-6"
        self.librarian_base_url = ""
        self.librarian_reasoning_effort = "medium"
        self.librarian_project = "ops/librarian"
        self.has_librarian_api_key = False
        self.librarian_effective_base_url = ""
        self.librarian_api_key = ""

    @property
    def writable_root_list(self) -> list[str]:
        return ["doc", "personal_vault", "assets"]


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _capsule_body(*, sources: str = "- https://example.com/source") -> str:
    summary = "This capsule exists only for Sagwan v2 testing. " * 14
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


def _default_stage_settings() -> dict[str, object]:
    return {
        "maintenance_enabled": True,
        "maintenance_interval_sec": 1800,
        "research_enabled": True,
        "research_interval_sec": 7200,
        "research_max_fetches": 3,
        "consolidate_enabled": True,
        "consolidate_interval_sec": 21600,
        "consolidate_min_reviews": 3,
        "topic_min_interval_hours": 12,
        "meta_min_interval_hours": 12,
        "profile_update_min_interval_hours": 24,
        "llm_call_hourly_cap": 50,
        "llm_call_ceiling_action": "skip_stage",
        "distill_min_interval_sec": 21600,
        "distill_min_episodes": 5,
        "stage_models": dict(sagwan_loop._SAGWAN_STAGE_MODEL_DEFAULTS),
    }


@contextmanager
def _temp_vault_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "server" / "data").mkdir(parents=True, exist_ok=True)
        fake_settings = _FakeSettings(root)
        original_mcp_settings = mcp_server.settings
        with ExitStack() as stack:
            for module in (vault, site, subordinate, sagwan_loop, core_api_bridge, mcp_server, librarian):
                stack.enter_context(mock.patch.object(module, "get_settings", return_value=fake_settings))
            mcp_server.settings = fake_settings
            site.invalidate_notes_cache()
            vault.invalidate_claim_id_cache()
            try:
                yield root
            finally:
                mcp_server.settings = original_mcp_settings
                site.invalidate_notes_cache()
                vault.invalidate_claim_id_cache()
                sagwan_loop._LLM_CALL_HISTORY[:] = []


class _StreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)


class SagwanV2Tests(unittest.TestCase):
    def test_invoke_proxy_chat_happy_path(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _StreamResponse(
                [
                    b'data: {"choices":[{"delta":{"content":"hello "}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"world"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

        with mock.patch.object(librarian, "_proxy_chat_urls", return_value=["http://proxy.test/v1/chat/completions"]), mock.patch.object(
            librarian.urlrequest, "urlopen", side_effect=fake_urlopen
        ):
            result = librarian._invoke_proxy_chat("say hi", model="gpt-5.4", system="system prompt")

        self.assertEqual(result, "hello world")
        self.assertEqual(captured["url"], "http://proxy.test/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "gpt-5.4")
        self.assertEqual(captured["body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["body"]["messages"][1]["content"], "say hi")

    def test_invoke_for_stage_routes_between_proxy_and_claude_cli(self) -> None:
        settings = _default_stage_settings()
        settings["stage_models"] = {
            "research": "claude-cli:claude-sonnet-4-6",
            "revalidate": "proxy:gpt-5.4",
        }
        with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
            sagwan_loop, "_invoke_claude_cli_with_tools", return_value="claude-result"
        ) as mock_cli, mock.patch.object(
            sagwan_loop, "_invoke_proxy_chat", return_value="proxy-result"
        ) as mock_proxy:
            research = sagwan_loop._invoke_for_stage("research", "prompt", web_tools=True)
            revalidate = sagwan_loop._invoke_for_stage("revalidate", "prompt")

        self.assertEqual(research, "claude-result")
        self.assertEqual(revalidate, "proxy-result")
        mock_cli.assert_called_once()
        self.assertEqual(mock_cli.call_args.kwargs["tools"], sagwan_loop._web_tools_list())
        mock_proxy.assert_called_once()

    def test_maintenance_stage_skips_when_hourly_cap_hit(self) -> None:
        with _temp_vault_env():
            vault.write_document(
                path="personal_vault/projects/demo/reference/candidate.md",
                title="Candidate",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(hours=2))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            settings["llm_call_hourly_cap"] = 1
            sagwan_loop._LLM_CALL_HISTORY[:] = [
                {
                    "ts": sagwan_loop._now_iso(),
                    "stage": "other",
                    "backend": "proxy",
                    "model": "gpt-5.4",
                    "duration_s": 0.1,
                    "estimated_tokens": 10,
                }
            ]
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings):
                result = sagwan_loop._curate_maintenance(force=True)

        self.assertEqual(result["status"], "rate_limit_skipped")

    def test_maintenance_keep_updates_last_maintained_at(self) -> None:
        with _temp_vault_env():
            path = "personal_vault/projects/demo/reference/keep.md"
            vault.write_document(
                path=path,
                title="Keep",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=3))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps({"verdict": "keep", "rationale": "still valid"}),
            ):
                result = sagwan_loop._curate_maintenance(force=True)

            doc = vault.load_document(path)
            self.assertEqual(result["verdict"], "keep")
            self.assertTrue(str(doc.frontmatter.get("last_maintained_at") or "").strip())
            self.assertEqual(doc.frontmatter.get("last_maintenance_verdict"), "keep")

    def test_maintenance_revise_rewrites_body(self) -> None:
        with _temp_vault_env():
            path = "personal_vault/projects/demo/reference/revise.md"
            new_body = _capsule_body(sources="- https://example.com/revised")
            vault.write_document(
                path=path,
                title="Revise",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=3))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps({"verdict": "revise", "rationale": "tighten body", "new_body": new_body}),
            ):
                result = sagwan_loop._curate_maintenance(force=True)

            doc = vault.load_document(path)
            self.assertEqual(result["status"], "revised")
            self.assertEqual(doc.body, new_body)
            self.assertEqual(doc.frontmatter.get("last_maintenance_verdict"), "revise")

    def test_maintenance_supersede_creates_new_capsule_and_links_parent(self) -> None:
        with _temp_vault_env():
            path = "personal_vault/projects/demo/reference/supersede.md"
            vault.write_document(
                path=path,
                title="Supersede Me",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=3))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps(
                    {
                        "verdict": "supersede",
                        "rationale": "new version",
                        "new_title": "Supersede Me v2",
                        "new_body": _capsule_body(sources="- https://example.com/v2"),
                    }
                ),
            ):
                result = sagwan_loop._curate_maintenance(force=True)

            parent = vault.load_document(path)
            child = vault.load_document(result["new_path"])
            self.assertEqual(parent.frontmatter.get("superseded_by"), child.path)
            self.assertEqual(child.frontmatter.get("supersedes"), parent.path)

    def test_maintenance_merge_marks_parent_merged_into_target(self) -> None:
        with _temp_vault_env():
            path = "personal_vault/projects/demo/reference/merge-me.md"
            target = "personal_vault/projects/demo/reference/merge-target.md"
            vault.write_document(
                path=target,
                title="Target",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=1)), "last_maintained_at": sagwan_loop._now_iso()},
                allow_owner_change=True,
            )
            vault.write_document(
                path=path,
                title="Merge Me",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=4))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps({"verdict": "merge", "rationale": "duplicate container", "merge_into": target}),
            ):
                result = sagwan_loop._curate_maintenance(force=True)

            doc = vault.load_document(path)
            self.assertEqual(result["verdict"], "merge")
            self.assertEqual(doc.frontmatter.get("superseded_by"), target)
            self.assertEqual(doc.frontmatter.get("claim_review_status"), "merged")

    def test_maintenance_archive_marks_note_private_and_archived(self) -> None:
        with _temp_vault_env():
            path = "personal_vault/projects/demo/reference/archive-me.md"
            vault.write_document(
                path=path,
                title="Archive Me",
                kind="capsule",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(days=5))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps({"verdict": "archive", "rationale": "obsolete"}),
            ):
                result = sagwan_loop._curate_maintenance(force=True)

            doc = vault.load_document(path)
            self.assertEqual(result["status"], "archived")
            self.assertEqual(doc.frontmatter.get("status"), "archived")
            self.assertEqual(doc.frontmatter.get("visibility"), "private")

    def test_conflict_stage_creates_dispute_review_for_new_candidate(self) -> None:
        with _temp_vault_env():
            candidate = "personal_vault/projects/demo/reference/new-claim.md"
            target = "personal_vault/projects/demo/reference/existing-claim.md"
            now = datetime.now(UTC)
            vault.write_document(
                path=target,
                title="Existing",
                kind="claim",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(now - timedelta(hours=2)), "conflict_check_at": sagwan_loop._now_iso()},
                allow_owner_change=True,
            )
            vault.write_document(
                path=candidate,
                title="New",
                kind="claim",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(now - timedelta(minutes=30))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop,
                "_invoke_for_stage",
                return_value=json.dumps({"verdict": "conflict", "target_path": target, "rationale": "claims disagree"}),
            ), mock.patch.object(mcp_server, "_post_internal_review", return_value={"status": "created"}) as review:
                result = sagwan_loop._curate_detect_conflicts()

            doc = vault.load_document(candidate)
            self.assertEqual(result["verdict"], "conflict")
            self.assertEqual(doc.frontmatter.get("conflict_status"), "flagged")
            review.assert_called_once()
            self.assertEqual(review.call_args.kwargs["evidence_paths"], [candidate])

    def test_research_gap_publication_judgment_applies_all_three_statuses(self) -> None:
        for publication_status in ("published", "requested", "none"):
            with self.subTest(publication_status=publication_status):
                with _temp_vault_env():
                    settings = _default_stage_settings()

                    def fake_stage(stage: str, prompt: str, **kwargs):
                        if stage == "research_selection":
                            return json.dumps(
                                {
                                    "topic": "Modal accessibility",
                                    "queries": ["modal accessibility aria"],
                                    "rationale": "gap",
                                    "target_capsule_title": "Modal Accessibility Capsule",
                                }
                            )
                        if stage == "research":
                            return _capsule_body()
                        if stage == "publication_judge":
                            return json.dumps({"publication_status": publication_status, "rationale": f"{publication_status} rationale"})
                        raise AssertionError(stage)

                    with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                        sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}
                    ), mock.patch.object(
                        sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}
                    ), mock.patch.object(
                        sagwan_loop, "recent_memory_tail", return_value=""
                    ), mock.patch.object(
                        sagwan_loop, "_invoke_for_stage", side_effect=fake_stage
                    ), mock.patch.object(
                        sagwan_loop, "_invoke_claude_cli_with_tools", return_value=json.dumps({"verdict": "proceed", "rationale": "ok"})
                    ):
                        result = sagwan_loop._curate_research_gaps(force=True)

                    doc = vault.load_document(result["capsule_path"])
                    self.assertEqual(result["publication_status"], publication_status)
                    self.assertEqual(doc.frontmatter.get("publication_status"), publication_status)
                    if publication_status == "published":
                        self.assertEqual(doc.frontmatter.get("visibility"), "public")
                        self.assertEqual(doc.frontmatter.get("owner"), "sagwan")
                    else:
                        self.assertEqual(doc.frontmatter.get("visibility"), "private")

    def test_distill_runs_when_cooldown_expired_and_enough_episodes(self) -> None:
        with _temp_vault_env():
            distilled_path = "personal_vault/projects/ops/librarian/memory/Sagwan Distilled Memory.md"
            vault.write_document(
                path=distilled_path,
                title="Sagwan Distilled Memory",
                kind="reference",
                project="ops/librarian",
                body="## Summary\nExisting.\n",
                metadata={"last_distilled_at": _iso(datetime.now(UTC) - timedelta(hours=7)), "owner": "sagwan"},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()
            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop, "_count_new_memory_episodes", return_value=7
            ), mock.patch.object(
                sagwan_loop, "distill_memory", return_value={"status": "ok", "new_episodes": 7}
            ) as distill:
                result = sagwan_loop._maybe_distill_sagwan()

            self.assertEqual(result["status"], "ok")
            self.assertTrue(distill.called)
            self.assertTrue(distill.call_args.kwargs["force"])

    def test_smoke_temp_vault_all_new_stages_run_with_mock_llm(self) -> None:
        with _temp_vault_env():
            note_path = "personal_vault/projects/demo/reference/smoke-maintenance.md"
            target_path = "personal_vault/projects/demo/reference/smoke-target.md"
            vault.write_document(
                path=target_path,
                title="Target",
                kind="claim",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(hours=3)), "conflict_check_at": sagwan_loop._now_iso()},
                allow_owner_change=True,
            )
            vault.write_document(
                path=note_path,
                title="Smoke",
                kind="claim",
                project="demo",
                body=_capsule_body(),
                metadata={"owner": "sagwan", "created_at": _iso(datetime.now(UTC) - timedelta(hours=2))},
                allow_owner_change=True,
            )
            settings = _default_stage_settings()

            def fake_stage(stage: str, prompt: str, **kwargs):
                if stage == "maintenance":
                    return json.dumps({"verdict": "keep", "rationale": "ok"})
                if stage == "conflict":
                    return json.dumps({"verdict": "duplicate", "target_path": target_path, "rationale": "same claim"})
                if stage == "research_selection":
                    return json.dumps(
                        {
                            "topic": "Smoke topic",
                            "queries": ["smoke topic"],
                            "rationale": "gap",
                            "target_capsule_title": "Smoke Topic Capsule",
                        }
                    )
                if stage == "research":
                    return _capsule_body()
                if stage == "publication_judge":
                    return json.dumps({"publication_status": "requested", "rationale": "review first"})
                raise AssertionError(stage)

            with mock.patch.object(sagwan_loop, "load_sagwan_settings", return_value=settings), mock.patch.object(
                sagwan_loop, "_invoke_for_stage", side_effect=fake_stage
            ), mock.patch.object(
                sagwan_loop, "_invoke_claude_cli_with_tools", return_value=json.dumps({"verdict": "proceed", "rationale": "ok"})
            ), mock.patch.object(
                sagwan_loop, "_inventory_knowledge_state", return_value={"total_capsules": 0, "total_claims": 0, "top_thin": [], "recent_gap_queries": []}
            ), mock.patch.object(
                sagwan_loop, "before_task_context", return_value={"distilled": "", "combined": ""}
            ), mock.patch.object(
                sagwan_loop, "recent_memory_tail", return_value=""
            ), mock.patch.object(mcp_server, "_post_internal_review", return_value={"status": "created"}):
                maintenance = sagwan_loop._curate_maintenance(force=True)
                conflict = sagwan_loop._curate_detect_conflicts()
                research = sagwan_loop._curate_research_gaps(force=True)

            self.assertEqual(maintenance["status"], "ok")
            self.assertEqual(conflict["verdict"], "duplicate")
            self.assertEqual(research["publication_status"], "requested")
