from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import mimetypes
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from app.config import get_settings


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
DEFAULT_IMAGE_FOLDER = "assets/images"
DEFAULT_FILE_FOLDER = "assets/files"
ROOT_NOTE_FILES = {"README.md", "AGENTS.md"}
PROJECT_SUBFOLDERS = (
    "architecture",
    "playbooks",
    "incidents",
    "decisions",
    "experiments",
    "reference",
)
KIND_CATALOG: list[dict[str, Any]] = [
    {
        "kind": "index",
        "label": "Index",
        "folder": "reference",
        "summary": "프로젝트나 공간의 진입점과 지도.",
        "sections": ["Summary", "Canonical Docs", "Active Surfaces", "Memory Map", "Reuse"],
    },
    {
        "kind": "architecture",
        "label": "Architecture",
        "folder": "architecture",
        "summary": "구조, 경계, 제어면, 데이터 흐름.",
        "sections": ["Summary", "Context", "Design", "Interfaces", "Risks", "Reuse"],
    },
    {
        "kind": "policy",
        "label": "Policy",
        "folder": "playbooks",
        "summary": "권한, 승인 조건, 금지 규칙.",
        "sections": ["Summary", "Policy", "Allowed Actions", "Disallowed Actions", "Reuse"],
    },
    {
        "kind": "playbook",
        "label": "Playbook",
        "folder": "playbooks",
        "summary": "반복 실행 절차와 운영 방법.",
        "sections": ["Summary", "When To Use", "Steps", "Checks", "Reuse"],
    },
    {
        "kind": "evidence",
        "label": "Evidence",
        "folder": "reference",
        "summary": "공개 결과의 근거가 되는 문서, 파일, 재현 기록.",
        "sections": ["Summary", "Source", "Method", "Artifacts", "Findings", "Limitations"],
    },
    {
        "kind": "experiment",
        "label": "Experiment",
        "folder": "experiments",
        "summary": "실험, 검증, 재현 시도.",
        "sections": ["Summary", "Hypothesis", "Setup", "Results", "Follow-up"],
    },
    {
        "kind": "dataset",
        "label": "Dataset",
        "folder": "reference",
        "summary": "데이터셋, 표본, 파일 세트 설명.",
        "sections": ["Summary", "Source", "Schema", "Coverage", "Usage Notes"],
    },
    {
        "kind": "reference",
        "label": "Reference",
        "folder": "reference",
        "summary": "짧게 다시 참조할 사실, 규약, 메모.",
        "sections": ["Summary", "Reference", "Reuse"],
    },
    {
        "kind": "claim",
        "label": "Claim",
        "folder": "reference",
        "summary": "공개 가능한 사실 주장과 범위.",
        "sections": ["Summary", "Claim", "Evidence Links", "Scope", "Caveats"],
    },
    {
        "kind": "capsule",
        "label": "Capsule",
        "folder": "reference",
        "summary": "공동 publish용 요약 산출물.",
        "sections": ["Summary", "Outcome", "Evidence Links", "Practical Use", "Reuse"],
    },
    {
        "kind": "roadmap",
        "label": "Roadmap",
        "folder": "reference",
        "summary": "갭 분석과 다음 단계 계획.",
        "sections": ["Summary", "Current State", "Gaps", "Next Milestones", "Open Questions"],
    },
    {
        "kind": "profile",
        "label": "Profile",
        "folder": "reference",
        "summary": "에이전트/주체의 역할과 성격.",
        "sections": ["Summary", "Role", "Capabilities", "Constraints", "Reuse"],
    },
    {
        "kind": "publication_request",
        "label": "Publication Request",
        "folder": "reference",
        "summary": "공개 요청 패키지와 근거 묶음.",
        "sections": ["Summary", "Source Note", "Requested Output", "Evidence Links", "Rationale", "Review Notes"],
    },
]
KIND_KEYS = {item["kind"] for item in KIND_CATALOG}
KIND_ALIASES = {
    "note": "reference",
    "concept": "reference",
    "schema": "reference",
    "workflow": "playbook",
    "incident": "experiment",
    "decision": "policy",
    "pattern": "playbook",
}
VISIBILITY_VALUES = {"private", "public"}
PUBLICATION_STATUS_VALUES = {
    "none",
    "requested",
    "reviewing",
    "approved",
    "rejected",
    "published",
}
PUBLICATION_REQUEST_FOLDER = "personal_vault/projects/ops/librarian/publication_requests"


