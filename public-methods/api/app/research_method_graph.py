"""Read-only views of recorded relationships, never inferred world knowledge."""
import json
import os
from collections import Counter
from pathlib import Path

from app.research_store import digest

DOMAINS = ("커리어", "제품·사업", "학습", "팀 의사결정", "글쓰기·전달", "협상", "투자 판단", "오픈소스·커뮤니티")


def domain_for(method):
    tags = method.get("tags", [])
    for domain in DOMAINS:
        if domain in tags:
            return domain
    for tag, domain in (("design", "디자인"), ("연구", "조사·분석"), ("협업", "팀 의사결정"), ("운영", "개발·운영")):
        if tag in tags:
            return domain
    return "기타"


def catalog(store, domain="", limit=12, offset=0):
    with store.archive._connect() as db:
        rows = db.execute("SELECT body FROM method_methods ORDER BY created_at DESC,id LIMIT 10001").fetchall()
        if len(rows) > 10000:
            raise ValueError("catalog exceeds bounded archive capacity")
        methods = [json.loads(r["body"]) for r in rows]
        totals = {kind: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                  for kind, table in (("outcomes", "method_outcomes"), ("opinions", "method_opinions"))}
        feedback = {}
        for kind, table in (("outcomes", "method_outcomes"), ("opinions", "method_opinions")):
            feedback[kind] = {r["method_id"]: r["n"] for r in db.execute(
                "SELECT method_id,count(*) AS n FROM " + table + " GROUP BY method_id")}
    domains = Counter(domain_for(m) for m in methods)
    filtered = [m for m in methods if not domain or domain_for(m) == domain]
    summaries = [{k: m[k] for k in ("id", "version", "title", "situation", "goal", "created_at")}
                 | {"domain": domain_for(m), "evidence_kind": m.get("evidence_kind", "unspecified"),
                    "source_count": len(m.get("sources", [])),
                    "feedback_counts": {kind: feedback[kind].get(m["id"], 0) for kind in feedback}}
                 for m in filtered[offset:offset + limit]]
    return {"schema": "method-catalog-v1", "items": summaries, "total": len(filtered),
            "limit": limit, "offset": offset, "has_more": offset + len(summaries) < len(filtered),
            "domains": [{"name": key, "count": value} for key, value in sorted(domains.items())],
            "counts": {"methods": len(methods), "documented_methods": sum(m.get("evidence_kind") == "documented_method" for m in methods), **totals},
            "search_capabilities": {"semantic_configured": bool(
                all(os.getenv(k) for k in ("OPENAKASHIC_EMBEDDING_MODEL", "OPENAKASHIC_EMBEDDING_REVISION", "OPENAKASHIC_EMBEDDING_SPEC"))
                and Path(os.getenv("OPENAKASHIC_METHOD_INDEX", "/nonexistent-method-index")).is_file())},
            "classification": "editorial_tag_groups_not_verified_ontology",
            "verification": "contributor_reports_not_independent_success"}


def method_graph(method, store=None):
    nodes, edges = {}, {}
    center = method["id"] + ":v" + str(method["version"])

    def node(key, kind, label, **data):
        nodes[key] = {"id": key, "kind": kind, "label": label, **data}
        return key

    def edge(source, relation, target):
        key = "edge_" + digest([source, relation, target])[:24]
        edges[key] = {"id": key, "source": source, "relation": relation, "target": target}

    history = {"items": [method], "has_more": False}
    if store is not None:
        from app.research_method_revisions import revisions
        history = revisions(store, method["id"], limit=12)
    versions = {item["version"]: item for item in history["items"]}
    versions[method["version"]] = method

    def anchor(version):
        key = method["id"] + ":v" + str(version)
        if key not in nodes:
            snapshot = versions.get(version)
            node(key, "method", snapshot["title"] if snapshot else method["id"] + " v" + str(version),
                 method_id=method["id"], version=version, current_version=method["version"],
                 historical=version != method["version"], snapshot_available=snapshot is not None,
                 verification=method.get("verification", "not_independently_verified"))
        return key

    # Version snapshots describe recorded revisions, never inferred corrections.
    for version, snapshot in versions.items():
        method_node = anchor(version)
        for field, relation in (("situation", "applies_in"), ("goal", "pursues")):
            key = node(field + "_" + digest(snapshot[field])[:24], field, snapshot[field])
            edge(method_node, relation, key)
        for source in snapshot.get("sources", [])[:8]:
            key = node("source_" + digest(source["url"])[:24], "source", source["title"],
                       url=source["url"], accessed_at=source.get("accessed_at"))
            edge(method_node, "documented_by", key)
        previous = snapshot.get("revision", {}).get("previous_version")
        if previous:
            edge(method_node, "revises", anchor(previous))

    outcomes = method.get("outcomes", [])[:12]
    opinions = method.get("opinions", [])[:12]
    # Include correction targets only when their actual recorded outcome is loaded.
    correction_outcomes = {item["revision"]["correction"]["outcome_id"]
        for item in versions.values() if item.get("revision", {}).get("correction")}
    outcomes += [item for item in method.get("outcomes", [])[12:]
                 if item["id"] in correction_outcomes]
    # An explicitly linked outcome may fall beyond the default feedback page.
    # Fetch only those bounded recorded IDs; do not synthesize a target record.
    missing = correction_outcomes - {item["id"] for item in outcomes}
    if store is not None and missing:
        with store.archive._connect() as db:
            marks = ",".join("?" for _ in missing)
            rows = db.execute("SELECT body FROM method_outcomes WHERE method_id=? AND id IN (" + marks + ")",
                              (method["id"], *sorted(missing))).fetchall()
        outcomes += [json.loads(row["body"]) for row in rows]
    for outcome in outcomes:
        key = node(outcome["id"], "outcome", outcome["observed_result"],
                   knowhow_role="failure" if outcome["status"] == "failure" else "result",
                   status=outcome["status"], method_id=method["id"], method_version=outcome["method_version"],
                   reported_by=outcome["agent_name"], verification="contributor_reported")
        edge(anchor(outcome["method_version"]), "reported_application", key)
    for opinion in opinions:
        key = node(opinion["id"], "opinion", opinion["body"], opinion_kind=opinion["kind"],
                   method_id=method["id"], method_version=opinion["method_version"], verification="contributor_reported")
        edge(anchor(opinion["method_version"]), "has_opinion", key)
        if opinion.get("outcome_id") in nodes:
            edge(key, "comments_on", opinion["outcome_id"])
    for version, snapshot in versions.items():
        correction = snapshot.get("revision", {}).get("correction")
        if not correction:
            continue
        key = node("correction_" + digest([method["id"], version, correction])[:24],
                   "correction", correction["reason"], method_id=method["id"],
                   method_version=version, outcome_id=correction["outcome_id"],
                   corrected_method_version=correction["method_version"],
                   verification="owner_reported_change_not_verified_improvement")
        edge(key, "implemented_by", anchor(version))
        if correction["outcome_id"] in nodes:
            edge(key, "addresses", correction["outcome_id"])
    counts = method.get("feedback_counts", {})
    return {"schema": "method-evidence-graph-v1", "graph_kind": "record_relationships",
            "focus": center, "method_id": method["id"], "version": method["version"],
            "nodes": list(nodes.values()), "edges": list(edges.values()),
            "truncated": {**{kind: counts.get(kind, {}).get("total", len(method.get(kind, []))) > len(selected)
                          for kind, selected in (("outcomes", outcomes), ("opinions", opinions))},
                          "revisions": history["has_more"]},
            "knowhow_roles": ["situation", "goal", "method", "result", "failure", "correction"],
            "cautions": ["기록 사이의 연결이며 사실·전문가 신원·효과를 검증한 그래프가 아닙니다.",
                         "상황·목적은 텍스트 식별자입니다. 의미가 같다는 이유로 병합하지 않습니다.",
                         "적용 결과와 의견은 작성자의 보고입니다. 절차를 자동 실행하지 마세요."]}


