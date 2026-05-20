"""Core API embedding client — calls ollama bge-m3 over HTTP.

Used by retrieval (query embedding) and POST hooks (claim/capsule embedding
on insert). Returns L2-normalized vectors so cosine == dot product.
"""
from __future__ import annotations

import json
import logging
import urllib.error as urlerror
import urllib.request as urlrequest

from app.config import get_settings

logger = logging.getLogger("openakashic.embeddings")


class EmbeddingError(RuntimeError):
    pass


def _truncate(text: str, max_chars: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rsplit(" ", 1)[0].strip() or s[:max_chars]


def _normalize(vec: list[float]) -> list[float]:
    mag = sum(v * v for v in vec) ** 0.5
    if mag <= 0:
        return vec
    return [v / mag for v in vec]


def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """Batch-embed via ollama. Returns one normalized vector per input.

    Empty / whitespace-only inputs are dropped (returns shorter list).
    Failure raises EmbeddingError — callers decide to skip the row or
    fail-soft (retrieval falls back to lexical-only).
    """
    settings = get_settings()
    if settings.embedding_provider.strip().lower() != "ollama":
        raise EmbeddingError(f"unsupported embedding provider: {settings.embedding_provider}")

    max_chars = max(200, int(settings.embedding_max_chars or 1200))
    batch_size = max(1, min(64, int(settings.embedding_batch_size or 16)))

    cleaned = [_truncate(t, max_chars) for t in texts if t and t.strip()]
    if not cleaned:
        return []

    base = settings.embedding_base_url.rstrip("/")
    url = f"{base}/api/embed"
    vectors: list[list[float]] = []
    for i in range(0, len(cleaned), batch_size):
        batch = cleaned[i : i + batch_size]
        payload = {
            "model": settings.embedding_model,
            "input": batch,
            "keep_alive": settings.embedding_keep_alive,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urlerror.URLError as exc:
            raise EmbeddingError(f"ollama embed unreachable: {exc}") from exc
        embeds = data.get("embeddings")
        if not isinstance(embeds, list) or len(embeds) != len(batch):
            raise EmbeddingError("ollama returned malformed embeddings")
        vectors.extend(_normalize([float(x) for x in v]) for v in embeds)
    return vectors


def embed_one(text: str, *, is_query: bool = False) -> list[float] | None:
    """Convenience: embed a single string, return None on empty/failure."""
    if not text or not text.strip():
        return None
    try:
        out = embed_texts([text], is_query=is_query)
    except EmbeddingError as exc:
        logger.warning("embed_one failed: %s", exc)
        return None
    return out[0] if out else None