FOLDER_RULES: list[dict[str, Any]] = [
    {
        "root": "doc",
        "label": "Docs",
        "description": "Long-lived operating docs, schemas, and agent guidance.",
        "subfolders": [
            {"path": "doc/general", "label": "general"},
            {"path": "doc/agents", "label": "agents"},
            {"path": "doc/reference", "label": "reference"},
        ],
    },
    {
        "root": "personal_vault",
        "label": "Vault",
        "description": "Reusable memory split into shared knowledge, personal notes, and personal or company project workspaces.",
        "subfolders": [
            {"path": "personal_vault/shared/concepts", "label": "shared concepts"},
            {"path": "personal_vault/shared/playbooks", "label": "shared playbooks"},
            {"path": "personal_vault/shared/schemas", "label": "shared schemas"},
            {"path": "personal_vault/shared/reference", "label": "shared reference"},
            {"path": "personal_vault/personal/concepts", "label": "personal concepts"},
            {"path": "personal_vault/personal/playbooks", "label": "personal playbooks"},
            {"path": "personal_vault/personal/reference", "label": "personal reference"},
            {"path": "personal_vault/projects", "label": "agent-managed projects"},
        ],
    },
    {
        "root": "assets",
        "label": "Assets",
        "description": "Uploaded images and media referenced by notes.",
        "subfolders": [
            {"path": "assets/images", "label": "images"},
            {"path": "assets/files", "label": "files"},
        ],
    },
]


@dataclass
class VaultDocument:
    path: str
    frontmatter: dict[str, Any]
    body: str


@dataclass
class VaultAsset:
    path: str
    mime_type: str
    size: int
    alt: str
    markdown: str
    url: str


@dataclass
class PublicationRequest:
    path: str
    source_path: str
    source_title: str
    requester: str
    target_visibility: str
    status: str
    rationale: str
    evidence_paths: list[str]
    requested_at: str


def vault_root() -> Path:
    return Path(get_settings().closed_akashic_path).resolve()


def folder_rules() -> list[dict[str, Any]]:
    return FOLDER_RULES


def folder_index() -> dict[str, list[str]]:
    root = vault_root()
    result: dict[str, list[str]] = {}
    for rule in FOLDER_RULES:
        base = root / rule["root"]
        existing = []
        if base.exists():
            for path in sorted(base.rglob("*")):
                if path.is_dir():
                    existing.append(path.relative_to(root).as_posix())
        result[rule["root"]] = existing
    return result


def list_note_paths() -> list[str]:
    root = vault_root()
    if not root.exists():
        return []
    return [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*.md"))
        if path.is_file() and _is_allowed_note_path(path.relative_to(root))
    ]


def load_document(path: str) -> VaultDocument:
    target = resolve_note_path(path, must_exist=True)
    raw = target.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(raw)
    return VaultDocument(
        path=target.relative_to(vault_root()).as_posix(),
        frontmatter=frontmatter,
        body=body.strip(),
    )


def write_document(
    *,
    path: str,
    body: str,
    title: str | None = None,
    kind: str | None = None,
    project: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    allow_owner_change: bool = False,
) -> VaultDocument:
    target = resolve_note_path(path, must_exist=False)
    existing = load_document(path) if target.exists() else None
    frontmatter = dict(existing.frontmatter if existing else {})

    if title:
        frontmatter["title"] = title
    elif not frontmatter.get("title"):
        frontmatter["title"] = target.stem

    if kind:
        frontmatter["kind"] = normalize_kind(kind)
    elif not frontmatter.get("kind"):
        frontmatter["kind"] = "reference"
    else:
        frontmatter["kind"] = normalize_kind(str(frontmatter.get("kind")))

    if project:
        frontmatter["project"] = project
    elif not frontmatter.get("project"):
        frontmatter["project"] = "closed-akashic"

    if status:
        frontmatter["status"] = status
    elif not frontmatter.get("status"):
        frontmatter["status"] = "active"

    if not frontmatter.get("confidence"):
        frontmatter["confidence"] = "high"

    if tags is not None:
        frontmatter["tags"] = tags
    elif "tags" not in frontmatter:
        frontmatter["tags"] = []

    if related is not None:
        frontmatter["related"] = related
    elif "related" not in frontmatter:
        frontmatter["related"] = []

    if metadata:
        next_metadata = dict(metadata)
        if existing and not allow_owner_change and "owner" in next_metadata:
            next_metadata["owner"] = existing.frontmatter.get("owner")
        frontmatter.update(next_metadata)

    _apply_governance_defaults(frontmatter)

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    frontmatter["updated_at"] = now
    if "created_at" not in frontmatter:
        frontmatter["created_at"] = now

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_document(frontmatter, body), encoding="utf-8")
    return load_document(path)


