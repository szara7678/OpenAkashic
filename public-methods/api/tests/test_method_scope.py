"""Scope regressions use ambiguous release terms, independent of investment query."""
import pytest
from app.research_method_search import SearchConfig, build_index, search_methods
from app.research_method_store import MethodStore
from app.research_store import ResearchStore
from test_research_methods import BASE, archive, method_payload, post

class AmbiguousEmbeddings:
    def embed(self, texts, input_type):
        return [[1.0, 0.0] for _ in texts]

@pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
def test_explicit_scope_precedes_ranking_and_limit(tmp_path, mode):
    store = MethodStore(ResearchStore(tmp_path / "scope.sqlite3"))
    base = {"title": "Release rollback checklist", "situation": "release rollback needed",
            "goal": "restore stable service", "constraints": [], "steps": ["Review rollback"],
            "success_criteria": ["Validate service"], "limitations": ["Check platform"],
            "tags": [], "agent_name": "fixture", "public_source_only": True}
    unknown = store.create_method(base, "unknown")
    other = store.create_method({**base, "tags": ["운영", "sqlite"]}, "other")
    target = store.create_method({**base, "tags": ["운영", "postgresql"],
                                  "constraint_rules": {"requires": ["network"], "forbids": []}}, "target")
    index = tmp_path / "index.sqlite3"
    config = SearchConfig(model="fixture", revision="frozen", embedding_spec="unit-v1")
    embeddings = AmbiguousEmbeddings()
    build_index(store, index, embeddings, config)
    def run(**scope):
        return search_methods(store, base["situation"], base["goal"], mode=mode,
                              config=config, embedder=embeddings, index_path=index, **scope)
    assert run()["total"] == 3
    scoped = run(domain="개발·운영", product="postgresql", limit=1)
    assert scoped["total"] == 1
    assert scoped["results"][0]["method"]["id"] == target["id"]
    assert "not_proven_incompatible" in scoped["scope"]["unknown_policy"]
    assert run(domain="투자 판단")["total"] == 0
    assert run(product="PostgreSQL")["total"] == 0
    assert run(product="postgresql", forbids=["network"])["total"] == 0
    unknown_condition = run(product="postgresql", forbids=["filesystem_write"])
    assert unknown_condition["total"] == 1
    assert unknown_condition["results"][0]["match"]["constraint_rules"]["status"] == "unknown"
    assert unknown["id"] != other["id"]

@pytest.mark.parametrize("route", ["search", "context", "bundle"])
def test_api_scope_forwarding_and_validation(archive, route):
    client, _ = archive
    response = post(client, "", {**method_payload(), "tags": ["운영", "postgresql"]}, "scope")
    assert response.status_code == 201, response.text
    method = response.json()
    query = {"situation": method["situation"], "goal": method["goal"], "mode": "lexical",
             "domain": "개발·운영", "product": "postgresql"}
    response = client.get(BASE + "/" + route, params=query)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scope"]["product"] == "postgresql"
    assert data.get("results", data.get("items"))
    empty = client.get(BASE + "/" + route, params={**query, "product": "sqlite"})
    assert empty.status_code == 200
    assert not empty.json().get("results", empty.json().get("items"))
    assert client.get(BASE + "/" + route, params={**query, "domain": "x" * 101}).status_code == 422

@pytest.mark.parametrize("route", ["context", "bundle"])
def test_long_scope_labels_fit_minimum_budget(archive, route):
    client, _ = archive
    response = client.get(BASE + "/" + route, params={"situation": "public release",
        "goal": "stable service", "mode": "lexical", "domain": "🧬" * 100,
        "product": "🧬" * 100, "max_tokens": 256})
    assert response.status_code == 200, response.text
    assert response.json()["tokens"] <= 256
