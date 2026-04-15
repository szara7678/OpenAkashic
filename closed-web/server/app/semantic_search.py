from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

from app.config import PROJECT_ROOT, get_settings
from app.embeddings import EmbeddingError, cosine_similarity, embed_texts


CACHE_VERSION = 1
_cache_lock = Lock()


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
        cache = _load_cache()
        cache = _ensure_document_vectors(cache, documents)
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
        _save_cache(cache)
        return scores[:limit]
    except EmbeddingError:
        return []
    except Exception:
        return []


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


def _load_cache() -> dict[str, object]:
    path = _cache_path()
    identity = _cache_identity()
    with _cache_lock:
        if not path.exists():
            return {**identity, "documents": {}}
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {**identity, "documents": {}}
    if any(cache.get(key) != value for key, value in identity.items()):
        return {**identity, "documents": {}}
    if not isinstance(cache.get("documents"), dict):
        cache["documents"] = {}
    return cache


def _save_cache(cache: dict[str, object]) -> None:
    path = _cache_path()
    with _cache_lock:
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _ensure_document_vectors(
    cache: dict[str, object],
    documents: list[SemanticDocument],
) -> dict[str, object]:
    stored = cache.setdefault("documents", {})
    missing_docs: list[SemanticDocument] = []
    for document in documents:
        current = stored.get(document.key)
        if not isinstance(current, dict) or current.get("fingerprint") != document.fingerprint:
            missing_docs.append(document)
    stale_keys = [key for key in list(stored.keys()) if key not in {doc.key for doc in documents}]
    for key in stale_keys:
        stored.pop(key, None)
    if not missing_docs:
        return cache
    vectors = embed_texts([document.embedding_text for document in missing_docs], is_query=False)
    for document, vector in zip(missing_docs, vectors):
        stored[document.key] = {
            "fingerprint": document.fingerprint,
            "vector": vector,
            "document": asdict(document),
        }
    return cache