def request_publication(
    *,
    path: str,
    requester: str | None = None,
    target_visibility: str = "public",
    rationale: str | None = None,
    evidence_paths: list[str] | None = None,
) -> PublicationRequest:
    document = load_document(path)
    source_frontmatter = dict(document.frontmatter)
    _apply_governance_defaults(source_frontmatter)
    requested_at = _now_iso()
    requester_value = (requester or source_frontmatter.get("owner") or get_settings().default_note_owner).strip()
    target = _normalize_visibility(target_visibility or "public")
    if target != "public":
        raise ValueError("Publication target must be public")

    source_frontmatter["publication_status"] = "requested"
    source_frontmatter["publication_requested_at"] = requested_at
    source_frontmatter["publication_requested_by"] = requester_value
    source_frontmatter["publication_target_visibility"] = target
    write_document(
        path=document.path,
        body=document.body,
        metadata=source_frontmatter,
    )

    request_slug = _slugify(f"{Path(document.path).stem}-{requested_at}")
    request_path = f"{PUBLICATION_REQUEST_FOLDER}/{request_slug}.md"
    evidence = [item for item in (evidence_paths or []) if str(item).strip()]
    request_body = "\n".join(
        [
            "## Summary",
            f"Publication request for `{document.path}`.",
            "",
            "## Source",
            f"- path: `{document.path}`",
            f"- title: {source_frontmatter.get('title', Path(document.path).stem)}",
            f"- current_visibility: `{source_frontmatter.get('visibility', 'private')}`",
            f"- target_visibility: `{target}`",
            f"- requester: `{requester_value}`",
            "",
            "## Rationale",
            (rationale or "No rationale provided.").strip(),
            "",
            "## Evidence Paths",
            *(f"- `{item}`" for item in evidence),
            *(["- none"] if not evidence else []),
            "",
            "## Librarian Checklist",
            "- [ ] Confirm owner and requester authority.",
            "- [ ] Check source evidence and provenance.",
            "- [ ] Create or update derived public capsule instead of exposing private source directly.",
            "- [ ] Record approve/reject decision with reason.",
        ]
    )
    request_doc = write_document(
        path=request_path,
        body=request_body,
        title=f"Publication Request - {source_frontmatter.get('title', Path(document.path).stem)}",
        kind="publication_request",
        project="ops/librarian",
        status="requested",
        tags=["librarian", "publication", "request"],
        related=[str(source_frontmatter.get("title", ""))] if source_frontmatter.get("title") else [],
        metadata={
            "owner": "sagwan",
            "visibility": "private",
            "publication_status": "reviewing",
            "source_path": document.path,
            "requester": requester_value,
            "target_visibility": target,
            "requested_at": requested_at,
            "evidence_paths": evidence,
        },
    )
    return PublicationRequest(
        path=request_doc.path,
        source_path=document.path,
        source_title=str(source_frontmatter.get("title", Path(document.path).stem)),
        requester=requester_value,
        target_visibility=target,
        status="requested",
        rationale=(rationale or "").strip(),
        evidence_paths=evidence,
        requested_at=requested_at,
    )


