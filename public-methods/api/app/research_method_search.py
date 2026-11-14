"""Bounded, read-only semantic retrieval over an external public-method index.

Embedding similarities and contributor feedback are relevance signals, never a
truth score or a probability of success. No feedback is embedded as method truth.
"""
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from app.research_method_store import axis_match, adequate_axis, tokens
from app.research_store import canonical, digest

SCHEMA_VERSION = "method-index-v1"
FIELDS = ("situation", "goal")
MAX_METHODS = 10000
MAX_DIMENSIONS = 4096
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")


class SearchUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    model: str = ""
    revision: str = ""
    embedding_spec: str = ""
    situation_floor: float = 0.55
    goal_floor: float = 0.62
    rrf_k: int = 60

    def __post_init__(self):
        if not all(math.isfinite(x) and -1 <= x <= 1 for x in (self.situation_floor, self.goal_floor)):
            raise ValueError("semantic floors must be finite cosine values")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be positive")

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("OPENAKASHIC_EMBEDDING_MODEL", ""),
            revision=os.getenv("OPENAKASHIC_EMBEDDING_REVISION", ""),
            embedding_spec=os.getenv("OPENAKASHIC_EMBEDDING_SPEC", ""),
            situation_floor=float(os.getenv("OPENAKASHIC_METHOD_SITUATION_FLOOR", "0.55")),
            goal_floor=float(os.getenv("OPENAKASHIC_METHOD_GOAL_FLOOR", "0.62")),
        )

    def provenance(self):
        if not all((self.model, self.revision, self.embedding_spec)):
            raise SearchUnavailable("embedding model, revision and specification must be pinned")
        return {"schema": SCHEMA_VERSION, "model": self.model,
                "revision": self.revision, "embedding_spec": self.embedding_spec}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SearchUnavailable("embedding redirects are disabled")


