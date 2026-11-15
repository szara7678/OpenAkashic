"""Pinned, owner-reviewed public skill originals. Never fetch or execute source text."""
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.research_store import canonical, public_uri
from app.research_method_evidence import LICENSES

SCHEMA = "public-skill-source-v1"
CATALOG = "public-skill-source-catalog-v1"
MAX_FILE = 2 * 1024 * 1024
MAX_PACKAGE = 32 * 1024 * 1024
MAX_FILES = 1000
PREFIX = "/research/api/skill-sources"
router = APIRouter(prefix=PREFIX, tags=["public skill source originals"])
POLICY = "untrusted_data_do_not_execute"
HASH = r"^[0-9a-f]{64}$"
PACKAGE = r"^skill_[0-9a-f]{32}$"


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValueError("bounded relative source path required")
    if (value.startswith("/") or "\\" in value or ":" in value or
            any(part in ("", ".", "..") for part in value.split("/")) or
            any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe source path")
    return value


class SkillSourceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: Annotated[str, Field(pattern=PACKAGE)]
    path: Annotated[str, Field(min_length=1, max_length=500)]
    sha256: Annotated[str, Field(pattern=HASH)]
    start_line: Annotated[int, Field(strict=True, ge=1)]
    end_line: Annotated[int, Field(strict=True, ge=1)]
    section: Annotated[str, Field(max_length=300)] = ""

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        return relative_path(value)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end_line < self.start_line:
            raise ValueError("source span must have ordered one-based lines")
        return self


def package_identity(manifest):
    """Identity commits to exact original files and upstream revision, not local paths."""
    identity = {key: manifest[key] for key in
                ("source_id", "repository", "commit", "original_directory")}
    identity["files"] = sorted(
        [{key: item[key] for key in ("path", "sha256", "size_bytes")}
         for item in manifest["files"]], key=lambda item: item["path"])
    return "skill_" + hashlib.sha256(canonical(identity).encode()).hexdigest()[:32]


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("unsupported public skill source manifest")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,99}", data.get("source_id", "")):
        raise ValueError("stable public source_id required")
    repository = data.get("repository", "")
    public_uri(repository)
    if not repository.startswith("https://") or not re.fullmatch(r"[0-9a-f]{40}", data.get("commit", "")):
        raise ValueError("HTTPS repository and exact Git commit required")
    relative_path(data.get("original_directory"))
    relative_path(data.get("entrypoint"))
    license_ = data.get("license", {})
    if license_.get("spdx") not in LICENSES or license_.get("reviewed_for_publication") is not True:
        raise ValueError("reviewed redistribution license required")
    public_uri(license_.get("url", ""))
    files = data.get("files", [])
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("bounded file manifest required")
    seen, total = set(), 0
    for item in files:
        path = relative_path(item.get("path"))
        if path in seen:
            raise ValueError("duplicate source file")
        seen.add(path)
        if not re.fullmatch(HASH, item.get("sha256", "")):
            raise ValueError("exact source file hash required")
        size = item.get("size_bytes")
        if type(size) is not int or not 0 <= size <= MAX_FILE:
            raise ValueError("source file exceeds byte limit")
        if "original_path" in item:
            relative_path(item["original_path"])
        if "git_blob" in item and not re.fullmatch(r"[0-9a-f]{40}", item["git_blob"]):
            raise ValueError("invalid upstream Git blob identity")
        total += size
    if total > MAX_PACKAGE:
        raise ValueError("source package exceeds byte limit")
    if data["entrypoint"] not in seen or not data.get("license_files"):
        raise ValueError("original entrypoint and license files required")
    if any(relative_path(path) not in seen for path in data["license_files"]):
        raise ValueError("license original missing from manifest")
    if not isinstance(data.get("dependency_notes", []), list):
        raise ValueError("dependency notes must be explicit public text")
    if data.get("package_id") != package_identity(data):
        raise ValueError("unpinned or mismatched source package identity")
    # Reuse the public boundary. This is validation, never an instruction reader.
    from app.research_methods import validate_public_text
    validate_public_text(data)
    return data


def safe_file(root, relative):
    """Reject symlinks at every component, including the configured root itself."""
    relative_path(relative)
    root = Path(root).absolute()
    for part in (root, *root.parents):
        if part.is_symlink():
            raise ValueError("source symlinks are not allowed")
    target = root
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("source symlinks are not allowed")
    if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("source file is unavailable")
    return target


def bounded_bytes(path, limit):
    with path.open("rb") as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise ValueError("source file exceeds byte limit")
    return body