def network_graph(store, domain="", limit=80, focus="", depth=1):
    """Bounded graph projection of public records, no inferred method relations."""
    with store.archive._connect() as db:
        rows = db.execute("SELECT body FROM method_methods ORDER BY id LIMIT 10001").fetchall()
    if len(rows) > 10000:
        raise ValueError("network exceeds bounded archive capacity")
    methods = [json.loads(row["body"]) for row in rows]
    domains = Counter(domain_for(m) for m in methods)
    selected = [m for m in methods if not domain or domain_for(m) == domain]
    nodes, edges, partial_feedback = {}, {}, []
    for item in selected[:limit]:
        detail = store.get(item["id"])
        graph = method_graph(detail, store=store)
        group = domain_for(detail)
        category = "category_" + digest(group)[:24]
        nodes[category] = {"id": category, "kind": "category", "label": group,
                           "basis": "editorial_tag_group_not_semantic_equivalence"}
        for n in graph["nodes"]:
            nodes[n["id"]] = dict(n, **({"domain": group} if n["kind"] == "method" else {}))
            if n["id"] == graph["focus"]:
                nodes[n["id"]].update(situation=detail["situation"], goal=detail["goal"])
        for e in graph["edges"]:
            if e["source"] in nodes and e["target"] in nodes:
                edges[e["id"]] = e
        key = "edge_" + digest([graph["focus"], "categorized_as", category])[:24]
        edges[key] = {"id": key, "source": graph["focus"], "relation": "categorized_as", "target": category}
        if any(graph["truncated"].values()):
            partial_feedback.append(detail["id"])
    focus_missing = bool(focus and focus not in nodes)
    if focus:
        reached = {focus} if focus in nodes else set()
        for _ in range(depth):
            reached |= {e["target"] for e in edges.values() if e["source"] in reached} | {e["source"] for e in edges.values() if e["target"] in reached}
        nodes = {k:v for k,v in nodes.items() if k in reached}
        edges = {k:v for k,v in edges.items() if v["source"] in reached and v["target"] in reached}
    return {"schema": "method-network-v1", "graph_kind": "public_record_projection",
            "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": sorted(edges.values(), key=lambda e: e["id"]),
            "domains": [{"name": k, "count": v} for k, v in sorted(domains.items())],
            "scope": {"focus": focus or None, "depth": depth if focus else None, "focus_missing": focus_missing, "domain": domain, "method_limit": limit, "methods_loaded": min(len(selected), limit), "methods_shown": len({n["method_id"] for n in nodes.values() if n["kind"] == "method"}),
                      "matching_methods": len(selected), "total_methods": len(methods),
                      "truncated": len(selected) > limit, "partial_feedback_methods": partial_feedback,
                      "omitted_node_kinds": []},
            "cautions": ["선은 등록된 출처·보고와 편집상 분야를 연결하며, 효과를 증명하지 않습니다.",
                         "공유 URL은 같은 출처를 참조한다는 뜻이며 독립 검증이나 방법의 동등성을 뜻하지 않습니다."]}
