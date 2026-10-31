"""Canonical evidence references and exact host-side rendering. No model or URL calls."""
import argparse
import copy
from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from app.research_method_context import _bundle_count
from app.research_method_evidence import LICENSES, SCHEMA, _methods, passages, retrieval_terms
from app.research_store import public_uri
from app.research_evidence_units import (UNIT_POLICY, anchored_sources, build_reference_index,
                                         is_markdown, markdown_sections, safe_span, search_terms,
                                         structural_frames)

PACKET_SCHEMA = "method-evidence-refs-v3"
POLICY = "anchored-normalized-units-v4"
SOURCE_FIELDS = ("source_url", "sha256", "version", "approved_scope", "provenance", "license", "approval")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                                     sort_keys=True).encode("utf-8")).hexdigest()


def make_ref(source_url, sha256, start, end, quote):
    """Content-address an exact span, not its semantic meaning or applicability."""
    public_uri(source_url)
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("pinned source sha256 required")
    if (type(start) is not int or type(end) is not int or start < 0 or end <= start
            or not isinstance(quote, str) or len(quote) != end-start):
        raise ValueError("invalid exact character span")
    return {"evidence_id": "ev_"+_hash([source_url, sha256, start, end, quote])[:32],
            "source_id": "src_"+_hash([source_url, sha256])[:32],
            "quote": quote, "start": start, "end": end}


def _read_action(source_id,start_line,end_line):
    return {"id":source_id,"start":start_line,"lines":min(160,end_line-start_line+1),
            "unit":"one_based_lines"}


def _source_descriptor(metadata,body):
    source_id="src_"+_hash([metadata["source_url"],metadata["sha256"]])[:32]
    total=max(1,len(body.splitlines()))
    return {**metadata,"read_url":metadata["source_url"],"total_lines":total,
            "offset_unit":"unicode_codepoints","start_line":1,"end_line":total,
            "read_action":_read_action(source_id,1,total)}


def _item_descriptor(ref,body):
    first=body.count("\n",0,ref["start"])+1
    last=body.count("\n",0,max(ref["start"],ref["end"]-1))+1
    return {**ref,"offset_unit":"unicode_codepoints","start_line":first,"end_line":last,
            "read_action":_read_action(ref["source_id"],first,last)}


def _approved_metadata(metadata):
    result = {key: metadata[key] for key in SOURCE_FIELDS}
    if result["approval"] != "approved_public_source":
        raise ValueError("unapproved source")
    for name in ("version", "approved_scope", "provenance"):
        if not isinstance(result[name], str) or not result[name].strip():
            raise ValueError("missing provenance")
    public_uri(result["source_url"])
    license_ = result["license"]
    if (license_.get("spdx") not in LICENSES
            or license_.get("reviewed_for_publication") is not True):
        raise ValueError("reviewed public redistribution license required")
    public_uri(license_["url"])
    return result