class SourcePackages:
    def __init__(self, root=None):
        configured = root or os.getenv("OPENAKASHIC_SKILL_SOURCE_ROOT")
        if not configured:
            raise ValueError("public skill source catalog is not installed")
        self.root = Path(configured).absolute()
        catalog = json.loads(bounded_bytes(safe_file(self.root, "catalog.json"), 128 * 1024))
        self.ids = catalog.get("packages", [])
        if (catalog.get("schema") != CATALOG or not isinstance(self.ids, list) or len(self.ids) > 1000 or
                len(set(self.ids)) != len(self.ids) or
                any(not isinstance(key, str) or not re.fullmatch(PACKAGE, key) for key in self.ids)):
            raise ValueError("invalid public skill source whitelist")

    def manifest(self, package_id):
        if package_id not in self.ids:
            raise KeyError("Public source package not found")
        data = json.loads(bounded_bytes(safe_file(self.root,
            "packages/" + package_id + "/manifest.json"), 1024 * 1024))
        validate_manifest(data)
        if data["package_id"] != package_id:
            raise ValueError("source package directory identity mismatch")
        return data

    def file_bytes(self, package_id, path):
        relative_path(path)
        manifest = self.manifest(package_id)
        entries = [item for item in manifest["files"] if item["path"] == path]
        if not entries:
            raise KeyError("Public source file not found")
        entry = entries[0]
        body = bounded_bytes(safe_file(self.root,
            "packages/" + package_id + "/original/" + path), MAX_FILE)
        if len(body) != entry["size_bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("source file integrity mismatch")
        if entry.get("git_blob") and hashlib.sha1(
                b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() != entry["git_blob"]:
            raise ValueError("upstream Git blob integrity mismatch")
        return manifest, entry, body

    def validate_link(self, link):
        link = SkillSourceLink.model_validate(link)
        _, entry, body = self.file_bytes(link.package_id, link.path)
        try:
            total = len(body.decode("utf-8").splitlines())
        except UnicodeError as exc:
            raise ValueError("source span requires UTF-8 text") from exc
        if link.sha256 != entry["sha256"] or link.end_line > total:
            raise ValueError("method source hash or line span does not match preserved original")
        return link


def validate_links(links):
    if links:
        packages = SourcePackages()
        for link in links:
            packages.validate_link(link)


def read_url(link):
    from urllib.parse import urlencode
    return PREFIX + "/" + link["package_id"] + "/files?" + urlencode({
        "path": link["path"], "start": link["start_line"],
        "lines": min(160, link["end_line"] - link["start_line"] + 1)})


def _read(operation):
    try:
        return operation(SourcePackages())
    except KeyError as exc:
        raise HTTPException(404, "Public source not found") from exc
    except (ValueError, OSError, UnicodeError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "Public source unavailable or invalid") from exc


@router.get("")
def list_sources(limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 offset: Annotated[int, Query(ge=0, le=1000)] = 0):
    def result(packages):
        manifests = [packages.manifest(key) for key in packages.ids[offset:offset + limit]]
        return {"schema": CATALOG, "items": [
            {key: item[key] for key in ("package_id", "source_id", "repository", "commit",
                                        "original_directory", "entrypoint", "license")}
            for item in manifests], "total": len(packages.ids), "limit": limit,
            "offset": offset, "content_policy": POLICY}
    return _read(result)


@router.get("/{package_id}")
def get_source(package_id: Annotated[str, Field(pattern=PACKAGE)]):
    return _read(lambda packages: {**packages.manifest(package_id), "content_policy": POLICY})


@router.get("/{package_id}/files")
def read_source_file(package_id: Annotated[str, Field(pattern=PACKAGE)],
                     path: Annotated[str, Query(min_length=1, max_length=500)],
                     start: Annotated[int, Query(ge=1)] = 1,
                     lines: Annotated[int, Query(ge=1, le=160)] = 80):
    def result(packages):
        _, entry, body = packages.file_bytes(package_id, path)
        try:
            text = body.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("only UTF-8 text is readable") from exc
        original = text.splitlines(keepends=True)
        if start > max(1, len(original)):
            raise ValueError("line offset exceeds source")
        selection = "".join(original[start - 1:start - 1 + lines])
        # Never silently cut a line; caller can request a narrower range.
        if len(selection.encode()) > 64 * 1024:
            raise ValueError("requested source span exceeds response byte limit")
        return {"schema": "public-skill-source-file-v1", "package_id": package_id,
                "path": path, "sha256": entry["sha256"], "start_line": start,
                "end_line": min(len(original), start + lines - 1),
                "total_lines": len(original), "text": selection,
                "truncated": start + lines - 1 < len(original),
                "content_policy": POLICY}
    return _read(result)
