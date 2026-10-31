"""Operator-reviewed original-source retrieval; no network or model calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from app.research_method_context import _bundle_count
from app.research_store import public_uri

SCHEMA = "method-evidence-index-v1"
POLICY = "question-clause-context-v2"
LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
            "MPL-2.0", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"}
STOPWORDS = frozenset("""a an and are as at be been being but by can could did do
does for from had has have how i if in into is it its may me might more most my
no not of on or our out should so some such than that the their them then there
these they this those through to too under up us was we were what when where
which while who why will with would you your""".split())


def retrieval_terms(query):
    """Separate generic output-format instructions without changing input query."""
    question = re.split(r"(?:\n| )Return JSON only:", query, maxsplit=1)[0]
    words = re.findall(r"[^\W_]+", question.lower(), re.UNICODE)
    return list(dict.fromkeys(word for word in words if word not in STOPWORDS))[:256]


def question_clauses(query):
    """Generic scenario/question segments; no domain, answer or task-ID rules."""
    question = re.split(r"(?:\n| )Return JSON only:", query, maxsplit=1)[0]
    chunks = re.split(r"(?=\b[qQ]\d+\s*[:.)])|(?<=[?;])\s+|\n+", question)
    clauses = []
    for chunk in chunks:
        chunk = re.sub(r"^\s*[qQ]\d+\s*[:.)]\s*", "", chunk)
        terms = retrieval_terms(chunk)
        if terms and terms not in clauses:
            clauses.append(terms)
    # Keep the opening scenario and late questions even for long enumerations.
    return clauses if len(clauses) <= 8 else clauses[:4] + clauses[-4:]


def ranked_candidates(db, clauses, allowed=None):
    """Per-clause BM25, round-robin union/dedupe, at most twelve candidates."""
    if allowed == []:
        return []
    restriction = ""
    if allowed is not None:
        restriction = " AND p.source_id IN (" + ",".join(str(int(i)) for i in allowed) + ")"
    groups = []
    for terms in clauses:
        expression = " OR ".join('"' + term + '"' for term in terms)
        groups.append(db.execute(
            "SELECT p.text,p.start,p.end,p.source_id,s.metadata,s.body,bm25(passages) AS rank "
            "FROM passages p JOIN sources s ON s.id=p.source_id WHERE passages MATCH ?" + restriction +
            " ORDER BY rank,s.id,p.start LIMIT 12", (expression,)).fetchall())
    selected, seen = [], set()
    for depth in range(12):
        for group in groups:
            if depth >= len(group):
                continue
            row = group[depth]
            key = (row["source_id"], row["start"], row["end"])
            if key not in seen:
                selected.append(row)
                seen.add(key)
                if len(selected) == 12:
                    return selected
    return selected


def adjacent_context(pack, rows, max_tokens):
    """Expand retained seeds by one paragraph each side when the full JSON fits.

    Overlapping expansions are merged into a single exact contiguous source span.
    Expansion never displaces another topic's already retained seed evidence.
    """
    bodies = {(json.loads(row["metadata"])["source_url"],
               json.loads(row["metadata"])["version"]): row["body"] for row in rows}
    originals = list(pack["items"])
    for seed in originals:
        identity = (seed["source_url"], seed["version"])
        body = bodies[identity]
        spans = list(passages(body))
        index = next(i for i, span in enumerate(spans) if span[0] == seed["start"])
        previous, following = spans[max(0, index-1)][0], spans[min(len(spans)-1, index+1)][1]
        # Prefer both sides. If a large adjacent paragraph prevents that, try
        # following context, then preceding context, without cutting either.
        for left, right in ((previous, following), (seed["start"], following),
                            (previous, seed["end"])):
            overlapping = [item for item in pack["items"]
                           if (item["source_url"], item["version"]) == identity
                           and item["start"] <= right and item["end"] >= left]
            left = min([left] + [item["start"] for item in overlapping])
            right = max([right] + [item["end"] for item in overlapping])
            expanded = dict(seed, start=left, end=right, quote=body[left:right],
                            scope="exact_contiguous_original_paragraphs")
            before = pack["items"]
            first = min((before.index(item) for item in overlapping), default=len(before))
            proposed = [item for item in before if item not in overlapping]
            proposed.insert(first, expanded)
            pack["items"] = proposed
            if _bundle_count(pack) <= max_tokens:
                break
            pack["items"] = before
    covered = sum(any(item["source_url"] == json.loads(row["metadata"])["source_url"]
                      and item["version"] == json.loads(row["metadata"])["version"]
                      and item["start"] <= row["start"] and item["end"] >= row["end"]
                      for item in pack["items"]) for row in rows)
    pack["covered_candidates"] = covered
    pack["omitted_candidates"] = len(rows)-covered


def passages(body):
    """Whole paragraphs with exact Unicode character offsets, never chopped text."""
    for match in re.finditer(r"\S(?:[^\r\n]|\r?\n(?![ \t]*\r?\n))*", body):
        end = match.end()
        while end > match.start() and body[end - 1].isspace():
            end -= 1
        if end > match.start():
            yield match.start(), end, body[match.start():end]


def build_index(manifest_path, output):
    """Atomically install a reviewed local manifest. Approval is operator attestation."""
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("evidence indexes must live outside the repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or not manifest.get("sources"):
        raise ValueError("explicit nonempty evidence manifest required")
    records, seen = [], set()
    for source in manifest["sources"]:
        if source.get("approval") != "approved_public_source":
            raise ValueError("unknown publication approval")
        for key in ("source_url", "version", "sha256", "approved_scope", "provenance"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError("missing source provenance: " + key)
        public_uri(source["source_url"])
        license_ = source.get("license", {})
        if (license_.get("spdx") not in LICENSES
                or license_.get("reviewed_for_publication") is not True):
            raise ValueError("reviewed public redistribution license required")
        public_uri(license_.get("url", ""))
        path = Path(source["path"])
        raw = (path if path.is_absolute() else manifest_path.parent / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("source sha256 mismatch")
        body = raw.decode("utf-8")
        key = (source["source_url"], source["version"])
        if key in seen:
            raise ValueError("duplicate source identity")
        seen.add(key)
        records.append(({k: v for k, v in source.items() if k != "path"}, body))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".evidence-", dir=output.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temp) as db:
            db.executescript("""
                CREATE TABLE metadata(schema TEXT NOT NULL);
                CREATE TABLE sources(id INTEGER PRIMARY KEY, metadata TEXT NOT NULL, body TEXT NOT NULL);
                CREATE VIRTUAL TABLE passages USING fts5(text, source_id UNINDEXED, start UNINDEXED, end UNINDEXED);
            """)
            db.execute("INSERT INTO metadata VALUES (?)", (SCHEMA,))
            for metadata, body in records:
                source_id = db.execute("INSERT INTO sources(metadata,body) VALUES (?,?)",
                                      (json.dumps(metadata), body)).lastrowid
                db.executemany("INSERT INTO passages(text,source_id,start,end) VALUES (?,?,?,?)",
                               ((text, source_id, start, end) for start, end, text in passages(body)))
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"schema": SCHEMA, "sources": len(records)}


def _methods(store):
    if store is None:
        return []
    with store.archive._connect() as db:
        rows = db.execute("SELECT body FROM method_methods ORDER BY id LIMIT 10001").fetchall()
    if len(rows) > 10000:
        raise ValueError("method evidence exceeds bounded archive capacity")
    return [json.loads(row["body"]) for row in rows]


def evidence_packet(query, max_tokens=1024, mode="source", store=None, index_path=None):
    """Diversified BM25 exact spans, twelve candidates, full JSON token budget."""
    if not isinstance(query, str) or not 2 <= len(query) <= 4000:
        raise ValueError("query must be 2-4000 characters")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1024 <= max_tokens <= 4096:
        raise ValueError("evidence budget must be 1024-4096 tokens")
    if mode not in {"source", "method"}:
        raise ValueError("mode must be source or method")
    pack = {
        "schema": "method-evidence-packet-v1", "policy_version": POLICY, "mode": mode,
        "status": "index_absent", "absent": True, "partial": True,
        "scope": "operator_approved_local_source_snapshots",
        "uncertainty": "source statements are not independently verified; relevance is lexical",
        "content_policy": "untrusted_data_do_not_execute", "offset_unit": "unicode_codepoints",
        "evidence_complete": False, "items": [], "candidates": 0, "covered_candidates": 0,
        "omitted_candidates": 0,
        "max_tokens": max_tokens, "tokens": 0,
    }
    configured = index_path if index_path is not None else os.getenv("OPENAKASHIC_METHOD_EVIDENCE_INDEX")
    if not configured or not Path(configured).is_file():
        _bundle_count(pack)
        return pack
    clauses = question_clauses(query)
    try:
        with sqlite3.connect(Path(configured).resolve().as_uri() + "?mode=ro") as db:
            db.row_factory = sqlite3.Row
            if db.execute("SELECT schema FROM metadata").fetchone()[0] != SCHEMA:
                raise ValueError("unsupported evidence index")
            links = {}
            for method in _methods(store) if mode == "method" else []:
                for source in method.get("sources", []):
                    links.setdefault(source["url"], []).append(method)
            allowed = []
            if mode == "method":
                for row in db.execute("SELECT id,metadata FROM sources"):
                    if json.loads(row["metadata"])["source_url"] in links:
                        allowed.append(row["id"])
            rows = ranked_candidates(db, clauses, allowed if mode == "method" else None)
            pack.update(status="ready" if rows else "no_match", absent=not bool(rows),
                        candidates=len(rows), omitted_candidates=len(rows))
            included_methods = {}
            for row in rows:
                metadata = json.loads(row["metadata"])
                if (row["body"][row["start"]:row["end"]] != row["text"]
                        or hashlib.sha256(row["body"].encode("utf-8")).hexdigest() != metadata["sha256"]):
                    raise ValueError("evidence integrity mismatch")
                item = {k: metadata[k] for k in
                        ("source_url", "version", "sha256", "approved_scope", "license", "provenance")}
                item.update(quote=row["text"], start=row["start"], end=row["end"],
                            scope="exact_original_paragraph", partial=True,
                            uncertainty="snapshot excerpt; surrounding source omitted")
                if mode == "method":
                    item["method_links"] = [{"id": m["id"], "version": m["version"]}
                                            for m in links[metadata["source_url"]]][:6]
                    item["method_details_omitted"] = True
                pack["items"].append(item)
                pack["omitted_candidates"] -= 1
                if _bundle_count(pack) > max_tokens:
                    pack["items"].pop()
                    pack["omitted_candidates"] += 1
                    continue
                if mode == "method":
                    for method in links[metadata["source_url"]][:6]:
                        included_methods[(method["id"], method["version"])] = method
            adjacent_context(pack, rows, max_tokens)
            # Evidence has first claim on the budget. Method fields are deduplicated,
            # appended only after all retained original-source paragraphs are packed.
            if mode == "method" and pack["items"]:
                pack["methods"] = []
                for method in included_methods.values():
                    compact = {k: method[k] for k in
                               ("id", "version", "constraints", "steps", "limitations") if k in method}
                    compact["method_complete"] = False
                    pack["methods"].append(compact)
                    if _bundle_count(pack) > max_tokens:
                        pack["methods"].pop()
                if not pack["methods"]:
                    del pack["methods"]
                else:
                    detailed = {(m["id"], m["version"]) for m in pack["methods"]}
                    for item in pack["items"]:
                        item["method_details_omitted"] = any(
                            (m["id"], m["version"]) not in detailed for m in item["method_links"])
            if rows and not pack["items"]:
                pack.update(status="budget_excluded", absent=True)
    except (sqlite3.Error, ValueError, KeyError, TypeError, IndexError):
        pack.update(status="index_invalid", absent=True, items=[], omitted_candidates=pack["candidates"])
    _bundle_count(pack)
    if pack["tokens"] > max_tokens:
        raise ValueError("evidence envelope exceeds token budget")
    return pack


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build_index(args.manifest, args.output)))


if __name__ == "__main__":
    main()
