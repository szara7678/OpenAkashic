"""Tiny mock-network tests; no live source download, install or process execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

from app.research_skill_sources import CATALOG, SCHEMA, package_identity
from app.research_store import canonical

script = Path(__file__).with_name("fetch_skill_sources.py")
if not script.exists():
    script = Path(__file__).parents[1] / "scripts/fetch_skill_sources.py"
spec = importlib.util.spec_from_file_location("fetch_skill_sources", script)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


@pytest.fixture
def reviewed(tmp_path):
    root = tmp_path / "public-examples"
    bodies = {"SKILL.md": b"# Review\r\nRead references/check.md.\r\n",
              "references/check.md": b"# Check\nKeep exact bytes.\n",
              "_upstream/LICENSE": b"MIT public fixture license\n"}
    entries = []
    for path, body in bodies.items():
        entries.append({"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body),
                        "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
                        "original_path": "skills/review/" + path,
                        "url": "https://ignored.example/never-fetch"})
    manifest = {"schema": SCHEMA, "source_id": "public-review", "repository": "https://github.com/example/skills",
                "commit": "a" * 40, "original_directory": "skills/review", "entrypoint": "SKILL.md",
                "license": {"spdx": "MIT", "url": "https://github.com/example/skills/blob/" + "a" * 40 + "/LICENSE",
                            "reviewed_for_publication": True},
                "license_files": ["_upstream/LICENSE"], "dependency_notes": ["No dependencies installed."],
                "files": entries}
    manifest["package_id"] = package_identity(manifest)
    key = manifest["package_id"]
    folder = root / "packages" / key
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(canonical(manifest))
    catalog = root / "catalog.json"
    catalog.write_text(canonical({"schema": CATALOG, "packages": [key]}))
    output = tmp_path / "external-runtime"
    def fake(url, expected_size):
        prefix = "https://raw.githubusercontent.com/example/skills/" + "a" * 40 + "/skills/review/"
        assert url.startswith(prefix)
        path = url[len(prefix):]
        return bodies[path]
    return catalog, manifest, bodies, output, fake


def test_dry_run_has_no_network_or_output(reviewed):
    catalog, _, _, output, _ = reviewed
    def forbidden(*args):
        raise AssertionError("dry-run must not fetch")
    result = fetch.reconstruct(catalog, output, fetcher=forbidden)
    assert result["dry_run"] and result["files_total"] == 3 and not output.exists()


def test_exact_bytes_pinned_host_and_no_overwrite_on_resume(reviewed):
    catalog, manifest, bodies, output, fake = reviewed
    result = fetch.reconstruct(catalog, output, apply=True, fetcher=fake)
    assert result["status"] == "complete" and result["files_downloaded"] == 3
    for path, body in bodies.items():
        assert (output / "packages" / manifest["package_id"] / "original" / path).read_bytes() == body
    def forbidden(*args):
        raise AssertionError("completed originals must be reused after verification")
    resumed = fetch.reconstruct(catalog, output, apply=True, fetcher=forbidden)
    assert resumed["files_present"] == 3 and resumed["files_downloaded"] == 0
    assert json.loads((output / "fetch-receipt.json").read_text())["status"] == "complete"


def test_partial_receipt_and_resume_only_missing_files(reviewed):
    catalog, _, _, output, fake = reviewed
    calls = []
    def partial(url, size):
        calls.append(url)
        if len(calls) == 2:
            raise ValueError("mock network failure")
        return fake(url, size)
    with pytest.raises(ValueError, match="mock"):
        fetch.reconstruct(catalog, output, apply=True, fetcher=partial)
    receipt = json.loads((output / "fetch-receipt.json").read_text())
    assert receipt["status"] == "partial" and receipt["files_downloaded"] == 1
    calls.clear()
    def missing_only(url, size):
        calls.append(url)
        return fake(url, size)
    final = fetch.reconstruct(catalog, output, apply=True, fetcher=missing_only)
    assert final["files_present"] == 1 and len(calls) == 2


def test_corrupt_download_never_written_and_corrupt_existing_refused(reviewed):
    catalog, manifest, _, output, fake = reviewed
    with pytest.raises(ValueError, match="mismatch"):
        fetch.reconstruct(catalog, output, apply=True, fetcher=lambda *_: b"corrupt")
    original = output / "packages" / manifest["package_id"] / "original/SKILL.md"
    assert not original.exists()
    fetch.reconstruct(catalog, output, apply=True, fetcher=fake)
    original.write_bytes(b"corrupt existing")
    with pytest.raises(ValueError, match="mismatch"):
        fetch.reconstruct(catalog, output, apply=True, fetcher=lambda *_: pytest.fail("must not fetch"))


def test_git_output_and_symlink_destinations_refused(reviewed, tmp_path):
    catalog, manifest, _, output, fake = reviewed
    repository = tmp_path / "repo"
    repository.mkdir(); (repository / ".git").write_text("gitdir: inert")
    with pytest.raises(ValueError, match="outside Git"):
        fetch.reconstruct(catalog, repository / "runtime", fetcher=fake)
    source = output / "packages" / manifest["package_id"] / "original"
    source.mkdir(parents=True)
    (source / "SKILL.md").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        fetch.reconstruct(catalog, output, apply=True, fetcher=fake)


@pytest.mark.parametrize("repository", ["http://github.com/example/skills",
    "https://github.com.evil.example/example/skills", "https://owner@github.com/example/skills",
    "https://github.com/example/skills?token=ignored", "https://github.com/example/skills/tree/main"])
def test_arbitrary_hosts_auth_and_mutable_locations_refused(reviewed, repository):
    _, manifest, _, _, _ = reviewed
    altered = copy.deepcopy(manifest); altered["repository"] = repository
    with pytest.raises(ValueError):
        fetch.github_location(altered, altered["files"][0])


def test_traversal_redirect_blob_and_size_limits(reviewed):
    _, manifest, bodies, _, _ = reviewed
    entry = copy.deepcopy(manifest["files"][0]); entry["original_path"] = "../private"
    with pytest.raises(ValueError, match="unsafe"):
        fetch.github_location(manifest, entry)
    with pytest.raises(ValueError, match="redirect"):
        fetch.NoRedirect().redirect_request(None, None, 302, None, None, "https://evil.example")
    entry = copy.deepcopy(manifest["files"][0]); entry["git_blob"] = "b" * 40
    with pytest.raises(ValueError, match="blob"):
        fetch.validate_body(entry, bodies["SKILL.md"])
    with pytest.raises(ValueError, match="size"):
        fetch.validate_body(manifest["files"][0], bodies["SKILL.md"] + b"oversize")


def test_reviewed_method_plan_matches_materialized_exact_span(reviewed, tmp_path):
    catalog, manifest, _, output, fake = reviewed
    source = manifest["files"][0]
    payload = {"public_source_only": True, "agent_name": "reviewed-fixture", "title": "Review workflow",
               "situation": "Review public inputs", "goal": "Preserve source evidence",
               "constraints": [], "steps": ["Read original references."],
               "success_criteria": ["Source hashes match."], "limitations": ["Not independent verification."],
               "skill_sources": [{"package_id": manifest["package_id"], "path": "SKILL.md",
                   "sha256": source["sha256"], "start_line": 1, "end_line": 2, "section": "Review"}]}
    plan = {"schema": "public-skill-method-import-v1",
            "methods": [{"public_id": "review-method", "payload": payload}]}
    path = tmp_path / "method-proposals.json"
    path.write_text(canonical(plan))
    result = fetch.reconstruct(catalog, output, path, apply=True, fetcher=fake)
    assert result["status"] == "complete"
    assert result["methods_plan_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    payload["skill_sources"][0]["sha256"] = "c" * 64
    path.write_text(canonical(plan))
    with pytest.raises(ValueError, match="outside"):
        fetch.reconstruct(catalog, tmp_path / "invalid-plan", path, apply=True, fetcher=fake)
    payload["skill_sources"][0]["sha256"] = source["sha256"]
    payload["skill_sources"][0]["end_line"] = 99
    path.write_text(canonical(plan))
    with pytest.raises(ValueError, match="line span"):
        fetch.reconstruct(catalog, tmp_path / "invalid-span", path, apply=True, fetcher=fake)
