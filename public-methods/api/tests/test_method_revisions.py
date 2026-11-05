"""Isolated owner-revision contract; no production archive or remote writes."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.research import store_for_path
from app.research_methods import router
from app.research_method_revisions import router as revision_router
from app.research_store import ResearchStore
from app.research_method_store import MethodStore
from app.research_method_graph import method_graph, network_graph

BASE = "/research/api/methods"
AUTH = {"X-OpenAkashic-Key": "synthetic-owner", "Idempotency-Key": "method-create"}


def method():
    return dict(public_source_only=True, agent_name="synthetic fixture",
                title="Recorded document check", situation="Public fixture missing a quote",
                goal="Preserve traceable quotes", constraints=[], steps=["Compare fixture quotes"],
                success_criteria=["Record whether quotes match"], limitations=["Synthetic only"],
                evidence_kind="contributor_method", sources=[], tags=[])


@pytest.fixture
def archive(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_DB", str(path))
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_WRITE_KEY", AUTH["X-OpenAkashic-Key"])
    monkeypatch.delenv("OPENAKASHIC_RESEARCH_READ_ONLY", raising=False)
    store_for_path.cache_clear()
    app = FastAPI()
    app.include_router(router)
    app.include_router(revision_router)
    client = TestClient(app)
    created = client.post(BASE, json=method(), headers=AUTH)
    assert created.status_code == 201, created.text
    yield client, path, created.json()
    store_for_path.cache_clear()


def revision(expected_version=1, correction=None):
    payload = dict(expected_version=expected_version, method=method(), reason="Record a clearer quote comparison")
    payload["method"]["steps"] = ["Compare fixture quote text and record its source ID"]
    if correction is not None:
        payload["correction"] = correction
    return payload


def post(client, path, payload, key):
    return client.post(path, json=payload, headers={**AUTH, "Idempotency-Key": key})


def test_revision_is_owner_keyed_idempotent_and_preserves_original(archive):
    client, path, initial = archive
    endpoint = BASE + "/" + initial["id"] + "/revisions"
    data = revision()
    before = path.read_bytes()
    assert client.post(endpoint, json=data, headers={"Idempotency-Key": "anonymous"}).status_code == 401
    assert path.read_bytes() == before
    assert client.get(endpoint).json()["items"] == [initial]
    assert path.read_bytes() == before
    result = post(client, endpoint, data, "rev2")
    assert result.status_code == 201, result.text
    revised = result.json()
    assert revised["id"] == initial["id"] and revised["version"] == 2
    assert revised["created_at"] == initial["created_at"]
    assert post(client, endpoint, data, "rev2").json() == revised
    assert post(client, endpoint, data, "stale").status_code == 409
    changed = copy.deepcopy(data)
    changed["reason"] = "Different payload"
    assert post(client, endpoint, changed, "rev2").status_code == 409
    assert client.get(BASE + "/" + initial["id"] + "/versions/1").json() == initial
    assert client.get(BASE + "/" + initial["id"] + "/versions/2").json() == revised
    history = client.get(endpoint).json()
    assert [i["version"] for i in history["items"]] == [2, 1]
    assert history["total"] == 2 and not history["has_more"]
    assert client.get(endpoint + "?limit=1&offset=1").json()["items"] == [initial]
    assert client.get(BASE + "/" + initial["id"] + "/versions/3").status_code == 404
    # Public immutable reads still work in enforced read-only mode.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_READ_ONLY", "1")
    try:
        assert client.get(endpoint).status_code == 200
        assert post(client, endpoint, revision(2), "readonly").status_code == 403
    finally:
        monkeypatch.undo()


def test_revision_rejects_private_payloads_and_missing_exact_outcome(archive):
    client, _, initial = archive
    endpoint = BASE + "/" + initial["id"] + "/revisions"
    for field, value in (("reason", "file:///private_notes/source.txt"),
                         ("unexpected", "private")):
        data = revision()
        data[field] = value
        assert post(client, endpoint, data, "invalid-" + field).status_code == 422
    bad = revision(correction=dict(outcome_id="outcome_missing", method_version=1, reason="Explicit fixture correction"))
    assert post(client, endpoint, bad, "missing-correction").status_code == 422
    assert post(client, BASE + "/missing/revisions", revision(), "missing-method").status_code == 404


def test_exact_version_feedback_and_explicit_correction_graph(archive):
    client, path, initial = archive
    store = MethodStore(ResearchStore(path))
    outcome = store.add_outcome(initial["id"], dict(public_source_only=True, agent_name="fixture",
        method_version=1, status="failure", situation="Fixture quote mismatch", goal="Preserve quote",
        actions=["Compared quote"], observed_result="Fixture quote did not match", evidence=[]), "failed-fixture")
    store.add_opinion(initial["id"], dict(public_source_only=True, agent_name="fixture",
        method_version=1, kind="suggestion", body="Consider preserving the source ID"), "suggestion")
    before = method_graph(store.get(initial["id"]), store=store)
    assert not any(n["kind"] == "correction" for n in before["nodes"])
    endpoint = BASE + "/" + initial["id"] + "/revisions"
    wrong = revision(correction=dict(outcome_id=outcome["id"], method_version=2, reason="Wrong exact version"))
    assert post(client, endpoint, wrong, "wrong-version").status_code == 422
    valid = revision(correction=dict(outcome_id=outcome["id"], method_version=1, reason="Added source ID comparison"))
    assert post(client, endpoint, valid, "corrected-fixture").status_code == 201
    graph = client.get(BASE + "/" + initial["id"] + "/graph").json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    correction = next(n for n in nodes.values() if n["kind"] == "correction")
    assert nodes[outcome["id"]]["knowhow_role"] == "failure"
    expected = initial["id"] + ":v1"
    assert any(e["source"] == expected and e["target"] == outcome["id"] for e in graph["edges"])
    assert not any(e["source"] == initial["id"] + ":v2" and e["target"] == outcome["id"] for e in graph["edges"])
    assert {e["relation"] for e in graph["edges"] if e["source"] == correction["id"]} == {"addresses", "implemented_by"}
    assert all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"])
    assert nodes[expected]["historical"] and nodes[expected]["snapshot_available"]
    network = network_graph(store)
    assert {"situation", "goal"}.issubset({n["kind"] for n in network["nodes"]})
    assert network["scope"]["methods_shown"] == 1
    assert network["scope"]["omitted_node_kinds"] == []
    assert store.get(initial["id"])["outcomes"][0] == outcome


def test_competing_revision_compare_and_swap(archive):
    client, _, initial = archive
    endpoint = BASE + "/" + initial["id"] + "/revisions"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda key: post(client, endpoint, revision(), key), ["race-a", "race-b"]))
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_initial_methods_without_feedback_do_not_invent_results(archive):
    client, _, initial = archive
    graph = client.get(BASE + "/" + initial["id"] + "/graph").json()
    assert {n["kind"] for n in graph["nodes"]} == {"method", "situation", "goal"}
    assert not any(n.get("knowhow_role") in ("result", "failure") for n in graph["nodes"])


def test_correction_target_outside_feedback_page_is_exact_record(archive):
    client, path, initial = archive
    store = MethodStore(ResearchStore(path))
    data = dict(public_source_only=True, agent_name="fixture", method_version=1, status="unknown",
                situation="Synthetic situation", goal="Synthetic goal", actions=["Recorded fixture"],
                observed_result="Observation is unknown", evidence=[])
    for number in range(101):
        target = store.add_outcome(initial["id"], data, "page-outcome-" + str(number))
    assert target["id"] not in {item["id"] for item in store.get(initial["id"])["outcomes"]}
    correction = dict(outcome_id=target["id"], method_version=1, reason="Explicitly clarified recorded procedure")
    response = post(client, BASE + "/" + initial["id"] + "/revisions",
                    revision(correction=correction), "last-page-correction")
    assert response.status_code == 201
    graph = client.get(BASE + "/" + initial["id"] + "/graph").json()
    nodes = {item["id"]: item for item in graph["nodes"]}
    assert nodes[target["id"]]["label"] == target["observed_result"]
    assert nodes[target["id"]]["status"] == "unknown"
    assert any(edge["relation"] == "addresses" and edge["target"] == target["id"] for edge in graph["edges"])
    assert graph["truncated"]["outcomes"] is True
