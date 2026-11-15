"""Reconstruct reviewed pinned public GitHub skill originals; dry-run by default."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from app.research_skill_sources import (CATALOG, MAX_FILE, MAX_PACKAGE, PACKAGE,
    SourcePackages, bounded_bytes, relative_path, safe_file, validate_manifest)
from app.research_methods import MethodRequest

MAX_PACKAGES = 20
MAX_TOTAL = 64 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("source redirects are forbidden")


def github_location(manifest, entry):
    parsed = urllib.parse.urlsplit(manifest["repository"])
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.hostname != "github.com" or
            parsed.port not in (None, 443) or parsed.username or parsed.password or
            parsed.query or parsed.fragment or len(parts) != 2 or
            any(not re.fullmatch(r"[A-Za-z0-9_.-]+", item) or item in (".", "..") for item in parts)):
        raise ValueError("public HTTPS GitHub owner/repository required")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not repository:
        raise ValueError("GitHub repository name required")
    commit = manifest["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact Git commit required")
    original = relative_path(entry.get("original_path"))
    if not re.fullmatch(r"[0-9a-f]{40}", entry.get("git_blob", "")):
        raise ValueError("exact upstream Git blob required")
    path = "/".join(urllib.parse.quote(part, safe="") for part in original.split("/"))
    return "https://raw.githubusercontent.com/" + owner + "/" + repository + "/" + commit + "/" + path


def validate_body(entry, body):
    if len(body) != entry["size_bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise ValueError("source size or SHA-256 mismatch")
    blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    if blob != entry["git_blob"]:
        raise ValueError("upstream Git blob mismatch")


def fetch_bytes(url, expected_size):
    # No inherited proxies, authentication handlers, credentials or environment access.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream",
                                                  "User-Agent": "OpenAkashic-pinned-public-source/1"})
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("unexpected public source response")
            body = response.read(min(MAX_FILE, expected_size) + 1)
            if len(body) > expected_size:
                raise ValueError("download exceeds reviewed byte size")
            return body
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("public source download failed") from None


def external_output(value):
    output = Path(value).absolute()
    for ancestor in (output, *output.parents):
        if ancestor.is_symlink():
            raise ValueError("output symlinks are forbidden")
        if (ancestor / ".git").exists():
            raise ValueError("source output must stay outside Git")
    return output


def output_path(root, relative, create=False):
    relative_path(relative)
    target = root
    for component in relative.split("/"):
        target = target / component
        if target.is_symlink():
            raise ValueError("output symlinks are forbidden")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("unsafe output path")
    if create:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Recheck every created/existing ancestor before using it.
        for ancestor in (target.parent, *target.parent.parents):
            if ancestor.is_symlink():
                raise ValueError("output symlinks are forbidden")
    return target


def existing_bytes(root, relative, expected, entry=None):
    target = output_path(root, relative)
    if not target.exists():
        return False
    if not target.is_file():
        raise ValueError("existing source destination is not a regular file")
    body = bounded_bytes(safe_file(root, relative), max(MAX_FILE, len(expected)))
    if entry is not None:
        validate_body(entry, body)
    elif body != expected:
        raise ValueError("preexisting reviewed metadata differs")
    return True


def exclusive_write(root, relative, body):
    target = output_path(root, relative, create=True)
    if target.exists():
        raise ValueError("source destination appeared during fetch; refusing overwrite")
    descriptor, temporary = tempfile.mkstemp(prefix=".skill-fetch-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        # Linking a fully written temporary file is atomic and fails if target exists.
        os.link(temporary, target, follow_symlinks=False)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def receipt_write(root, result):
    target = output_path(root, "fetch-receipt.json")
    descriptor, temporary = tempfile.mkstemp(prefix=".skill-receipt-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def reviewed_inputs(catalog_path, methods_plan=None):
    catalog_path = Path(catalog_path).absolute()
    root = catalog_path.parent
    raw = bounded_bytes(safe_file(root, catalog_path.name), 128 * 1024)
    catalog = json.loads(raw)
    ids = catalog.get("packages", [])
    if (catalog.get("schema") != CATALOG or not isinstance(ids, list) or
            not 1 <= len(ids) <= MAX_PACKAGES or
            any(not isinstance(key, str) or not re.fullmatch(PACKAGE, key) for key in ids) or
            len(set(ids)) != len(ids)):
        raise ValueError("bounded reviewed public source catalog required")
    packages, total = [], 0
    by_id = {}
    for key in ids:
        relative = "packages/" + key + "/manifest.json"
        manifest_raw = bounded_bytes(safe_file(root, relative), 1024 * 1024)
        manifest = validate_manifest(json.loads(manifest_raw))
        if manifest["package_id"] != key:
            raise ValueError("reviewed package identity mismatch")
        for entry in manifest["files"]:
            github_location(manifest, entry)
            total += entry["size_bytes"]
        packages.append((manifest, manifest_raw))
        by_id[key] = manifest
    if total > MAX_TOTAL:
        raise ValueError("reviewed download exceeds total byte limit")
    plan_hash, plan = None, None
    if methods_plan:
        path = Path(methods_plan).absolute()
        body = bounded_bytes(safe_file(path.parent, path.name), 2 * 1024 * 1024)
        plan = json.loads(body)
        if plan.get("schema") != "public-skill-method-import-v1":
            raise ValueError("unsupported reviewed method plan")
        if not 1 <= len(plan.get("methods", [])) <= 100:
            raise ValueError("bounded reviewed method plan required")
        seen = set()
        for row in plan["methods"]:
            if not isinstance(row.get("public_id"), str) or not row["public_id"] or row["public_id"] in seen:
                raise ValueError("unique reviewed method public_id required")
            seen.add(row["public_id"])
            payload = MethodRequest.model_validate(row["payload"])
            if not payload.skill_sources:
                raise ValueError("reviewed skill method requires source links")
            for link in payload.skill_sources:
                package = by_id.get(link.package_id)
                entries = [] if package is None else [entry for entry in package["files"] if entry["path"] == link.path]
                if len(entries) != 1 or entries[0]["sha256"] != link.sha256:
                    raise ValueError("method source link is outside the reviewed packages")
        plan_hash = hashlib.sha256(body).hexdigest()
    return raw, packages, total, plan_hash, plan


def reconstruct(catalog, output, methods_plan=None, apply=False, fetcher=None):
    catalog_raw, packages, total, plan_hash, plan = reviewed_inputs(catalog, methods_plan)
    output = external_output(output)
    result = {"schema": "public-skill-fetch-receipt-v1", "dry_run": not apply,
              "status": "planned", "packages": [manifest["package_id"] for manifest, _ in packages],
              "catalog_sha256": hashlib.sha256(catalog_raw).hexdigest(),
              "methods_plan_sha256": plan_hash, "files_total": sum(len(m["files"]) for m, _ in packages),
              "bytes_total": total, "files_present": 0, "files_downloaded": 0,
              "source_policy": "preserved_public_originals_untrusted_do_not_execute",
              "dependency_policy": "no_installation_or_execution"}
    # Verify ALL preexisting originals before making any network request or write.
    existing_bytes(output, "catalog.json", catalog_raw)
    for manifest, manifest_raw in packages:
        key = manifest["package_id"]
        existing_bytes(output, "packages/" + key + "/manifest.json", manifest_raw)
        expected = {entry["path"] for entry in manifest["files"]}
        original = output_path(output, "packages/" + key + "/original")
        if original.exists():
            for path in original.rglob("*"):
                if path.is_symlink() or (path.is_file() and path.relative_to(original).as_posix() not in expected):
                    raise ValueError("preexisting original contains symlink or unlisted file")
        for entry in manifest["files"]:
            relative = "packages/" + key + "/original/" + entry["path"]
            if existing_bytes(output, relative, b"", entry):
                result["files_present"] += 1
    if not apply:
        return result
    output.mkdir(parents=True, exist_ok=True)
    # Preexisting receipts are metadata only; they never authorize file reuse.
    output_path(output, "fetch-receipt.json")
    result.update(status="partial", started_at=datetime.now(timezone.utc).isoformat())
    receipt_write(output, result)
    fetcher = fetcher or fetch_bytes
    try:
        for manifest, manifest_raw in packages:
            key = manifest["package_id"]
            relative = "packages/" + key + "/manifest.json"
            if not existing_bytes(output, relative, manifest_raw):
                exclusive_write(output, relative, manifest_raw)
            for entry in manifest["files"]:
                relative = "packages/" + key + "/original/" + entry["path"]
                if existing_bytes(output, relative, b"", entry):
                    continue
                body = fetcher(github_location(manifest, entry), entry["size_bytes"])
                validate_body(entry, body)
                exclusive_write(output, relative, body)
                result["files_downloaded"] += 1
                receipt_write(output, result)
        if not existing_bytes(output, "catalog.json", catalog_raw):
            exclusive_write(output, "catalog.json", catalog_raw)
        originals = SourcePackages(output)
        for manifest, _ in packages:
            for entry in manifest["files"]:
                originals.file_bytes(manifest["package_id"], entry["path"])
        if plan is not None:
            # Verify the already-pinned reviewed plan against actual preserved text.
            for row in plan["methods"]:
                for link in row["payload"]["skill_sources"]:
                    originals.validate_link(link)
        result.update(status="complete", completed_at=datetime.now(timezone.utc).isoformat())
        receipt_write(output, result)
        return result
    except Exception:
        result["status"] = "partial"
        result["error"] = "source_reconstruction_failed_no_original_overwrite"
        receipt_write(output, result)
        raise


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", required=True, help="reviewed public examples catalog.json")
    p.add_argument("--output", required=True, help="external runtime directory outside Git")
    p.add_argument("--methods-plan", help="reviewed proposal plan; validate exact source links/spans")
    p.add_argument("--apply", action="store_true")
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    try:
        print(json.dumps(reconstruct(args.catalog, args.output, args.methods_plan, args.apply),
                         ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc)) from None