class HTTPEmbedder:
    """Only the operator-configured loopback service is contacted; never user URLs."""
    def __init__(self, config, endpoint=None, timeout=15):
        self.config = config
        self.endpoint = endpoint or os.getenv("OPENAKASHIC_EMBEDDING_URL", "")
        parsed = urlparse(self.endpoint)
        allowed_hosts = {"127.0.0.1", "::1", "localhost"}
        bridge = os.getenv("OPENAKASHIC_EMBEDDING_BRIDGE_HOST", "")
        if bridge:
            try:
                address = ipaddress.ip_address(bridge)
                networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
                if address.version != 4 or not any(address in ipaddress.ip_network(n) for n in networks):
                    raise ValueError("bridge must be an explicit RFC1918 IPv4 address")
                allowed_hosts.add(str(address))
            except ValueError as exc:
                raise SearchUnavailable("invalid configured embedding bridge host") from exc
        if (parsed.scheme != "http" or parsed.hostname not in allowed_hosts
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise SearchUnavailable("a fixed loopback or configured bridge HTTP embedding endpoint is required")
        self.timeout = min(max(float(timeout), 0.1), 15.0)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def embed(self, texts, input_type):
        if input_type not in {"query", "document"} or not 1 <= len(texts) <= 8:
            raise SearchUnavailable("invalid embedding batch")
        if any(not isinstance(x, str) or not 1 <= len(x) <= 2000 for x in texts):
            raise SearchUnavailable("embedding text exceeds bounds")
        req = Request(self.endpoint, data=canonical({"texts": texts, "input_type": input_type}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            deadline = time.monotonic() + self.timeout
            for attempt in range(5):
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SearchUnavailable("embedding request deadline exceeded")
                    with self.opener.open(req, timeout=remaining) as response:
                        raw = response.read(MAX_RESPONSE_BYTES + 1)
                    break
                except HTTPError as exc:
                    # The local encoder is deliberately single-flight. Brief
                    # contention can recover without changing the query/model,
                    # relaxing floors, or hiding errors behind lexical results.
                    delay = 0.15 * (2 ** attempt)
                    if exc.code != 429 or attempt == 4 or time.monotonic() + delay >= deadline:
                        raise
                    time.sleep(delay)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise SearchUnavailable("embedding response exceeds bounds")
            body = json.loads(raw)
            for key in ("model", "revision", "embedding_spec"):
                if body.get(key) != self.config.provenance()[key]:
                    raise SearchUnavailable("embedding service provenance mismatch")
            if body.get("normalized") is not True:
                raise SearchUnavailable("embedding service normalization mismatch")
            vectors = body["embeddings"]
            if len(vectors) != len(texts):
                raise SearchUnavailable("embedding batch count mismatch")
            result = [validate_vector(x) for x in vectors]
            if any(len(x) != body.get("dimensions") for x in result):
                raise SearchUnavailable("embedding dimensions mismatch")
            return result
        except (OSError, URLError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SearchUnavailable("embedding service unavailable or invalid response") from exc


def validate_vector(value):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_DIMENSIONS:
        raise SearchUnavailable("invalid embedding dimensions")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise SearchUnavailable("invalid embedding values")
    norm = math.sqrt(sum(x*x for x in value))
    if norm < 1e-12:
        raise SearchUnavailable("zero embedding")
    return [x / norm for x in value]


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_methods(store):
    with store.archive._connect() as db:
        rows = db.execute("SELECT id,version,body FROM method_methods ORDER BY id LIMIT ?", (MAX_METHODS + 1,)).fetchall()
    if len(rows) > MAX_METHODS:
        raise SearchUnavailable("method archive exceeds bounded retrieval capacity")
    methods = []
    for row in rows:
        method = json.loads(row["body"])
        if method.get("id") != row["id"] or method.get("version") != row["version"]:
            raise SearchUnavailable("method source identity mismatch")
        methods.append(method)
    return methods


def constraint_match(method, requires=(), forbids=()):
    required, forbidden = set(requires), set(forbids)
    if any(not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in required | forbidden):
        raise ValueError("structured constraint tags must be lowercase tokens")
    if required & forbidden:
        raise ValueError("query constraint tags conflict")
    rules = method.get("constraint_rules", {})
    mr, mf = set(rules.get("requires", [])), set(rules.get("forbids", []))
    if any(not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in mr | mf) or mr & mf:
        return {"status": "conflict", "conflicts": ["invalid_method_constraint_rules"], "unknown": []}
    conflicts = sorted((mr & forbidden) | (mf & required))
    unknown = sorted((mr - required - forbidden) | ((required | forbidden) - mr - mf))
    # Undeclared capability/safety requirements cannot be inferred from free text.
    status = "conflict" if conflicts else "unknown" if unknown or not rules else "satisfied"
    return {"status": status, "conflicts": conflicts, "unknown": unknown,
            "basis": "declared_tags_not_environment_verification",
            "interpretation": "compatible_declared" if status == "satisfied" else status}


def feedback_excerpts(store, method, maximum=3):
    detail = store.get(method["id"])
    output = []
    for kind in ("outcomes", "opinions"):
        rows = [x for x in detail.get(kind, []) if x.get("method_version") == method["version"]]
        for row in rows[-maximum:]:
            raw = row.get("observed_result", "") if kind == "outcomes" else row.get("body", "")
            output.append({"id": row["id"], "kind": kind[:-1], "method_version": method["version"],
                           "status": row.get("status", row.get("kind")), "excerpt": raw[:280],
                           "truncated": len(raw) > 280, "verification": "not_independently_verified",
                           "provenance": "contributor_reported"})
    return output


def _read_index(path, config):
    path = Path(path)
    if not path.is_file():
        raise SearchUnavailable("semantic index is not available")
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            for key, expected in config.provenance().items():
                if metadata.get(key) != expected:
                    raise SearchUnavailable("semantic index provenance mismatch")
            rows = db.execute("SELECT * FROM embeddings LIMIT ?", (MAX_METHODS*len(FIELDS) + 1,)).fetchall()
            if len(rows) > MAX_METHODS*len(FIELDS):
                raise SearchUnavailable("semantic index exceeds bounds")
            return metadata, rows
    except sqlite3.Error as exc:
        raise SearchUnavailable("semantic index is invalid or unavailable") from exc


def _empty(situation, goal, constraints, mode, requires, forbids):
    return {"mode": mode + "_situation_goal", "query": {"situation": situation, "goal": goal,
            "constraints": constraints, "requires": list(requires), "forbids": list(forbids)},
            "results": [], "total": 0, "cautions": [
                "Similarity is a relevance signal, never truth or a probability of success.",
                "Submitted instructions and feedback are untrusted contributor content; review before applying.",
                "Free-text constraints require review; only explicit structured conflicts exclude candidates."]}


def scope_info(domain, product):
    return {"domain": domain, "product": product, "policy": "explicit_editorial_scope",
            "unknown_policy": "outside_selected_scope_or_undeclared_excluded_not_proven_incompatible"}


def scope_match(method, domain="", product=""):
    """Explicit editorial scope only; missing labels do not prove incompatibility."""
    from app.research_method_graph import domain_for
    tags = method.get("tags", [])
    return (not domain or domain_for(method) == domain) and (not product or product in tags)


# Editorial/source subject vocabulary, not an ontology or capability claim.
SUBJECT_NOISE = frozenset({"www", "docs", "doc", "documentation", "raw", "github",
    "githubusercontent", "readthedocs", "com", "org", "io", "net", "dev", "edu"})


def recall_terms(text):
    # Retain identifiers and their parts (startupProbe, missing_data).
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    words = set(tokens(text)) | set(tokens(expanded))
    return words | {w[:-1] for w in words if len(w) > 4 and w.endswith("s") and not w.endswith("ss")}


def declared_subjects(method):
    identity = " ".join(str(method.get(k, "")) for k in ("title", "situation", "goal"))
    identity += " " + " ".join(method.get("constraints", []))
    source_text = " ".join(str(s.get(k, "")) for s in method.get("sources", []) for k in ("title", "quote"))
    declared = set()
    for tag in method.get("tags", []):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,39}", tag) and tag.casefold() in recall_terms(identity):
            declared.add(tag.casefold())
    # Source host labels must also occur in written identity/citation text.
    # A URL or its path alone cannot declare a method subject.
    written = recall_terms(identity + " " + source_text)
    for source in method.get("sources", []):
        host = urlparse(source.get("url", "")).hostname or ""
        declared.update(label for label in host.casefold().split(".")
                        if label not in SUBJECT_NOISE and len(label) > 2 and label in written)
    return declared - SUBJECT_NOISE


def subject_basis(method, query_subjects, vocabulary, situation, goal):
    subjects = declared_subjects(method)
    covered, missing = query_subjects & subjects, query_subjects - subjects
    title_subjects = subjects & recall_terms(method.get("title", ""))
    unmentioned_title_subjects = title_subjects - query_subjects
    subject_words = set().union(*(recall_terms(word) for word in vocabulary)) if vocabulary else set()
    topic = recall_terms(" ".join(str(method.get(k, "")) for k in ("title", "situation", "goal"))
                         + " " + " ".join(method.get("steps", []))
                         + " " + " ".join(str(s.get(k, "")) for s in method.get("sources", [])
                                              for k in ("title", "quote"))) - subject_words
    evidence = {field: sorted((recall_terms(text) - subject_words) & topic)
                for field, text in (("situation", situation), ("goal", goal))}
    return {"policy": "declared_subject_and_topic_v1", "query_subjects": sorted(query_subjects),
            "method_subjects": sorted(subjects), "covered": sorted(covered), "undeclared": sorted(missing),
            "unmentioned_title_subjects": sorted(unmentioned_title_subjects),
            "topic_terms": evidence, "status": "unknown" if missing else "declared_overlap" if covered else "not_selected",
            "interpretation": "retrieval_relevance_only_not_verified_applicability"}


def search_methods(store, situation, goal, constraints="", limit=5, *, mode="hybrid", requires=(),
                   forbids=(), domain="", product="", index_path=None, embedder=None, config=None):
    """Retrieve methods with disclosed subject/topic checks and independent ranks.

    Semantic candidates pass both frozen floors. Hybrid may also return explicitly
    labeled subject-and-topic lexical candidates. Both routes require a current
    pinned index and available embedder; neither bypasses staleness or constraints.
    """
    if mode not in {"semantic", "hybrid", "lexical"}:
        raise ValueError("unknown method search mode")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be 1-20")
    if len(requires) > 20 or len(forbids) > 20:
        raise ValueError("too many structured constraint tags")
    constraint_match({}, requires, forbids)
    if mode == "lexical" and not requires and not forbids and not domain and not product:
        return store.search(situation, goal, constraints, limit)
    if mode == "lexical":
        result = store.search(situation, goal, constraints, MAX_METHODS)
        result["results"] = [row for row in result["results"]
                             if scope_match(row["method"], domain, product)
                             and constraint_match(row["method"], requires, forbids)["status"] != "conflict"]
        if domain or product:
            result["scope"] = scope_info(domain, product)
        result["total"] = len(result["results"])
        result["results"] = result["results"][:limit]
        for row in result["results"]:
            row["match"]["constraint_rules"] = constraint_match(row["method"], requires, forbids)
        return result
    result = _empty(situation, goal, constraints, mode, requires, forbids)
    if domain or product:
        result["scope"] = scope_info(domain, product)
    config = config or SearchConfig.from_env()
    metadata = {"available": False, "status": "unavailable", "eligible_methods": 0,
                "stale_or_missing_methods": 0, "weak_axis_methods": 0, "constraint_conflicts": 0, "relevance_status": "unknown", "floors": {"situation": config.situation_floor, "goal": config.goal_floor},
                "floor_policy": "operator_frozen_before_evaluation", "ranking": "reciprocal_rank_fusion" if mode == "hybrid" else "mean_axis_cosine",
                "subject_policy": "declared_subject_and_topic_v1",
                "subject_unknown_policy": "undeclared_subject_or_topic_excluded_not_proven_incompatible",
                "subject_unknown_methods": 0, "lexical_recall_methods": 0}
    result["search"] = metadata
    try:
        methods = source_methods(store)
        vocabulary = set().union(*(declared_subjects(m) for m in methods)) if methods else set()
        query_subjects = (recall_terms(situation) | recall_terms(goal)) & vocabulary
        metadata["query_subjects"] = sorted(query_subjects)
        if query_subjects:
            result["cautions"].append("Automatic declared subject/topic checks narrow retrieval; missing subject labels are unknown, not proven incompatibility.")
        index_meta, entries = _read_index(index_path or os.getenv("OPENAKASHIC_METHOD_INDEX", ""), config)
        metadata.update({key: index_meta[key] for key in ("model", "revision", "embedding_spec")})
        query = (embedder or HTTPEmbedder(config)).embed([situation, goal], "query")
        if len(query) != 2:
            raise SearchUnavailable("query embedding count mismatch")
        query = [validate_vector(x) for x in query]
        dimensions = int(index_meta.get("dimensions", "-1"))
        if any(len(x) != dimensions for x in query) and methods:
            raise SearchUnavailable("query/index dimensions mismatch")
        vectors = {(r["method_id"], r["version"], r["field"]): r for r in entries}
        eligible = []
        lexical_rank = {}
        for method in methods:
            if not scope_match(method, domain, product):
                continue
            axes = {}
            stale = False
            for field, qvector in zip(FIELDS, query):
                row = vectors.get((method["id"], method["version"], field))
                if (row is None or row["source_hash"] != digest(method) or row["content_hash"] != text_hash(method[field])
                        or any(row[key] != config.provenance()[key] for key in ("model", "revision", "embedding_spec"))):
                    stale = True
                    break
                vector = validate_vector(json.loads(row["vector"]))
                if len(vector) != len(qvector) or len(vector) != row["dimensions"]:
                    stale = True
                    break
                axes[field] = sum(a*b for a, b in zip(qvector, vector))
            if stale:
                metadata["stale_or_missing_methods"] += 1
                continue
            rule_match = constraint_match(method, requires, forbids)
            if rule_match["status"] == "conflict":
                metadata["constraint_conflicts"] += 1
                continue
            s, g = axis_match(situation, method["situation"]), axis_match(goal, method["goal"])
            basis = subject_basis(method, query_subjects, vocabulary, situation, goal)
            topic_overlap = all(basis["topic_terms"].values())
            if query_subjects and (basis["undeclared"] or basis["unmentioned_title_subjects"] or not topic_overlap):
                metadata["subject_unknown_methods"] += 1
                continue
            lexical_recall = bool(mode == "hybrid" and query_subjects and topic_overlap)
            if adequate_axis(s) and adequate_axis(g):
                lexical_rank[method["id"]] = (s["coverage"]+g["coverage"])/2
            semantic = axes["situation"] >= config.situation_floor and axes["goal"] >= config.goal_floor
            if not semantic:
                metadata["weak_axis_methods"] += 1
                if not lexical_recall:
                    continue
                metadata["lexical_recall_methods"] += 1
                lexical_rank[method["id"]] = sum(len(x) for x in basis["topic_terms"].values())
            for field, match in (("situation", s), ("goal", g)):
                match.update({"similarity": round(axes[field], 6), "status": "relevant" if semantic else "lexical_candidate_below_semantic_floor", "floor": getattr(config, field+"_floor")})
            c = axis_match(constraints, " ".join(method["constraints"]))
            c["status"] = "requires_review" if constraints else "not_reviewed"
            eligible.append({"method": method, "match": {"situation": s, "goal": g, "constraints": c,
                            "constraint_rules": rule_match, "retrieval_basis": "semantic_axes" if semantic else "declared_subject_topic_lexical",
                            "subject_match": basis, "semantic_eligible": semantic, "semantic_relevance": round(sum(axes.values())/2, 6),
                            "cautions": result["cautions"]}})
        eligible.sort(key=lambda x: (-x["match"]["semantic_relevance"], x["method"]["id"]))
        lex_ranks = {mid: rank for rank, (mid, _) in enumerate(sorted(lexical_rank.items(), key=lambda x: (-x[1], x[0])), 1)}
        semantic_ranks = {row["method"]["id"]: rank for rank, row in enumerate(
            [x for x in eligible if x["match"]["semantic_eligible"]], 1)}
        for row in eligible:
            rank = semantic_ranks.get(row["method"]["id"])
            lr = lex_ranks.get(row["method"]["id"])
            row["match"]["score"] = (round((1/(config.rrf_k+rank) if rank else 0) + (1/(config.rrf_k+lr) if lr else 0), 8)
                                          if mode == "hybrid" else row["match"]["semantic_relevance"])
            row["match"]["ranks"] = {"semantic": rank, "lexical": lr}
        eligible.sort(key=lambda x: (-x["match"]["score"], x["method"]["id"]))
        result["total"] = len(eligible)
        result["results"] = eligible[:limit]
        for row in result["results"]:
            row["match"]["feedback"] = feedback_excerpts(store, row["method"])
        metadata.update({"available": True, "eligible_methods": len(eligible),
                         "status": "partial_index" if metadata["stale_or_missing_methods"] else "ready",
                         "source_methods": len(methods), "relevance_status": "candidates" if eligible else "unknown"})
        if metadata["lexical_recall_methods"]:
            result["cautions"].append("Some candidates use declared subject/topic lexical recall below semantic floors; inspect the retrieval basis and full method before applying.")
        if metadata["stale_or_missing_methods"]:
            result["cautions"].append("Some current methods lack a matching index entry and were excluded.")
    except (SearchUnavailable, ValueError, KeyError, TypeError) as exc:
        result["results"], result["total"] = [], 0
        metadata["reason"] = str(exc)[:200]
        result["cautions"].append("Semantic retrieval abstained because the index or embedding service is unavailable or inconsistent.")
    return result


def build_index(store, index_path, embedder, config):
    """Incrementally rebuild an external SQLite index in one atomic transaction."""
    from app.research_methods import validate_public_text
    path = Path(index_path).resolve()
    repo = Path(__file__).resolve().parents[2]
    if path == repo or repo in path.parents:
        raise ValueError("generated method indexes must remain outside the repository")
    if path == Path(store.db_path).resolve():
        raise ValueError("index must be separate from the public source archive")
    provenance = config.provenance()
    methods = source_methods(store)
    snapshot_hash = digest(methods)
    for method in methods:
        validate_public_text(method)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS embeddings(
            method_id TEXT NOT NULL, version INTEGER NOT NULL, field TEXT NOT NULL,
            source_hash TEXT NOT NULL, content_hash TEXT NOT NULL, model TEXT NOT NULL,
            revision TEXT NOT NULL, embedding_spec TEXT NOT NULL, dimensions INTEGER NOT NULL,
            vector TEXT NOT NULL, PRIMARY KEY(method_id,version,field))""")
        previous = dict(db.execute("SELECT key,value FROM metadata"))
        rebuild = any(previous.get(k) != v for k, v in provenance.items())
        old = {} if rebuild else {(r["method_id"], r["version"], r["field"]): r for r in db.execute("SELECT * FROM embeddings")}
        desired, pending, reused = [], [], 0
        for method in methods:
            for field in FIELDS:
                key = (method["id"], method["version"], field)
                row = old.get(key)
                item = (*key, digest(method), text_hash(method[field]), config.model, config.revision, config.embedding_spec)
                if row and all(name == "source_hash" or row[name] == value for name, value in zip(
                        ("method_id", "version", "field", "source_hash", "content_hash", "model", "revision", "embedding_spec"), item)):
                    vector = validate_vector(json.loads(row["vector"]))
                    if len(vector) == row["dimensions"]:
                        desired.append((*item, len(vector), canonical(vector)))
                        reused += 1
                        continue
                pending.append((item, method[field]))
        for offset in range(0, len(pending), 8):
            batch = pending[offset:offset+8]
            vectors = embedder.embed([text for _, text in batch], "document")
            if len(vectors) != len(batch):
                raise SearchUnavailable("embedding batch count mismatch")
            for (item, _), vector in zip(batch, vectors):
                vector = validate_vector(vector)
                desired.append((*item, len(vector), canonical(vector)))
        if len({row[-2] for row in desired}) > 1:
            raise SearchUnavailable("index vectors have inconsistent dimensions")
        if digest(source_methods(store)) != snapshot_hash:
            raise SearchUnavailable("public method source changed while indexing; retry")
        if (not pending and not rebuild and previous.get("source_snapshot_hash") == snapshot_hash
                and len(old) == len(desired)):
            return {"methods": len(methods), "embedded_fields": 0, "reused_fields": reused,
                    "source_snapshot_hash": snapshot_hash, **provenance, "index_path": str(path)}
        db.execute("DELETE FROM embeddings")
        db.executemany("INSERT INTO embeddings VALUES (?,?,?,?,?,?,?,?,?,?)", desired)
        db.execute("DELETE FROM metadata")
        db.executemany("INSERT INTO metadata VALUES (?,?)", {**provenance, "source_snapshot_hash": snapshot_hash,
                       "method_count": str(len(methods)), "dimensions": str(desired[0][-2] if desired else 0)}.items())
    return {"methods": len(methods), "embedded_fields": len(pending), "reused_fields": reused,
            "source_snapshot_hash": snapshot_hash, **provenance, "index_path": str(path)}




