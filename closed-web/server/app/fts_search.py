from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


_FTS_LOCK = threading.Lock()
_TOKEN_PATTERN = re.compile(r"[\w가-힣]+", re.UNICODE)
_BM25_WEIGHTS = (8.0, 4.0, 1.2, 1.5, 2.0, 1.0, 2.8, 0.5)


@dataclass(frozen=True)
class FTSDocument:
    path: str
    slug: str
    title: str
    summary: str
    kind: str
    project: str
    owner: str
    tags: list[str]
    body: str


def _fts_path() -> Path:
    path = Path(get_settings().fts_index_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_fts_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS note_fts_meta (
            path TEXT PRIMARY KEY,
            slug TEXT NOT NULL,
            fingerprint TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
            path UNINDEXED,
            slug UNINDEXED,
            title,
            summary,
            kind,
            project,
            owner,
            tags,
            body,
            tokenize='unicode61'
        )
        """
    )


def _fingerprint(doc: FTSDocument) -> str:
    payload = "\x1f".join(
        [
            doc.path,
            doc.slug,
            doc.title,
            doc.summary,
            doc.kind,
            doc.project,
            doc.owner,
            " ".join(doc.tags),
            doc.body,
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _sync_index(con: sqlite3.Connection, documents: list[FTSDocument]) -> None:
    _ensure_schema(con)
    existing = {
        str(row["path"]): str(row["fingerprint"])
        for row in con.execute("SELECT path, fingerprint FROM note_fts_meta")
    }
    current_paths = {doc.path for doc in documents}

    removed_paths = [path for path in existing if path not in current_paths]
    if removed_paths:
        con.executemany("DELETE FROM note_fts WHERE path = ?", ((path,) for path in removed_paths))
        con.executemany("DELETE FROM note_fts_meta WHERE path = ?", ((path,) for path in removed_paths))

    for doc in documents:
        fingerprint = _fingerprint(doc)
        if existing.get(doc.path) == fingerprint:
            continue
        con.execute("DELETE FROM note_fts WHERE path = ?", (doc.path,))
        con.execute(
            """
            INSERT INTO note_fts(path, slug, title, summary, kind, project, owner, tags, body)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc.path,
                doc.slug,
                doc.title,
                doc.summary,
                doc.kind,
                doc.project,
                doc.owner,
                " ".join(doc.tags),
                doc.body,
            ),
        )
        con.execute(
            """
            INSERT INTO note_fts_meta(path, slug, fingerprint)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET slug=excluded.slug, fingerprint=excluded.fingerprint
            """,
            (doc.path, doc.slug, fingerprint),
        )


def _query_tokens(query: str) -> list[str]:
    tokens = [token.strip().lower() for token in _TOKEN_PATTERN.findall(query) if token.strip()]
    unique_tokens: list[str] = []
    for token in tokens:
        if token not in unique_tokens:
            unique_tokens.append(token)
    return unique_tokens


def _match_queries(query: str) -> list[str]:
    tokens = _query_tokens(query)
    if not tokens:
        return []
    strict = " AND ".join(f"{token}*" for token in tokens)
    if len(tokens) == 1:
        return [strict]
    loose = " OR ".join(f"{token}*" for token in tokens)
    return [strict, loose]


def lexical_rank(query: str, documents: list[FTSDocument], *, limit: int = 24) -> dict[str, dict[str, float]]:
    match_queries = _match_queries(query)
    if not match_queries or not documents:
        return {}

    allowed_slugs = [doc.slug for doc in documents]
    placeholders = ",".join("?" for _ in allowed_slugs)
    sql = (
        "SELECT slug, path, bm25(note_fts, ?, ?, ?, ?, ?, ?, ?, ?) AS rank "
        "FROM note_fts WHERE note_fts MATCH ? "
        f"AND slug IN ({placeholders}) "
        "ORDER BY rank LIMIT ?"
    )

    with _FTS_LOCK:
        con = _connect()
        try:
            _sync_index(con, documents)
            rows: list[sqlite3.Row] = []
            for match_query in match_queries:
                params = [*_BM25_WEIGHTS, match_query, *allowed_slugs, max(limit, 1)]
                rows = list(con.execute(sql, params))
                if rows:
                    break
            con.commit()
        finally:
            con.close()

    results: dict[str, dict[str, float]] = {}
    for row in rows:
        raw_rank = float(row["rank"] if row["rank"] is not None else 0.0)
        normalized = 1.0 / (1.0 + abs(raw_rank))
        results[str(row["slug"])] = {
            "bm25": raw_rank,
            "score": normalized,
        }
    return results