def list_publication_requests(status: str | None = None) -> list[PublicationRequest]:
    status_filter = (status or "").strip().lower()
    requests: list[PublicationRequest] = []
    for path in list_note_paths():
        if not path.startswith(f"{PUBLICATION_REQUEST_FOLDER}/"):
            continue
        try:
            document = load_document(path)
        except Exception:
            continue
        frontmatter = document.frontmatter
        current_status = str(frontmatter.get("status") or frontmatter.get("publication_status") or "requested")
        if status_filter and current_status.lower() != status_filter:
            continue
        requests.append(
            PublicationRequest(
                path=document.path,
                source_path=str(frontmatter.get("source_path") or ""),
                source_title=str(frontmatter.get("title") or Path(document.path).stem),
                requester=str(frontmatter.get("requester") or ""),
                target_visibility=str(frontmatter.get("target_visibility") or "public"),
                status=current_status,
                rationale=_extract_section(document.body, "Rationale"),
                evidence_paths=_as_list(frontmatter.get("evidence_paths")),
                requested_at=str(frontmatter.get("requested_at") or frontmatter.get("created_at") or ""),
            )
        )
    requests.sort(key=lambda item: item.requested_at, reverse=True)
    return requests


def set_publication_status(
    *,
    path: str,
    status: str,
    decider: str = "sagwan",
    reason: str | None = None,
) -> VaultDocument:
    document = load_document(path)
    frontmatter = dict(document.frontmatter)
    _apply_governance_defaults(frontmatter)
    next_status = _normalize_publication_status(status)
    if next_status == "none":
        raise ValueError("Publication status decision must be requested, reviewing, approved, rejected, or published")
    frontmatter["publication_status"] = next_status
    frontmatter["publication_decided_at"] = _now_iso()
    frontmatter["publication_decided_by"] = (decider or "sagwan").strip() or "sagwan"
    if reason is not None:
        frontmatter["publication_decision_reason"] = reason.strip()
    if next_status == "published":
        frontmatter.setdefault("original_owner", frontmatter.get("owner") or get_settings().default_note_owner)
        frontmatter["visibility"] = "public"
        frontmatter["owner"] = "sagwan"
    return write_document(path=document.path, body=document.body, metadata=frontmatter, allow_owner_change=True)


def append_section(path: str, heading: str, content: str) -> VaultDocument:
    existing = load_document(path)
    section = f"\n\n## {heading.strip()}\n{content.strip()}\n"
    return write_document(
        path=path,
        body=(existing.body.rstrip() + section).strip() + "\n",
        metadata=existing.frontmatter,
    )


def delete_document(path: str) -> str:
    target = resolve_note_path(path, must_exist=True)
    relative = target.relative_to(vault_root()).as_posix()
    target.unlink()
    return relative


