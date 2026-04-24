from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import librarian, sagwan_loop


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


if __name__ == "__main__":
    unittest.main()
