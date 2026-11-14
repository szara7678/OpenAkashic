"""Subject/topic recall contracts with adversarial deterministic embeddings."""
import sqlite3

import pytest

from app.research_method_search import SearchConfig, SearchUnavailable, build_index, declared_subjects, search_methods
from app.research_method_store import MethodStore
from app.research_store import ResearchStore

CONFIG = SearchConfig(model="fake", revision="pinned", embedding_spec="unit-v1")


class Embeddings:
    def __init__(self, weak=False, unavailable=False):
        self.weak, self.unavailable = weak, unavailable

    def embed(self, texts, input_type):
        if self.unavailable:
            raise SearchUnavailable("offline")
        return [[1, 0] if input_type == "document" or not self.weak else [0, 1] for _ in texts]


@pytest.fixture
def corpus(tmp_path):
    store = MethodStore(ResearchStore(tmp_path / "public.sqlite3"))
    base = {"title": "Needle startup checks", "situation": "느린 시작과 일시적 비준비를 나눈다",
            "goal": "검사별 복구 목적을 구분한다", "constraints": ["Needle access"],
            "steps": ["Configure startupProbe and readinessProbe separately"],
            "success_criteria": ["Observe probe behavior"], "limitations": ["Review actual environment"],
            "tags": ["Needle", "운영"], "agent_name": "fixture", "public_source_only": True,
            "evidence_kind": "documented_method", "sources": [{"url": "https://needle.org/probes",
            "title": "Needle startup readiness probes"}], "constraint_rules": {"requires": ["linux"], "forbids": []}}
    target = store.create_method(base, "needle")
    other = store.create_method({**base, "title": "Other startup checks", "tags": ["Other"],
        "constraints": ["Other access"], "sources": [{"url": "https://other.org/probes", "title": "Other startup readiness probes"}]}, "other")
    index = tmp_path / "index.sqlite3"
    build_index(store, index, Embeddings(), CONFIG)
    return store, target, other, index


def run(corpus, **kwargs):
    store, _, _, index = corpus
    return search_methods(store, kwargs.pop("situation", "Needle startupProbe initialization"),
        kwargs.pop("goal", "Configure readiness probes"), config=CONFIG, index_path=index,
        embedder=kwargs.pop("embedder", Embeddings(weak=True)), **kwargs)


def test_hybrid_exact_subject_topic_recall_is_labeled_below_unchanged_floors(corpus):
    result = run(corpus)
    assert [r["method"]["id"] for r in result["results"]] == [corpus[1]["id"]]
    match = result["results"][0]["match"]
    assert match["retrieval_basis"] == "declared_subject_topic_lexical"
    assert not match["semantic_eligible"] and match["ranks"]["semantic"] is None
    assert match["ranks"]["lexical"] == 1
    assert match["subject_match"]["topic_terms"]["goal"]
    assert result["search"]["floors"] == {"situation": .55, "goal": .62}
    assert run(corpus, mode="semantic")["results"] == []


def test_cross_product_semantic_false_positive_and_mixed_subjects_abstain(corpus):
    result = run(corpus, embedder=Embeddings())
    assert [r["method"]["id"] for r in result["results"]] == [corpus[1]["id"]]
    assert run(corpus, situation="Needle and Other startupProbe", goal="readiness probes", embedder=Embeddings())["results"] == []
    assert result["search"]["subject_unknown_methods"] == 1


def test_subject_alone_does_not_rescue_unrelated_topic_or_plural_alias(corpus):
    assert run(corpus, situation="Needle charts colors", goal="Needle marketing drawings", embedder=Embeddings())["results"] == []
    assert run(corpus, product="unknown-product", embedder=Embeddings())["results"] == []


@pytest.mark.parametrize("change", ["source_hash", "version", "unavailable"])
def test_lexical_recall_never_bypasses_stale_or_unavailable_semantics(corpus, change):
    store, method, _, index = corpus
    if change != "unavailable":
        with sqlite3.connect(index) as db:
            db.execute("UPDATE embeddings SET " + change + "=? WHERE method_id=?", (999 if change == "version" else "stale", method["id"]))
    result = run(corpus, embedder=Embeddings(weak=True, unavailable=change == "unavailable"))
    assert result["results"] == []
    if change == "unavailable":
        assert not result["search"]["available"]
    else:
        assert result["search"]["stale_or_missing_methods"] == 1


def test_constraints_and_exact_scope_still_precede_recall(corpus):
    assert run(corpus, forbids=["linux"])["results"] == []
    assert run(corpus, product="Other")["results"] == []
    assert run(corpus, domain="학습")["results"] == []
    assert run(corpus, product="Needle")["results"][0]["method"]["version"] == 1


def test_source_identity_requires_written_corroboration_not_url_path():
    method = {"title": "결측 정책", "situation": "데이터 처리", "goal": "정책 비교", "tags": [],
        "constraints": ["pandas로 작업"], "sources": [{"url": "https://pandas.pydata.org/docs/missing_data.html",
        "title": "Working with missing data pandas documentation"}]}
    assert declared_subjects(method) == {"pandas"}
    method["constraints"] = []
    method["sources"][0]["title"] = "Working with missing data"
    assert declared_subjects(method) == set()


def test_secondary_language_anchor_does_not_override_different_title_product(corpus):
    store, _, _, index = corpus
    m = store.create_method({"title": "StoreDB backup", "situation": "Backup database source", "goal": "Verify backup source",
        "constraints": ["Python environment"], "steps": ["Backup source"], "success_criteria": ["Compare source"],
        "limitations": ["Review"], "tags": ["StoreDB", "Python"], "agent_name": "fixture", "public_source_only": True,
        "evidence_kind": "documented_method", "sources": [{"url": "https://python.org/backup", "title": "Python backup source"}]}, "db")
    build_index(store, index, Embeddings(), CONFIG)
    r = run(corpus, situation="Python HTTP source client", goal="Verify source HTTP", embedder=Embeddings())
    assert m["id"] not in [x["method"]["id"] for x in r["results"]]


@pytest.mark.parametrize("budget", [512, 2048])
def test_packed_candidates_retain_lexical_basis_when_full_or_fetch_only(corpus, budget):
    from app.research_method_context import counted, pack_bundle, pack_context
    result = run(corpus)
    # 512 fits the reference envelope; 256 may correctly omit the entire candidate.
    # Force small budgets down the fetch-only path while preserving exact IDs.
    result["results"][0]["method"]["limitations"] = ["Review full method. " * 100]
    for packer in (pack_bundle, pack_context):
        pack = packer(result, budget)
        assert counted(pack) <= budget
        assert pack["items"]
        item = pack["items"][0]
        assert item["retrieval_basis"] == "declared_subject_topic_lexical"
        assert item["semantic_eligible"] is False
        assert item["id"] == corpus[1]["id"] and item["version"] == 1
