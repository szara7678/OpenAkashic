from __future__ import annotations

import json
import sys
from pathlib import Path

from app import system_access


def _use_workspace(tmp_path: Path, monkeypatch) -> Path:
    workspace = tmp_path / "workspace"
    vault = tmp_path / "vault"
    workspace.mkdir()
    monkeypatch.setattr(system_access, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(system_access, "vault_root", lambda: vault)
    return workspace


def _audit_log() -> str:
    path = system_access.vault_root() / system_access.AUDIT_LOG_RELATIVE_PATH
    return path.read_text(encoding="utf-8")


def test_run_shell_returns_stdout_stderr_and_exit_code(tmp_path, monkeypatch):
    workspace = _use_workspace(tmp_path, monkeypatch)

    result = json.loads(system_access.execute_system_tool("run_shell", {"command": "printf hello"}))

    assert result["stdout"] == "hello"
    assert result["stderr"] == ""
    assert result["exit_code"] == 0
    log = _audit_log()
    assert "run_shell" in log
    assert "printf hello" in log


def test_run_shell_reports_timeout(tmp_path, monkeypatch):
    workspace = _use_workspace(tmp_path, monkeypatch)
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'

    result = json.loads(
        system_access.execute_system_tool("run_shell", {"command": command, "timeout_secs": 1})
    )

    assert result["exit_code"] == -1
    assert "timed out" in result["error"]
    assert "run_shell" in _audit_log()


def test_path_traversal_is_blocked(tmp_path, monkeypatch):
    workspace = _use_workspace(tmp_path, monkeypatch)

    result = json.loads(system_access.execute_system_tool("read_workspace_file", {"path": "../outside.txt"}))

    assert "inside /workspace" in result["error"]
    assert "read_workspace_file" in _audit_log()


def test_write_then_read_workspace_file_roundtrip(tmp_path, monkeypatch):
    workspace = _use_workspace(tmp_path, monkeypatch)

    write_result = json.loads(
        system_access.execute_system_tool(
            "write_workspace_file",
            {"path": "notes/example.txt", "content": "roundtrip text"},
        )
    )
    read_result = system_access.execute_system_tool("read_workspace_file", {"path": "notes/example.txt"})

    assert write_result["status"] == "ok"
    assert read_result == "roundtrip text"
    assert (workspace / "notes" / "example.txt").read_text(encoding="utf-8") == "roundtrip text"
    log = _audit_log()
    assert "write_workspace_file" in log
    assert "read_workspace_file" in log
    assert '"chars": 14' in log


def test_list_workspace_dir_returns_sorted_listing(tmp_path, monkeypatch):
    workspace = _use_workspace(tmp_path, monkeypatch)
    (workspace / "z-file.txt").write_text("z", encoding="utf-8")
    (workspace / "a-dir").mkdir()

    result = json.loads(system_access.execute_system_tool("list_workspace_dir", {}))

    names = [entry["name"] for entry in result["entries"]]
    assert names == ["a-dir", "z-file.txt"]
    assert result["entries"][0]["type"] == "dir"
    assert "list_workspace_dir" in _audit_log()
