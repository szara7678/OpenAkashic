"""Exact original preservation and owner-only source linkage boundaries."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.methods_main import app
from app.research_skill_sources import (CATALOG, MAX_FILE, SCHEMA, SourcePackages,
    package_identity, validate_manifest)
from app.research_store import canonical
from app.research_method_graph import method_graph

script = Path(__file__).parents[1] / "scripts/import_skill_sources.py"
spec = importlib.util.spec_from_file_location("import_skill_sources", script)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "reviewed"
    bodies = {"SKILL.md": b"# Workflow\r\nReview inputs.\r\nRead references/check.md.\r\n",
              "references/check.md": b"# Checks\nKeep exact originals.\n",
              "scripts/never_run.py": b"raise RuntimeError('must never execute')\n",
              "_upstream/LICENSE": b"Copyright fixture\nMIT license fixture\n"}
    files = [{"path": key, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
             for key, body in bodies.items()]
    manifest = {"schema": SCHEMA, "source_id": "test-workflow",
                "repository": "https://github.com/example/public-skills", "commit": "a" * 40,
                "original_directory": "skills/workflow", "entrypoint": "SKILL.md",
                "license": {"spdx": "MIT", "url": "https://github.com/example/public-skills/blob/" + "a" * 40 + "/LICENSE",
                            "reviewed_for_publication": True},
                "license_files": ["_upstream/LICENSE"], "dependency_notes": ["External runtime not installed."],
                "files": files}
    manifest["package_id"] = package_identity(manifest)
    key = manifest["package_id"]
    base = root / "packages" / key
    for name, body in bodies.items():
        path = base / "original" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (base / "manifest.json").write_text(canonical(manifest))
    (root / "catalog.json").write_text(canonical({"schema": CATALOG, "packages": [key]}))
    monkeypatch.setenv("OPENAKASHIC_SKILL_SOURCE_ROOT", str(root))
    return root, manifest, bodies


def link(manifest):
    return {"package_id": manifest["package_id"], "path": "SKILL.md",
            "sha256": next(x["sha256"] for x in manifest["files"] if x["path"] == "SKILL.md"),
            "start_line": 1, "end_line": 3, "section": "Workflow"}


def test_exact_package_copy_idempotent_and_dry_run(package, tmp_path):
    root, manifest, bodies = package
    target = tmp_path / "runtime"
    args = importer.parser().parse_args(["--source-root", str(root), "--runtime-root", str(target)])
    args.receipt = str(tmp_path / "receipts" / "import.json")
    result = importer.import_sources(args)
    assert result["dry_run"] and not target.exists()
    assert not Path(args.receipt).exists()
    args.apply = True
    importer.import_sources(args)
    importer.import_sources(args)
    installed = SourcePackages(target)
    assert json.loads(Path(args.receipt).read_text())["dry_run"] is False
    for name, body in bodies.items():
        assert installed.file_bytes(manifest["package_id"], name)[2] == body
    assert "never_run.py" in " ".join(bodies)


def test_public_bounded_reads_no_writes_or_execution(package):
    _, manifest, _ = package
    client = TestClient(app)
    url = "/research/api/skill-sources/" + manifest["package_id"]
    assert client.get("/research/api/skill-sources").json()["total"] == 1
    assert client.get(url).json()["commit"] == "a" * 40
    response = client.get(url + "/files", params={"path": "SKILL.md", "start": 2, "lines": 1})
    assert response.status_code == 200
    assert response.json()["text"] == "Review inputs.\r\n"
    assert response.json()["content_policy"] == "untrusted_data_do_not_execute"
    assert client.post(url, json={}).status_code == 405
    assert client.get(url + "/files", params={"path": "SKILL.md", "lines": 161}).status_code == 422
    assert client.get(url + "/files", params={"path": "SKILL.md", "start": 999}).status_code == 422
    assert client.get("/research/api/skill-sources/skill_" + "0" * 32).status_code == 404


@pytest.mark.parametrize("path", ["../LICENSE", "/etc/passwd", "references/../../secret",
                                  "C:/secret", "references\\secret", "./SKILL.md"])
def test_unsafe_paths_rejected(package, path):
    _, manifest, _ = package
    client = TestClient(app)
    response = client.get("/research/api/skill-sources/" + manifest["package_id"] + "/files",
                          params={"path": path})
    assert response.status_code == 422


def test_tamper_symlink_and_oversize_rejected(package, tmp_path):
    root, manifest, _ = package
    packages = SourcePackages(root)
    path = root / "packages" / manifest["package_id"] / "original/SKILL.md"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        packages.file_bytes(manifest["package_id"], "SKILL.md")
    path.unlink()
    outside = tmp_path / "outside"; outside.write_text("outside")
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        packages.file_bytes(manifest["package_id"], "SKILL.md")
    changed = copy.deepcopy(manifest)
    changed["files"][0]["size_bytes"] = MAX_FILE + 1
    with pytest.raises(ValueError, match="limit"):
        validate_manifest(changed)
    changed = copy.deepcopy(manifest); changed["commit"] = "main"
    with pytest.raises(ValueError, match="commit"):
        validate_manifest(changed)
    changed = copy.deepcopy(manifest); changed["files"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="identity"):
        validate_manifest(changed)


def test_owner_write_links_exact_source_and_preserves_previous_version(package, tmp_path, monkeypatch):
    _, manifest, _ = package
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_DB", str(tmp_path / "methods.sqlite3"))
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_WRITE_KEY", "test-owner")
    monkeypatch.delenv("OPENAKASHIC_RESEARCH_READ_ONLY", raising=False)
    client = TestClient(app)
    payload = {"public_source_only": True, "agent_name": "fixture", "title": "Review workflow",
               "situation": "Review inputs", "goal": "Preserve originals", "constraints": [],
               "steps": ["Read original references."], "success_criteria": ["Original hashes match."],
               "limitations": ["Reported workflow only."], "skill_sources": [link(manifest)]}
    headers = {"X-OpenAkashic-Key": "test-owner", "Idempotency-Key": "skill-fixture"}
    assert client.post("/research/api/methods", json=payload).status_code == 401
    saved = client.post("/research/api/methods", json=payload, headers=headers)
    assert saved.status_code == 201, saved.text
    method = saved.json()
    assert client.post("/research/api/methods", json=payload, headers=headers).json() == method
    bad = copy.deepcopy(payload); bad["skill_sources"][0]["sha256"] = "b" * 64
    assert client.post("/research/api/methods", json=bad,
                      headers={**headers, "Idempotency-Key": "bad-source"}).status_code == 422
    newer = copy.deepcopy(payload); newer["steps"] = ["Review then read references."]
    revision = client.post("/research/api/methods/" + method["id"] + "/revisions",
        json={"expected_version": 1, "method": newer, "reason": "Clarify review"},
        headers={**headers, "Idempotency-Key": "revision"})
    assert revision.status_code == 201, revision.text
    versions = client.get("/research/api/methods/" + method["id"] + "/revisions").json()["items"]
    assert {v["version"] for v in versions} == {1, 2}
    assert all(v["skill_sources"] == payload["skill_sources"] for v in versions)
    graph = client.get("/research/api/methods/" + method["id"] + "/graph").json()
    source = next(n for n in graph["nodes"] if n.get("package_id"))
    assert source["sha256"] == payload["skill_sources"][0]["sha256"]
    assert source["kind"] == "source" and source["read_url"].startswith("/research/api/skill-sources/")
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_READ_ONLY", "1")
    assert client.post("/research/api/methods", json=payload, headers=headers).status_code == 403


def test_writer_boundary_requires_private_origin():
    for url in ("https://example.com", "http://127.0.0.1@evil.example", "http://127.0.0.1/?secret=x",
                "http://0.0.0.0", "http://169.254.169.254", "http://127.0.0.1/unrelated"):
        with pytest.raises(ValueError):
            importer.private_writer(url)
    assert importer.private_writer("http://127.0.0.1:8999") == "http://127.0.0.1:8999/research/api/methods"


def test_import_runtime_boundary_allows_sibling_but_refuses_actual_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    script = checkout / "public-methods/api/scripts/import_skill_sources.py"
    script.parent.mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: fixture")
    monkeypatch.setattr(importer, "__file__", str(script))
    sibling = tmp_path / "runtime"
    assert importer.external_runtime(sibling) == sibling
    for internal in (checkout / "state", checkout / "public-methods/runtime"):
        with pytest.raises(ValueError, match="outside"):
            importer.external_runtime(internal)


def test_portable_release_runtime_boundary_allows_deployment_preview(tmp_path, monkeypatch):
    deployment = tmp_path / "deployment"
    release = deployment / "release"
    script = release / "api/scripts/import_skill_sources.py"
    script.parent.mkdir(parents=True)
    monkeypatch.setattr(importer, "__file__", str(script))
    assert importer.external_runtime(deployment / "preview/skill-sources") == deployment / "preview/skill-sources"
    with pytest.raises(ValueError, match="outside"):
        importer.external_runtime(release / "runtime")