def _public_license(license_):
    """Public rights/provenance fields only; operator file pointers never leave."""
    required={"spdx","url","reviewed_for_publication"}
    allowed=required|{"sha256","attribution","copyright","notice"}
    if not isinstance(license_,dict) or not required<=license_.keys():
        raise ValueError("public license metadata required")
    result={key:value for key,value in license_.items() if key in allowed}
    if result["spdx"] not in LICENSES or result["reviewed_for_publication"] is not True:
        raise ValueError("reviewed public redistribution license required")
    public_uri(result["url"])
    if "sha256" in result and (not isinstance(result["sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",result["sha256"])):
        raise ValueError("invalid public license hash")
    for name in ("attribution","copyright","notice"):
        if name not in result:continue
        value=result[name]
        if (not isinstance(value,str) or not value.strip() or len(value)>2000
                or re.search(r"file://|[A-Za-z]:[\\/]|\\\\|(?<![:\w/])/(?!/)[\w.-]+",value)):
            raise ValueError("attribution must be public text without local paths")
    return result


def _public_metadata(metadata):
    result=_approved_metadata(metadata)
    result["license"]=_public_license(result["license"])
    return result


def public_projection(packet):
    """Pure emitted-boundary projection AFTER evaluated packing decisions.

    No text, IDs, ranking, source identity or ranges change. Token counters count
    the public JSON; original benchmark usage/context counters remain separate.
    """
    if not isinstance(packet,dict):raise ValueError("packet object required")
    result=copy.deepcopy(packet)
    for source in result.get("sources",{}).values():
        source["license"]=_public_metadata(source)["license"]
    if isinstance(result.get("evidence"),list):
        for citation in result["evidence"]:
            citation["license"]=_public_license(citation["license"])
    _bundle_count(result)
    return result


class ApprovedIndex(AbstractContextManager):
    """One read-only snapshot and one body-hash check per source per operation."""
    def __init__(self, path=None):
        configured = path if path is not None else (os.getenv("OPENAKASHIC_METHOD_REFS_INDEX")
                                                    or os.getenv("OPENAKASHIC_METHOD_EVIDENCE_INDEX"))
        if not configured or not Path(configured).is_file():
            raise ValueError("approved evidence index absent")
        self.db = sqlite3.connect(Path(configured).resolve().as_uri()+"?mode=ro")
        self.db.row_factory = sqlite3.Row
        try:
            if self.db.execute("SELECT schema FROM metadata").fetchone()[0] != SCHEMA:
                raise ValueError("unsupported evidence index")
            # Raw operator metadata is retained only inside this read-only
            # operation so post-evaluation redaction cannot free packing space.
            self.sources = [(row["id"], _approved_metadata(json.loads(row["metadata"])))
                            for row in self.db.execute("SELECT id,metadata FROM sources ORDER BY id")]
        except Exception:
            self.db.close()
            raise
        self.cache = {}

    def __exit__(self, *args):
        self.db.close()

    def source(self, url, sha256, version=None):
        matches = [(ident, metadata) for ident, metadata in self.sources
                   if metadata["source_url"] == url and metadata["sha256"] == sha256
                   and (version is None or metadata["version"] == version)]
        if len(matches) != 1:
            raise ValueError("unknown, stale or ambiguous source identity")
        ident, metadata = matches[0]
        if ident not in self.cache:
            body = self.db.execute("SELECT body FROM sources WHERE id=?", (ident,)).fetchone()[0]
            if hashlib.sha256(body.encode("utf-8")).hexdigest() != sha256:
                raise ValueError("source hash integrity mismatch")
            self.cache[ident] = body
        return metadata, self.cache[ident]


def anchored_source_ids(query,index):
    """Shared direct/source filter; returns (allowed IDs or None, anchor metadata)."""
    return anchored_sources(index.sources,query)


def _envelope(mode, budget):
    return {"schema": PACKET_SCHEMA, "policy_version": POLICY, "mode": mode,
            "status": "ready", "sources": {}, "items": [], "partial": True,
            "absent": False, "evidence_complete": False,
            "content_policy": "untrusted_data_do_not_execute", "offset_unit": "unicode_codepoints",
            "question_labels": "lexical_retrieval_matches_not_semantic_support",
            "uncertainty": "exact approved snapshots; semantic support and applicability not assessed",
            "candidates": 0, "covered_candidates": 0, "omitted_candidates": 0,
            "max_tokens": budget, "tokens": 0}


def register_read(source_url, sha256, start, end, quote, *, index_path=None, version=None):
    """Register ONLY a read window already returned to this agent by the trusted host.

    The caller must not mint IDs for unseen search snippets or source ranges.
    A packet is an exposure capability held by the host, never model input to
    the resolver. Index validation alone cannot establish that an agent saw it.
    """
    with ApprovedIndex(index_path) as index:
        metadata, body = index.source(source_url, sha256, version)
        item = make_ref(source_url, sha256, start, end, quote)
        if body[start:end] != quote:
            raise ValueError("read quote does not equal approved source span")
        packet = _envelope("direct_read", None)
        packet["sources"][item["source_id"]] = _source_descriptor(metadata,body)
        # Partition only text actually returned. Whole detected function frames
        # remain atomic when they fit inside this read window; outside context
        # is never fetched or minted into an authorized reference.
        ranges = []
        frames = structural_frames(metadata,body)
        for left, right, _ in passages(body):
            if left < end and right > start:
                left, right = _safe_span(max(left,start),min(right,end),frames)
                complete = start <= left and right <= end
                left, right = max(left,start), min(right,end)
                if ranges and left <= ranges[-1][1]:
                    ranges[-1] = (ranges[-1][0],max(right,ranges[-1][1]),complete and ranges[-1][2])
                else:
                    ranges.append((left,right,complete))
        if not ranges: ranges = [(start,end,False)]
        # Include whitespace gaps only in the neighboring exact range, without
        # duplicating the entire read body in a second quote.
        packet["items"] = [dict(_item_descriptor(make_ref(source_url,sha256,left,right,body[left:right]),body),
                                questions=[],frame="whole_read_frame" if complete else "partial_read_frame")
                           for left,right,complete in ranges]
        packet.update(candidates=len(ranges), covered_candidates=len(ranges))
        _bundle_count(packet)
        return public_projection(packet)


def render_citations(selections, packets, *, index_path=None):
    """Resolve IDs from trusted actual exposures, fail closed on any invalid ID.

    This checks exact public provenance, not the correctness of an answer. The
    host must retain the packets itself; never accept a model-supplied packet.
    """
    if not isinstance(selections, dict) or len(selections) > 32:
        raise ValueError("question-to-evidence-ID object required")
    if not isinstance(packets, list) or len(packets) > 64:
        raise ValueError("bounded host-held exposure packets required")
    exposed = {}
    with ApprovedIndex(index_path) as index:
        for packet in packets:
            if packet.get("schema") != PACKET_SCHEMA or packet.get("policy_version") != POLICY:
                raise ValueError("unknown or stale exposure packet schema")
            for item in packet.get("items", []):
                metadata = packet["sources"][item["source_id"]]
                approved, body = index.source(metadata["source_url"], metadata["sha256"], metadata["version"])
                supplied=copy.deepcopy(metadata);expected_metadata=_source_descriptor(approved,body)
                supplied["license"]=_public_license(supplied["license"])
                expected_metadata["license"]=_public_license(expected_metadata["license"])
                if supplied != expected_metadata:
                    raise ValueError("source provenance was altered")
                metadata=supplied
                expected = _item_descriptor(make_ref(metadata["source_url"], metadata["sha256"],
                                                     item["start"], item["end"], item["quote"]),body)
                if any(item.get(k) != v for k, v in expected.items()) or body[item["start"]:item["end"]] != item["quote"]:
                    raise ValueError("evidence reference hash or span was altered")
                value = (expected, metadata)
                if item["evidence_id"] in exposed and exposed[item["evidence_id"]] != value:
                    raise ValueError("ambiguous exposure identity")
                exposed[item["evidence_id"]] = value
        chosen = {}
        for question, ids in selections.items():
            if not re.fullmatch(r"q[1-9]\d{0,2}", question) or not isinstance(ids, list) or len(ids) > 12:
                raise ValueError("invalid question evidence selection")
            for ident in ids:
                if not isinstance(ident, str) or ident not in exposed:
                    raise ValueError("unknown or unexposed evidence ID")
                chosen.setdefault(ident, [])
                if question not in chosen[ident]:
                    chosen[ident].append(question)
        rendered = []
        for ident, questions in chosen.items():
            item, source = exposed[ident]
            rendered.append({"url": source["source_url"], "quote": item["quote"], "supports": questions,
                             "evidence_id": ident, "sha256": source["sha256"], "version": source["version"],
                             "start": item["start"], "end": item["end"],
                             "offset_unit":"unicode_codepoints","start_line":item["start_line"],
                             "end_line":item["end_line"],"read_action":item["read_action"],
                             "read_url":source["source_url"],
                             "approved_scope": source["approved_scope"], "license": source["license"],
                             "provenance": source["provenance"], "semantic_support": "not_assessed"})
    result = {"schema": "rendered-evidence-v3", "evidence": rendered,
              "semantic_support": "not_assessed", "content_policy": "untrusted_data_do_not_execute",
              "tokens": 0}
    _bundle_count(result)
    return public_projection(result)


def labelled_clauses(query):
    question = re.split(r"(?:\n| )Return JSON only:", query, maxsplit=1)[0]
    markers = list(re.finditer(r"\b[qQ]([1-9]\d{0,2})\b\s*(?:\([^\n)]{1,40}\))?\s*[:.)]?", question))
    chunks = []
    if markers:
        chunks.append(("scenario", question[:markers[0].start()]))
        chunks.extend(("q"+m.group(1), question[m.end():markers[i+1].start() if i+1<len(markers) else len(question)])
                      for i, m in enumerate(markers))
    else:
        chunks = [("scenario", chunk) for chunk in re.split(r"(?<=[?;])\s+|\n+", question)]
    result = [(label, list(dict.fromkeys(search_terms(text)))[:256]) for label, text in chunks if search_terms(text)]
    return result if len(result) <= 8 else result[:4]+result[-4:]


def _candidates(index, clauses, allowed, trace=None):
    if allowed == []:
        return []
    restriction = "" if allowed is None else " AND p.source_id IN ("+",".join(str(int(i)) for i in allowed)+")"
    groups, questions = [], {}
    for label, terms in sorted(clauses,key=lambda item:item[0]=="scenario"):
        expression = " OR ".join('"'+term+'"' for term in terms)
        group = [dict(row) for row in index.db.execute(
            "SELECT p.source_id,p.start,p.end,p.kind,p.text,p.heading,s.metadata,bm25(reference_units,1.0,1.5) AS rank "
            "FROM reference_units p JOIN sources s ON s.id=p.source_id WHERE reference_units MATCH ?"+restriction+
            " ORDER BY rank,s.id,p.start LIMIT 12", (expression,))]
        # RRF combines unit BM25 with distinct normalized query-term coverage.
        # A single rare generic word should not outrank a whole relevant frame
        # containing several independent parts of the question.
        for rank,row in enumerate(group):
            row["bm25_rank"]=rank+1
            row["coverage"]=len(set(terms)&set((row["text"]+" "+row["heading"]).split()))
        coverage_order=sorted(group,key=lambda row:(-row["coverage"],row["rank"],row["source_id"],row["start"]))
        coverage_rank={id(row):rank+1 for rank,row in enumerate(coverage_order)}
        for row in group:row["rrf"]=1/(60+row["bm25_rank"])+1/(60+coverage_rank[id(row)])
        group.sort(key=lambda row:(-row["rrf"],row["rank"],row["source_id"],row["start"]))
        if group:
            threshold=max(1,(max(row["coverage"] for row in group)+1)//2)
            group=[row for row in group if row["coverage"]>=threshold][:1 if label=="scenario" else 3]
        if trace is not None:
            trace.append({"question":label,"terms":terms,"ranked_units":[
                {"source_url":json.loads(row["metadata"])["source_url"],"start":row["start"],
                 "end":row["end"],"kind":row["kind"],"bm25":row["rank"],
                 "term_coverage":row["coverage"],"rrf":row["rrf"]} for row in group]})
        for row in group:
            questions.setdefault((row["source_id"],row["start"],row["end"]), [])
            if label not in questions[(row["source_id"],row["start"],row["end"])]:
                questions[(row["source_id"],row["start"],row["end"])].append(label)
        groups.append(group)
    rows, seen = [], set()
    for depth in range(12):
        for group in groups:
            if depth >= len(group):
                continue
            row = group[depth]
            key = (row["source_id"],row["start"],row["end"])
            if key not in seen:
                rows.append(dict(row, questions=questions[key]))
                seen.add(key)
                if len(rows) == 12:
                    return rows
    return rows


def inspect_candidate_rank(query, *, index_path=None):
    """Offline lexical diagnostics only: approved scope and per-clause unit ranks."""
    with ApprovedIndex(index_path) as index:
        allowed,anchoring=anchored_source_ids(query,index)
        trace=[]
        selected=_candidates(index,labelled_clauses(query),allowed,trace)
        return {"policy_version":POLICY,"anchoring":anchoring,"clauses":trace,
                "selected":[{"source_url":json.loads(row["metadata"])["source_url"],
                             "start":row["start"],"end":row["end"],"questions":row["questions"],
                             "kind":row["kind"]} for row in selected]}


def function_frames(body):
    """Conservative braced function boundaries, ignoring strings/comments.

    This is a lexical boundary aid, not a parser or code execution. Unknown
    languages remain paragraph-based; detected oversized functions are omitted.
    """
    frames, stack, state, escape = [], [], None, False
    i = 0
    while i < len(body):
        char, pair = body[i], body[i:i+2]
        if state == "line":
            if char == "\n": state = None
        elif state == "comment":
            if pair == "*/": state = None; i += 1
        elif state:
            if escape: escape = False
            elif char == "\\": escape = True
            elif char == state: state = None
        elif pair == "//": state = "line"; i += 1
        elif pair == "/*": state = "comment"; i += 1
        elif char in "\"'`": state = char
        elif char == "{":
            boundary = max(body.rfind("\n\n", 0, i), body.rfind("}", 0, i), body.rfind(";", 0, i))+1
            prefix = body[boundary:i]
            method = re.search(
                r"(?m)^[ \t]*(?:(?:public|private|protected|static|async|readonly|override)\s+)*"
                r"([A-Za-z_$][\w$]*)\s*(?:<[^{};]*>)?\s*\([^{};]*\)\s*[^{};=]*$", prefix)
            method_declaration = bool(method and method.group(1) not in
                                      {"if","for","while","switch","catch","with"})
            declaration = (bool(re.search(r"\bfunction\s*[\w$]*\s*(?:<[^>]*>)?\s*\(", prefix))
                           or "=>" in prefix or method_declaration)
            start = boundary+method.start() if method_declaration else boundary
            while start < i and body[start].isspace(): start += 1
            stack.append((start, declaration))
        elif char == "}" and stack:
            start, declaration = stack.pop()
            if declaration: frames.append((start, i+1))
        i += 1
    return frames


def _safe_span(start, end, frames):
    # Never cut a detected function branch at an internal blank line.
    changed = True
    while changed:
        changed = False
        for left, right in frames:
            if left < end and right > start and (left < start or right > end):
                start, end = min(start,left), max(end,right)
                changed = True
    return start, end


def _put_span(packet, metadata, body, start, end, questions, frame, budget):
    """Merge overlapping exact spans, retaining a single source metadata entry."""
    ref = make_ref(metadata["source_url"], metadata["sha256"], start, end, body[start:end])
    before_items, before_sources = packet["items"], packet["sources"]
    overlap = [item for item in before_items if item["source_id"] == ref["source_id"]
               and item["start"] <= end and item["end"] >= start]
    if overlap:
        start = min([start]+[item["start"] for item in overlap])
        end = max([end]+[item["end"] for item in overlap])
        questions = list(dict.fromkeys(questions+[q for item in overlap for q in item["questions"]]))
        ref = make_ref(metadata["source_url"], metadata["sha256"], start, end, body[start:end])
    item = dict(_item_descriptor(ref,body), questions=questions, frame=frame)
    proposed = [item_ for item_ in before_items if item_ not in overlap]
    position = min((before_items.index(item_) for item_ in overlap), default=len(proposed))
    proposed.insert(position, item)
    packet["items"] = proposed
    packet["sources"] = dict(before_sources, **{ref["source_id"]: _source_descriptor(metadata,body)})
    if _bundle_count(packet) > budget:
        packet["items"], packet["sources"] = before_items, before_sources
        return False
    return True


def reference_packet(query, max_tokens=1024, mode="source", store=None, index_path=None):
    if not isinstance(query, str) or not 2 <= len(query) <= 4000:
        raise ValueError("query must be 2-4000 characters")
    if type(max_tokens) is not int or not 1024 <= max_tokens <= 4096:
        raise ValueError("evidence budget must be 1024-4096 tokens")
    if mode not in {"source", "method"}:
        raise ValueError("mode must be source or method")
    packet = _envelope(mode, max_tokens)
    configured = index_path if index_path is not None else (os.getenv("OPENAKASHIC_METHOD_REFS_INDEX")
                                                          or os.getenv("OPENAKASHIC_METHOD_EVIDENCE_INDEX"))
    if not configured or not Path(configured).is_file():
        packet.update(status="index_absent", absent=True)
        _bundle_count(packet)
        return packet
    try:
        with ApprovedIndex(configured) as index:
            try:
                unit_policy=index.db.execute("SELECT policy FROM reference_search_metadata").fetchone()[0]
            except sqlite3.Error:
                unit_policy=None
            if unit_policy!=UNIT_POLICY:
                packet.update(status="index_upgrade_required",absent=True)
                _bundle_count(packet)
                return packet
            methods, links = _methods(store) if mode == "method" else [], {}
            for method in methods:
                for source in method.get("sources", []): links.setdefault(source["url"], []).append(method)
            allowed,anchoring=anchored_source_ids(query,index)
            packet["anchoring"]=anchoring
            if mode=="method":
                method_allowed=[ident for ident, metadata in index.sources if metadata["source_url"] in links]
                allowed=[ident for ident in method_allowed if allowed is None or ident in allowed]
            rows = _candidates(index, labelled_clauses(query), allowed)
            packet.update(candidates=len(rows), omitted_candidates=len(rows))
            cache, seeds = {}, []
            for row in rows:
                raw = json.loads(row["metadata"])
                metadata, body = index.source(raw["source_url"], raw["sha256"], raw["version"])
                key = (metadata["source_url"], metadata["sha256"], metadata["version"])
                if key not in cache: cache[key] = (metadata, body, list(passages(body)), structural_frames(metadata,body))
                _, _, paragraphs, frames = cache[key]
                start, end = _safe_span(row["start"], row["end"], frames)
                if _put_span(packet, metadata, body, start, end, row["questions"],
                             "whole_function" if (start,end)!=(row["start"],row["end"]) else "whole_paragraph", max_tokens):
                    seeds.append((key,start,end,row["questions"]))
            # Do not fill unused budget with unrelated functions or cross-section
            # Markdown. Keep whole structural units and a bounded local qualifier.
            for key, start, end, questions in seeds:
                metadata, body, paragraphs, frames = cache[key]
                first = next(i for i,p in enumerate(paragraphs) if p[1]>start)
                last = max(i for i,p in enumerate(paragraphs) if p[0]<end)
                if any(left<end and right>start for left,right in frames):
                    continue
                windows = [(max(0,first-1),min(len(paragraphs)-1,last+1)),
                           (first,min(len(paragraphs)-1,last+1)),(max(0,first-1),last)]
                for first_, last_ in windows:
                    left, right = min(start,paragraphs[first_][0]), max(end,paragraphs[last_][1])
                    if is_markdown(metadata,body):
                        section=next(((a,b) for a,b,_ in markdown_sections(body) if a<=start<b),None)
                        if section:left,right=max(left,section[0]),min(right,section[1])
                    elif any(a<right and b>left and not (a<end and b>start) for a,b in frames):
                        continue
                    left, right = _safe_span(left,right,frames)
                    if _put_span(packet, metadata, body, left, right, questions, "contiguous_context", max_tokens):
                        break
            covered = sum(any(item["source_id"] == "src_"+_hash([json.loads(row["metadata"])["source_url"],json.loads(row["metadata"])["sha256"]])[:32]
                              and item["start"] <= row["start"] and item["end"] >= row["end"]
                              for item in packet["items"]) for row in rows)
            packet.update(covered_candidates=covered, omitted_candidates=len(rows)-covered)
            if mode == "method" and packet["items"]:
                packet["methods"] = []
                urls = {m["source_url"] for m in packet["sources"].values()}
                for method in methods:
                    if any(s["url"] in urls for s in method.get("sources", [])):
                        compact = {k:method[k] for k in ("id","version","constraints","steps","limitations") if k in method}
                        packet["methods"].append(dict(compact, method_complete=False))
                        if _bundle_count(packet)>max_tokens: packet["methods"].pop()
                if not packet["methods"]: del packet["methods"]
            packet.update(status="ready" if packet["items"] else "budget_excluded" if rows else "no_match", absent=not bool(packet["items"]))
    except (sqlite3.Error, ValueError, KeyError, IndexError, TypeError):
        packet = _envelope(mode,max_tokens)
        packet.update(status="index_invalid",absent=True)
    _bundle_count(packet)
    if packet["tokens"]>max_tokens: raise ValueError("reference envelope exceeds budget")
    return public_projection(packet)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", help="Operator-installed approved SQLite index")
    parser.add_argument("--build-manifest",help="Build a normalized reference index from an operator-approved local manifest")
    parser.add_argument("--packet", action="append", help="Host-held actually exposed packet JSON; repeatable")
    parser.add_argument("--selections", help="JSON object mapping q IDs to evidence IDs")
    parser.add_argument("--output", help="Write rendered evidence JSON here")
    args = parser.parse_args()
    if args.build_manifest:
        if not args.output:parser.error("--build-manifest requires --output")
        print(json.dumps(build_reference_index(args.build_manifest,args.output)))
        return
    if not args.packet or not args.selections:parser.error("rendering requires --packet and --selections")
    result = render_citations(json.loads(Path(args.selections).read_text(encoding="utf-8")),
                              [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.packet], index_path=args.index)
    text = json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output: Path(args.output).write_text(text,encoding="utf-8")
    else: print(text,end="")


if __name__ == "__main__":
    main()
