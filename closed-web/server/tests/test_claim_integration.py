from __future__ import annotations

from contextlib import ExitStack
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class ClaimIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
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
            "CLOSED_AKASHIC_DEFAULT_NOTE_OWNER": "tester",
        }
        self._env_patcher = mock.patch.dict(os.environ, env, clear=False)
        self._env_patcher.start()

        from app import config

        config.get_settings.cache_clear()
        from app import sagwan_loop, vault

        vault.invalidate_claim_id_cache()
        self.sagwan_loop = sagwan_loop
        self.vault = vault

    def tearDown(self) -> None:
        self._env_patcher.stop()
        from app import config

        config.get_settings.cache_clear()
        self.vault.invalidate_claim_id_cache()
        self.sagwan_loop._LLM_CALL_HISTORY[:] = []
        self._tmp.cleanup()

    def _write_claim(self, path: str, body: str, title: str = "Integration Claim") -> None:
        self.vault.write_document(
            path=path,
            title=title,
            kind="claim",
            project="personal/openakashic",
            body=body,
            tags=["integration", "capsule"],
            metadata={
                "owner": "tester",
                "visibility": "private",
                "publication_status": "guardrail_passed",
            },
        )

    def _write_capsule(self, path: str, body: str = "## Summary\nExisting integration capsule.\n") -> None:
        self.vault.write_document(
            path=path,
            title="Existing Integration Capsule",
            kind="capsule",
            project="ops/librarian",
            body=body,
            tags=["integration", "capsule"],
            metadata={
                "owner": "sagwan",
                "visibility": "public",
                "publication_status": "published",
                "evidence_paths": [],
            },
            allow_owner_change=True,
        )

    def test_link_adds_claim_as_capsule_evidence(self) -> None:
        claim_path = "personal_vault/projects/personal/openakashic/reference/link-claim.md"
        capsule_path = "personal_vault/projects/ops/librarian/capsules/link-target.md"
        self._write_claim(claim_path, "## Claim\nIntegration claims can be linked as evidence.\n")
        self._write_capsule(capsule_path)
        llm_response = json.dumps({
            "results": [{
                "claim_path": claim_path,
                "action": "LINK",
                "target_path": capsule_path,
                "rationale": "same integration topic",
            }]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        capsule = self.vault.load_document(capsule_path)
        self.assertEqual(result["linked"], 1)
        self.assertEqual(claim.frontmatter["publication_status"], "published")
        self.assertEqual(claim.frontmatter["integration_action"], "link")
        self.assertIn(claim_path, capsule.frontmatter["evidence_paths"])
        self.assertIn("Sagwan Claim Link", capsule.body)

    def test_contribute_appends_agent_contribution_to_capsule(self) -> None:
        claim_path = "personal_vault/projects/personal/openakashic/reference/contribute-claim.md"
        capsule_path = "personal_vault/projects/ops/librarian/capsules/contribute-target.md"
        self._write_claim(claim_path, "## Claim\nClaims can supplement capsule caveats.\n")
        self._write_capsule(capsule_path)
        contribution = "## Practical Use\nUse the claim as an extra caveat when integrating capsules."
        llm_response = json.dumps({
            "results": [{
                "claim_path": claim_path,
                "action": "CONTRIBUTE",
                "target_path": capsule_path,
                "contribution": contribution,
                "rationale": "adds a reusable capsule caveat",
            }]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        capsule = self.vault.load_document(capsule_path)
        self.assertEqual(result["contributed"], 1)
        self.assertEqual(claim.frontmatter["publication_status"], "published")
        self.assertIn(claim_path, capsule.frontmatter["evidence_paths"])
        self.assertIn("Use the claim as an extra caveat", capsule.body)

    def test_create_writes_new_capsule_from_generalizable_claim(self) -> None:
        claim_path = "personal_vault/projects/personal/openakashic/reference/create-claim.md"
        self._write_claim(claim_path, "## Claim\nGuardrail-passed claims can become capsules when generalizable.\n")
        llm_response = json.dumps({
            "results": [{
                "claim_path": claim_path,
                "action": "CREATE",
                "title": "Claim Integration Pattern",
                "body": "## Summary\nClaim integration creates capsules for reusable patterns.\n\n## Evidence Links\n- claim source",
                "rationale": "general reusable integration pattern",
            }]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        capsule_path = result["created_paths"][0]
        capsule = self.vault.load_document(capsule_path)
        self.assertEqual(result["created"], 1)
        self.assertEqual(claim.frontmatter["publication_status"], "published")
        self.assertEqual(claim.frontmatter["integrated_target_path"], capsule_path)
        self.assertEqual(capsule.frontmatter["kind"], "capsule")
        self.assertEqual(capsule.frontmatter["publication_status"], "requested")
        self.assertEqual(capsule.frontmatter["visibility"], "private")
        self.assertEqual(capsule.frontmatter["source_claim_paths"], [claim_path])
        self.assertIn("Claim integration creates capsules", capsule.body)

    def test_defer_marks_claim_pending_integration(self) -> None:
        self.assertEqual(self.vault._normalize_publication_status("pending_integration"), "pending_integration")
        claim_path = "personal_vault/projects/personal/openakashic/reference/defer-claim.md"
        self._write_claim(claim_path, "## Claim\nA narrow claim needs more related evidence before integration.\n")
        llm_response = json.dumps({
            "results": [{
                "claim_path": claim_path,
                "action": "DEFER",
                "rationale": "needs a stronger related capsule cluster",
            }]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(claim.frontmatter["publication_status"], "pending_integration")
        self.assertIn("stronger related capsule", claim.frontmatter["integration_defer_reason"])

    def test_pending_integration_claim_is_retried(self) -> None:
        claim_path = "personal_vault/projects/personal/openakashic/reference/retry-claim.md"
        capsule_path = "personal_vault/projects/ops/librarian/capsules/retry-target.md"
        self._write_claim(claim_path, "## Claim\nPending integration claims should be retried.\n")
        claim = self.vault.load_document(claim_path)
        claim_fm = dict(claim.frontmatter)
        claim_fm["publication_status"] = "pending_integration"
        self.vault.write_document(path=claim_path, body=claim.body, metadata=claim_fm)
        self._write_capsule(capsule_path)
        llm_response = json.dumps({
            "results": [{
                "claim_path": claim_path,
                "action": "LINK",
                "target_path": capsule_path,
                "rationale": "retry found a related capsule",
            }]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        capsule = self.vault.load_document(capsule_path)
        self.assertEqual(result["linked"], 1)
        self.assertEqual(claim.frontmatter["publication_status"], "published")
        self.assertIn(claim_path, capsule.frontmatter["evidence_paths"])

    def test_integration_parse_failure_preserves_claim_for_retry(self) -> None:
        claim_path = "personal_vault/projects/personal/openakashic/reference/integration-parse-failure.md"
        self._write_claim(claim_path, "## Claim\nInvalid integration JSON should leave state unchanged.\n")

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value="not json"):
            with self.assertLogs("app.sagwan_loop", level="WARNING") as logs:
                result = self.sagwan_loop._run_claim_integration_cycle(limit=10)

        claim = self.vault.load_document(claim_path)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(claim.frontmatter["publication_status"], "guardrail_passed")
        self.assertTrue(any("claim integration response parse failed" in line for line in logs.output))

    def test_curation_cycle_registers_integration_after_guardrail(self) -> None:
        order: list[str] = []

        def guardrail() -> dict[str, str]:
            order.append("guardrail")
            return {"status": "skipped"}

        def integration() -> dict[str, str]:
            order.append("integration")
            return {"status": "skipped"}

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.sagwan_loop, "_maybe_run_claim_guardrail_cycle", side_effect=guardrail))
            stack.enter_context(mock.patch.object(self.sagwan_loop, "_maybe_run_claim_integration_cycle", side_effect=integration))
            for name, value in {
                "_curate_derive_and_sync": {"sync_enqueued": False},
                "_curate_revalidate_published": {"checked": 0, "revalidated": 0},
                "_curate_ingest_feeds": {"enqueued": 0},
                "_curate_generate_capsules": {"generated": 0},
                "_curate_detect_conflicts": {"checked": 0, "flagged": 0},
                "_curate_enqueue_signal_scans": {"enqueued": 0},
                "_curate_propose_topics": {"status": "skipped"},
                "_curate_system_health": {"status": "skipped"},
                "_curate_research_gaps": {"status": "skipped"},
                "_curate_consolidate_reviews": {"status": "skipped"},
                "_curate_maintenance": {"status": "skipped"},
                "_maybe_distill_sagwan": {"status": "skipped"},
                "_curate_self_improve": {"status": "skipped"},
                "_curate_autonomous_sweep": {"status": "skipped"},
            }.items():
                stack.enter_context(mock.patch.object(self.sagwan_loop, name, return_value=value))
            stack.enter_context(mock.patch.object(self.sagwan_loop, "_write_llm_telemetry_cycle", return_value=None))
            stack.enter_context(mock.patch.object(self.sagwan_loop, "remember", return_value=None))
            result = self.sagwan_loop.run_sagwan_curation_cycle(reason="test")

        self.assertEqual(order[:2], ["guardrail", "integration"])
        self.assertEqual(result["claim_integration"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
