from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
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


class ClaimGuardrailPassTests(unittest.TestCase):
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

    def _write_claim(self, path: str, body: str, title: str = "Guardrail Claim") -> None:
        self.vault.write_document(
            path=path,
            title=title,
            kind="claim",
            project="personal/openakashic",
            body=body,
            metadata={
                "owner": "tester",
                "visibility": "private",
                "publication_status": "requested",
            },
        )

    def test_pass_case(self) -> None:
        self.assertEqual(self.vault._normalize_publication_status("guardrail_passed"), "guardrail_passed")
        path = "personal_vault/projects/personal/openakashic/reference/pass.md"
        self._write_claim(
            path,
            "## Claim\nOpenAkashic claim notes start as private review drafts.\n\n## Evidence Links\n- PR1 behavior note\n",
        )
        self.sagwan_loop._ensure_guardrail_log_document()
        log_doc = self.vault.load_document(self.sagwan_loop._GUARDRAIL_LOG_PATH)
        log_fm = dict(log_doc.frontmatter)
        log_fm["last_run_at"] = (
            datetime.now(UTC) - timedelta(hours=2)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.vault.write_document(
            path=log_doc.path,
            body=log_doc.body,
            metadata=log_fm,
            allow_owner_change=True,
        )
        llm_response = json.dumps({
            "results": [{"path": path, "decision": "pass", "reason": "neutral claim with stated basis"}]
        })

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response))
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

        doc = self.vault.load_document(path)
        self.assertEqual(result["claim_guardrail"]["status"], "ok")
        self.assertEqual(doc.frontmatter["publication_status"], "guardrail_passed")
        self.assertEqual(doc.frontmatter["guardrail_reason"], "neutral claim with stated basis")

    def test_reject_by_llm(self) -> None:
        self.assertEqual(self.vault._normalize_publication_status("guardrail_rejected"), "guardrail_rejected")
        path = "personal_vault/projects/personal/openakashic/reference/reject.md"
        self._write_claim(path, "## Claim\nThis vague thing is definitely always true.\n")
        llm_response = json.dumps({
            "results": [{"path": path, "decision": "reject", "reason": "no evidence or basis"}]
        })

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage", return_value=llm_response):
            claims = self.sagwan_loop.get_pending_claims(None)
            results = self.sagwan_loop._run_guardrail_pass(claims)
            self.sagwan_loop._apply_guardrail_results(results, None)

        doc = self.vault.load_document(path)
        self.assertEqual(doc.frontmatter["publication_status"], "guardrail_rejected")
        self.assertEqual(doc.frontmatter["guardrail_reject_reason"], "no evidence or basis")

    def test_reject_by_secret_pattern(self) -> None:
        path = "personal_vault/projects/personal/openakashic/reference/secret.md"
        self._write_claim(path, "## Claim\nThe test credential is sk-abcdef0123456789ABCDEF.\n")

        with mock.patch.object(self.sagwan_loop, "_invoke_for_stage") as llm:
            claims = self.sagwan_loop.get_pending_claims(None)
            results = self.sagwan_loop._run_guardrail_pass(claims)
            self.sagwan_loop._apply_guardrail_results(results, None)

        llm.assert_not_called()
        doc = self.vault.load_document(path)
        self.assertEqual(doc.frontmatter["publication_status"], "guardrail_rejected")
        self.assertIn("secret pattern detected", doc.frontmatter["guardrail_reject_reason"])


if __name__ == "__main__":
    unittest.main()
