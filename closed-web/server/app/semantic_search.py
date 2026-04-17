from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.embeddings import EmbeddingError, cosine_similarity, embed_texts


CACHE_VERSION = 1
_cache_lock = threading.Lock()

# ── In-memory cache ───────────────────────────────────────────────────────────
# 디스크 read/write는 최초 로드 1회 + 변경 시 백그라운드 저장만 수행한다.
# 이전 구조에서 매 검색마다 11MB JSON read/write → ~550ms 낭비를 제거한다.

_mem_cache: dict | None = None          # 로드된 캐시 (None = 아직 미로드)
_dirty: bool = False                    # 마지막 저장 이후 변경 여부
_bg_save_timer: threading.Timer | None = None
_BG_SAVE_DELAY = 5.0                    # 변경 후 5초 뒤 디스크에 저장


@dataclass(frozen=True)
class SemanticDocument:
    key: str
    path: str
    title: str
    kind: str
    project: str
    status: str
    summary: str
    body: str

    @property
    def fingerprint(self) -> str:
        source = "\n".join(
            [
                self.path,
                self.title,
                self.kind,
                self.project,
                self.status,
                self.summary,
                self.body,
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @property
    def embedding_text(self) -> str:
        return "\n".join(
            [
                self.title,
                self.kind,
                self.project,
                self.status,
                self.summary,
                self.body,
            ]
        ).strip()


def semantic_rank(query: str, documents: list[SemanticDocument], limit: int = 12) -> list[tuple[str, float]]:
    stripped = query.strip()
    if not stripped or not documents:
        return []

    try:
        cache = _get_mem_cache()
        changed = _ensure_document_vectors(cache, documents)
        if changed:
            _schedule_bg_save()
        query_vector = embed_texts([stripped], is_query=True)
        if not query_vector:
            return []
        scores: list[tuple[str, float]] = []
        for document in documents:
            item = cache["documents"].get(document.key)
            if not item:
                continue
            score = cosine_similarity(query_vector[0], item.get("vector", []))
            if score > 0.18:
                scores.append((document.key, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:limit]
    except EmbeddingError:
        return []
    except Exception:
        return []


# ── Cache identity & path ─────────────────────────────────────────────────────

def _cache_path() -> Path:
    path = Path(get_settings().semantic_cache_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = PROJECT_ROOT / "server" / "logs" / "semantic-index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cache_identity() -> dict[str, object]:
    settings = get_settings()
    return {
        "version": CACHE_VERSION,
        "provider": settings.embedding_provider.strip().lower(),
        "model": settings.embedding_model.strip(),
        "max_chars": settings.embedding_max_chars,
        "batch_size": settings.embedding_batch_size,
    }


# ── In-memory cache accessors ─────────────────────────────────────────────────

def _get_mem_cache() -> dict:
    """메모리 캐시 반환. 미로드 시 디스크에서 1회 읽고 이후 메모리 유지."""
    global _mem_cache
    if _mem_cache is not None:
        return _mem_cache
    with _cache_lock:
        if _mem_cache is not None:
            return _mem_cache
        _mem_cache = _load_from_disk()
    return _mem_cache


def _load_from_disk() -> dict:
    path = _cache_path()
    identity = _cache_identity()
    if not path.exists():
        return {**identity, "documents": {}}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {**identity, "documents": {}}
    if any(cache.get(k) != v for k, v in identity.items()):
        # 모델/설정 변경 → 캐시 무효화
        return {**identity, "documents": {}}
    if not isinstance(cache.get("documents"), dict):
        cache["documents"] = {}
    return cache


def _schedule_bg_save() -> None:
    """변경 후 5초 뒤 디스크 저장 예약 (debounce). 연속 변경 시 타이머 재설정."""
    global _dirty, _bg_save_timer
    _dirty = True
    if _bg_save_timer is not None:
        _bg_save_timer.cancel()
    _bg_save_timer = threading.Timer(_BG_SAVE_DELAY, _flush_to_disk)
    _bg_save_timer.daemon = True
    _bg_save_timer.start()


def _flush_to_disk() -> None:
    """메모리 캐시를 디스크에 저장한다. 백그라운드 타이머에서 호출."""
    global _dirty
    if not _dirty or _mem_cache is None:
        return
    path = _cache_path()
    with _cache_lock:
        if not _dirty or _mem_cache is None:
            return
        try:
            path.write_text(json.dumps(_mem_cache, ensure_ascii=False), encoding="utf-8")
            _dirty = False
        except OSError:
            pass


def flush_semantic_cache() -> None:
    """외부에서 즉시 저장이 필요할 때 호출 (shutdown hook 등)."""
    global _bg_save_timer
    if _bg_save_timer is not None:
        _bg_save_timer.cancel()
        _bg_save_timer = None
    _flush_to_disk()


def invalidate_semantic_cache() -> None:
    """모델/설정 변경 시 메모리 캐시를 초기화한다."""
    global _mem_cache, _dirty, _bg_save_timer
    with _cache_lock:
        if _bg_save_timer is not None:
            _bg_save_timer.cancel()
            _bg_save_timer = None
        _mem_cache = None
        _dirty = False


# ── Document vector management ────────────────────────────────────────────────

def _ensure_document_vectors(
    cache: dict,
    documents: list[SemanticDocument],
) -> bool:
    """누락/변경된 문서를 임베딩하고 캐시에 반영. 변경 여부를 반환."""
    stored = cache.setdefault("documents", {})
    missing_docs: list[SemanticDocument] = []
    for document in documents:
        current = stored.get(document.key)
        if not isinstance(current, dict) or current.get("fingerprint") != document.fingerprint:
            missing_docs.append(document)
    stale_keys = [key for key in list(stored.keys()) if key not in {doc.key for doc in documents}]
    for key in stale_keys:
        stored.pop(key, None)
    if not missing_docs and not stale_keys:
        return False
    if missing_docs:
        vectors = embed_texts([document.embedding_text for document in missing_docs], is_query=False)
        for document, vector in zip(missing_docs, vectors):
            stored[document.key] = {
                "fingerprint": document.fingerprint,
                "vector": vector,
                "document": asdict(document),
            }
    return True