def move_document(path: str, new_path: str) -> str:
    source = resolve_note_path(path, must_exist=True)
    target = resolve_note_path(new_path, must_exist=False)
    if target.exists():
        raise FileExistsError(target.relative_to(vault_root()).as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target.relative_to(vault_root()).as_posix()


def ensure_folder(path: str) -> str:
    target = resolve_folder_path(path, must_exist=False)
    target.mkdir(parents=True, exist_ok=True)
    return target.relative_to(vault_root()).as_posix()


def move_folder(path: str, new_path: str) -> str:
    source = resolve_folder_path(path, must_exist=True)
    target = resolve_folder_path(new_path, must_exist=False)
    if target.exists():
        raise FileExistsError(target.relative_to(vault_root()).as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target.relative_to(vault_root()).as_posix()


def save_image(
    *,
    filename: str,
    content: bytes,
    folder: str | None = None,
    alt: str | None = None,
) -> VaultAsset:
    root = vault_root()
    raw_folder = (folder or DEFAULT_IMAGE_FOLDER).strip().strip("/")
    target_folder = resolve_asset_folder(raw_folder)
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError("Unsupported image type")

    stem = _slugify(Path(filename).stem)
    safe_name = f"{stem}-{uuid4().hex[:8]}{suffix}"
    target = root / target_folder / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    rel_path = target.relative_to(root).as_posix()
    mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    rendered_alt = alt or Path(filename).stem
    url = file_href(rel_path)
    return VaultAsset(
        path=rel_path,
        mime_type=mime_type,
        size=target.stat().st_size,
        alt=rendered_alt,
        markdown=f"![{rendered_alt}]({url})",
        url=url,
    )


def save_asset(
    *,
    filename: str,
    content: bytes,
    folder: str | None = None,
    label: str | None = None,
) -> VaultAsset:
    root = vault_root()
    raw_folder = (folder or DEFAULT_FILE_FOLDER).strip().strip("/")
    target_folder = resolve_asset_folder(raw_folder)
    suffix = Path(filename).suffix.lower()
    stem = _slugify(Path(filename).stem or "file")
    safe_name = f"{stem}-{uuid4().hex[:8]}{suffix}"
    target = root / target_folder / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    rel_path = target.relative_to(root).as_posix()
    mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    rendered_label = label or Path(filename).name or target.name
    url = file_href(rel_path)
    return VaultAsset(
        path=rel_path,
        mime_type=mime_type,
        size=target.stat().st_size,
        alt=rendered_label,
        markdown=f"[{rendered_label}]({url})",
        url=url,
    )


def read_asset_bytes(path: str) -> tuple[Path, str]:
    target = resolve_asset_path(path, must_exist=True)
    mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target, mime_type


def resolve_note_path(path: str, *, must_exist: bool) -> Path:
    root = vault_root()
    safe_path = Path(path.strip())
    if not path.strip():
        raise ValueError("Path is required")
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise ValueError("Path must be relative to the vault root")

    normalized = safe_path.with_suffix(".md") if safe_path.suffix.lower() != ".md" else safe_path
    if not normalized.parts:
        raise ValueError("Invalid note path")
    if not _is_allowed_note_path(normalized):
        raise ValueError("Path must stay within an allowed Closed Akashic note root")

    target = (root / normalized).resolve()
    if root not in target.parents:
        raise ValueError("Path escapes Closed Akashic root")
    if must_exist and not target.exists():
        raise FileNotFoundError(normalized.as_posix())
    return target


def resolve_asset_folder(path: str) -> str:
    safe_path = Path(path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise ValueError("Asset folder must be relative")
    if not safe_path.parts:
        raise ValueError("Asset folder is required")
    if safe_path.parts[0] != "assets":
        raise ValueError("Assets must be stored under assets/")
    return safe_path.as_posix()


def resolve_asset_path(path: str, *, must_exist: bool) -> Path:
    root = vault_root()
    safe_path = Path(path.strip())
    if not path.strip():
        raise ValueError("Asset path is required")
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise ValueError("Asset path must be relative")
    if not safe_path.parts or safe_path.parts[0] != "assets":
        raise ValueError("Asset path must stay inside assets/")
    target = (root / safe_path).resolve()
    if root not in target.parents:
        raise ValueError("Asset path escapes Closed Akashic root")
    if must_exist and not target.exists():
        raise FileNotFoundError(safe_path.as_posix())
    return target


def resolve_folder_path(path: str, *, must_exist: bool) -> Path:
    root = vault_root()
    safe_path = Path(path.strip().strip("/"))
    if not safe_path.parts:
        raise ValueError("Folder path is required")
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise ValueError("Folder path must be relative")
    if safe_path.suffix:
        raise ValueError("Folder path must point to a directory")
    if safe_path.parts[0] not in set(get_settings().writable_root_list):
        raise ValueError("Folder path must stay inside an allowed Closed Akashic root")
    target = (root / safe_path).resolve()
    if root not in target.parents:
        raise ValueError("Folder path escapes Closed Akashic root")
    if must_exist and not target.exists():
        raise FileNotFoundError(safe_path.as_posix())
    return target


def file_href(path: str, route_prefix: str = "") -> str:
    prefix = "/" + route_prefix.strip("/") if route_prefix.strip() else ""
    return f"{prefix}/files/{path.strip('/')}"


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    return parse_yamlish(parts[1]), parts[2]


def parse_yamlish(value: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for line in value.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            output[key.strip()] = [
                item.strip().strip("\"'")
                for item in raw[1:-1].split(",")
                if item.strip()
            ]
        else:
            output[key.strip()] = raw.strip("\"'")
    return output


def render_document(frontmatter: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            rendered = ", ".join(_quote_yaml(str(item)) for item in value if str(item).strip())
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {_quote_yaml(str(value))}")
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    return "\n".join(lines).rstrip() + "\n"


def _apply_governance_defaults(frontmatter: dict[str, Any]) -> None:
    owner = str(frontmatter.get("owner") or get_settings().default_note_owner).strip() or "aaron"
    visibility = _normalize_visibility(str(frontmatter.get("visibility") or get_settings().default_note_visibility))
    publication_status = _normalize_publication_status(str(frontmatter.get("publication_status") or "none"))
    frontmatter["owner"] = owner
    frontmatter["visibility"] = visibility
    frontmatter["publication_status"] = publication_status


def _normalize_visibility(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_") or "private"
    aliases = {
        "personal": "private",
        "personal_private": "private",
        "private_source": "private",
        "source_private": "private",
        "source_shared": "private",
        "shared_source": "private",
        "internal": "private",
        "derived_internal": "private",
        "requested": "private",
        "public_requested": "private",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VISIBILITY_VALUES:
        return "private"
    return normalized


def _normalize_publication_status(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_") or "none"
    if normalized not in PUBLICATION_STATUS_VALUES:
        return "none"
    return normalized


def kind_catalog() -> list[dict[str, Any]]:
    return KIND_CATALOG


def normalize_kind(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    if not normalized:
        return "reference"
    resolved = KIND_ALIASES.get(normalized, normalized)
    return resolved if resolved in KIND_KEYS else "reference"


def kind_template_sections(kind: str | None) -> list[str]:
    kind_key = normalize_kind(kind)
    for item in KIND_CATALOG:
        if item["kind"] == kind_key:
            return list(item["sections"])
    return ["Summary", "Reference", "Reuse"]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _extract_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def suggest_note_path(
    kind: str | None,
    title: str,
    preferred_folder: str | None = None,
    scope: str | None = None,
    project: str | None = None,
) -> str:
    kind_key = normalize_kind(kind)
    if preferred_folder:
        base = preferred_folder.strip().strip("/")
    elif project:
        if kind_key == "index":
            return f"{_project_workspace(project)}/README.md"
        by_kind = {
            "architecture": "architecture",
            "policy": "playbooks",
            "playbook": "playbooks",
            "evidence": "reference",
            "experiment": "experiments",
            "dataset": "reference",
            "reference": "reference",
            "claim": "reference",
            "capsule": "reference",
            "roadmap": "reference",
            "profile": "reference",
            "publication_request": "reference",
        }
        leaf = by_kind.get(kind_key, "reference")
        base = f"{_project_workspace(project)}/{leaf}"
    else:
        scope_key = (scope or "shared").strip().lower()
        if scope_key == "personal":
            by_kind = {
                "policy": "personal_vault/personal/playbooks",
                "playbook": "personal_vault/personal/playbooks",
                "evidence": "personal_vault/personal/reference",
                "experiment": "personal_vault/personal/reference",
                "reference": "personal_vault/personal/reference",
                "roadmap": "personal_vault/personal/reference",
                "profile": "personal_vault/personal/reference",
            }
        else:
            by_kind = {
                "architecture": "personal_vault/shared/reference",
                "policy": "personal_vault/shared/playbooks",
                "playbook": "personal_vault/shared/playbooks",
                "evidence": "personal_vault/shared/reference",
                "experiment": "personal_vault/shared/reference",
                "dataset": "personal_vault/shared/reference",
                "reference": "personal_vault/shared/reference",
                "claim": "personal_vault/shared/reference",
                "capsule": "personal_vault/shared/reference",
                "roadmap": "personal_vault/shared/reference",
                "profile": "personal_vault/shared/reference",
            }
        base = by_kind.get(kind_key, "personal_vault/shared/reference")
    return f"{base}/{title.strip()}.md"


def normalize_project_key(project: str, scope: str | None = None) -> str:
    raw = project.strip().replace("\\", "/")
    pieces = [piece for piece in raw.split("/") if piece and piece != "."]
    if not pieces:
        raise ValueError("Project name is required")
    scope_key = (scope or "").strip().lower()
    if scope_key:
        pieces = [scope_key, *pieces] if pieces[0] != scope_key else pieces
    elif len(pieces) == 1:
        pieces = [scope_key or "personal", *pieces]
    slugged = [_slugify(piece) for piece in pieces]
    return "/".join(slugged)


def bootstrap_project_workspace(
    *,
    project: str,
    scope: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    canonical_docs: list[str] | None = None,
    folders: list[str] | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
) -> dict[str, Any]:
    project_key = normalize_project_key(project, scope)
    workspace = _project_workspace(project_key)
    created_folders = [ensure_folder(workspace)]
    folder_plan = _normalize_project_folders(folders)
    for folder in folder_plan:
        created_folders.append(ensure_folder(f"{workspace}/{folder}"))

    readme_path = f"{workspace}/README.md"
    readme_target = resolve_note_path(readme_path, must_exist=False)
    created_index = not readme_target.exists()
    if created_index:
        display_title = title or _display_project_title(project_key)
        doc = write_document(
            path=readme_path,
            title=f"{display_title} Project",
            kind="index",
            project=project_key,
            status="active",
            tags=tags or ["project", *project_key.split("/")],
            related=related or ["Project Memory Intake", "Agent Guide"],
            body=_render_project_index_body(
                project_key=project_key,
                display_title=display_title,
                summary=summary,
                canonical_docs=canonical_docs,
            ),
        )
    else:
        doc = load_document(readme_path)

    return {
        "project": project_key,
        "workspace": workspace,
        "folders": created_folders,
        "folder_plan": folder_plan,
        "readme_path": readme_path,
        "created_index": created_index,
        "frontmatter": doc.frontmatter,
    }


def _quote_yaml(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", value):
        return value
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _is_allowed_note_path(path: Path) -> bool:
    note_roots = {root for root in get_settings().writable_root_list if root != "assets"}
    if not path.parts:
        return False
    if len(path.parts) == 1:
        return path.name in ROOT_NOTE_FILES
    return path.parts[0] in note_roots


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣ぁ-んァ-ン一-龥]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _project_workspace(project: str) -> str:
    return f"personal_vault/projects/{normalize_project_key(project)}"


def _display_project_title(project_key: str) -> str:
    leaf = project_key.split("/")[-1]
    return " ".join(part.capitalize() for part in leaf.replace("-", " ").split())


def _render_project_index_body(
    *,
    project_key: str,
    display_title: str,
    summary: str | None,
    canonical_docs: list[str] | None,
) -> str:
    docs = canonical_docs or []
    doc_lines = [f"- `{path}`" for path in docs if path.strip()]
    if not doc_lines:
        doc_lines = ["- add the canonical repo docs, plans, and troubleshooting paths here"]

    return "\n".join(
        [
            "## Summary",
            summary or f"{display_title} reusable memory lives in this project workspace.",
            "",
            "## Canonical Docs",
            *doc_lines,
            "",
            "## Active Surfaces",
            "- repo: add the main repository path or URL",
            "- runtime: add the deployed app, API, or service endpoint",
            "- dashboards: add logs, metrics, or admin surfaces worth checking first",
            "",
            "## Memory Map",
            "- Add or remove subfolders as the project demands.",
            "- Common choices: architecture, playbooks, incidents, decisions, experiments, reference.",
            "- Keep project-specific canonical docs in the repo and reusable memory here.",
            "",
            "## Working Agreement",
            "- Keep canonical product docs in the project repo.",
            "- Store only distilled reusable memory here.",
            "- Let agents create, move, or rename project folders through MCP when the structure changes.",
            "- Update this index when a new note or folder becomes a recurring starting point.",
            "",
            "## Reuse",
            f"Read this index, then search adjacent notes in `{_project_workspace(project_key)}` before major work. Write back one concise linked note after meaningful changes.",
        ]
    )


def _normalize_project_folders(folders: list[str] | None) -> list[str]:
    if not folders:
        return list(PROJECT_SUBFOLDERS)

    result: list[str] = []
    for raw in folders:
        folder = raw.strip().strip("/")
        if not folder:
            continue
        safe_path = Path(folder)
        if safe_path.is_absolute() or ".." in safe_path.parts or safe_path.suffix:
            raise ValueError(f"Invalid project folder: {raw}")
        normalized = safe_path.as_posix()
        if normalized not in result:
            result.append(normalized)
    return result or list(PROJECT_SUBFOLDERS)
