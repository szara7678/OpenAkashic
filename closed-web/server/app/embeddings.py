from __future__ import annotations

import json
from threading import Lock
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


_model_lock = Lock()
_sentence_transformer_model = None


def _embedding_provider() -> str:
    return get_settings().embedding_provider.strip().lower() or "sentence-transformers"


def _embedding_model_name() -> str:
    return get_settings().embedding_model.strip() or "intfloat/multilingual-e5-small"


def _embedding_max_chars() -> int:
    return max(500, int(get_settings().embedding_max_chars or 4000))


def _embedding_batch_size() -> int:
    return max(1, min(64, int(get_settings().embedding_batch_size or 16)))


def _truncate_for_embedding(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _embedding_max_chars():
        return stripped
    return stripped[: _embedding_max_chars()].rsplit(" ", 1)[0].strip() or stripped[: _embedding_max_chars()]


def _uses_e5_prefix() -> bool:
    model_name = _embedding_model_name().lower()
    return "e5" in model_name


def _prepare_query_text(text: str) -> str:
    stripped = _truncate_for_embedding(text)
    if not stripped:
        return stripped
    return f"query: {stripped}" if _uses_e5_prefix() else stripped


def _prepare_document_text(text: str) -> str:
    stripped = _truncate_for_embedding(text)
    if not stripped:
        return stripped
    return f"passage: {stripped}" if _uses_e5_prefix() else stripped


def _load_sentence_transformer():
    global _sentence_transformer_model
    if _sentence_transformer_model is not None:
        return _sentence_transformer_model
    with _model_lock:
        if _sentence_transformer_model is not None:
            return _sentence_transformer_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed. Add it to the server requirements or switch to Ollama embeddings."
            ) from exc
        _sentence_transformer_model = SentenceTransformer(_embedding_model_name(), device="cpu")
        return _sentence_transformer_model


def _normalize(vectors: Iterable[Iterable[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for vector in vectors:
        values = [float(value) for value in vector]
        magnitude = sum(value * value for value in values) ** 0.5
        if magnitude <= 0:
            normalized.append(values)
            continue
        normalized.append([value / magnitude for value in values])
    return normalized


def _embed_sentence_transformers(texts: list[str], *, is_query: bool) -> list[list[float]]:
    prepared = [_prepare_query_text(text) if is_query else _prepare_document_text(text) for text in texts]
    model = _load_sentence_transformer()
    vectors = model.encode(
        prepared,
        normalize_embeddings=False,
        show_progress_bar=False,
    )
    return _normalize(vectors.tolist() if hasattr(vectors, "tolist") else vectors)


def _embed_ollama(texts: list[str], *, is_query: bool) -> list[list[float]]:
    prepared = [_prepare_query_text(text) if is_query else _prepare_document_text(text) for text in texts]
    vectors: list[list[float]] = []
    batch_size = _embedding_batch_size()
    for index in range(0, len(prepared), batch_size):
        vectors.extend(_embed_ollama_batch(prepared[index : index + batch_size]))
    return _normalize(vectors)


def _embed_ollama_batch(prepared: list[str]) -> list[list[float]]:
    payload = {
        "model": _embedding_model_name(),
        "input": prepared,
    }
    body = json.dumps(payload).encode("utf-8")
    base_url = get_settings().ollama_base_url.rstrip("/")
    request = urllib_request.Request(
        f"{base_url}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib_error.URLError as exc:
        raise EmbeddingError(f"Failed to reach Ollama embedding endpoint: {exc}") from exc
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or not vectors:
        raise EmbeddingError("Ollama embedding response did not include embeddings")
    return vectors


def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    cleaned = [text.strip() for text in texts if text and text.strip()]
    if not cleaned:
        return []
    provider = _embedding_provider()
    if provider == "ollama":
        return _embed_ollama(cleaned, is_query=is_query)
    return _embed_sentence_transformers(cleaned, is_query=is_query)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))
