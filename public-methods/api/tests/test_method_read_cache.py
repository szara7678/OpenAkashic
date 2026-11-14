"""Complete-method read suppression is exact, explicit and session scoped."""
from copy import deepcopy
import importlib.util
import json
from test_research_methods import archive
from pathlib import Path

spec = importlib.util.spec_from_file_location("read_cache", Path(__file__).parents[1] / "scripts" / "method_read_cache.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def method():
    return {"id": "method_a", "version": 2, "steps": ["Read full procedure"],
            "sources": [{"url": "https://example.com", "quote": "Evidence"}]}


def bundle(value):
    return {"schema": "method-bundle-v1", "tokens": 100, "items": [
        {"id": value["id"], "version": value["version"], "complete": True,
         "needs_fetch": False, "source_hash": module.fingerprint(value), "method": value}]}


def test_full_bundle_counts_as_read_and_exact_get_has_local_source(tmp_path):
    cache = module.MethodReadCache(tmp_path, "public-endpoint")
    value = method()
    assert cache.present("bundle", bundle(value))["items"][0]["method"] == value
    receipt = cache.present("fetch", value)
    assert receipt["already_read"] and receipt["current_response_revalidated"]
    assert receipt["source_hash"] == module.fingerprint(value)
    assert json.loads(Path(receipt["artifact"]).read_text()) == value
    repeated = cache.present("bundle", bundle(value))
    assert "method" not in repeated["items"][0]
    assert repeated["items"][0]["method_read_receipt"]["already_read"]
    assert "tokens" not in repeated and repeated["server_response_tokens"] == 100


def test_new_version_or_same_version_changed_evidence_never_suppressed(tmp_path):
    cache = module.MethodReadCache(tmp_path, "public-endpoint")
    value = method()
    cache.present("fetch", value)
    for changed in (dict(value, version=3), dict(value, sources=[{"quote": "New correction"}])):
        assert cache.present("fetch", changed) == changed
    assert cache.present("fetch", value, refetch=True) == value
    assert cache.present("bundle", bundle(value), refetch=True)["items"][0]["method"] == value


def test_reference_search_context_and_malformed_bundle_do_not_register_read(tmp_path):
    cache = module.MethodReadCache(tmp_path, "public-endpoint")
    value = method()
    for command in ("search", "context"):
        assert cache.present(command, bundle(value)) == bundle(value)
    incomplete = bundle(value)
    incomplete["items"][0]["complete"] = False
    cache.present("bundle", incomplete)
    mismatch = bundle(value)
    mismatch["items"][0]["source_hash"] = "bad"
    cache.present("bundle", mismatch)
    assert cache.present("fetch", value) == value


def test_persists_only_in_same_session_and_endpoint_and_preserves_corruption(tmp_path):
    value = method()
    cache = module.MethodReadCache(tmp_path / "session1", "endpoint-a")
    assert cache.present("fetch", value) == value
    assert module.MethodReadCache(tmp_path / "session1", "endpoint-a").present("fetch", value)["already_read"]
    assert module.MethodReadCache(tmp_path / "session1", "endpoint-b").present("fetch", value) == value
    assert module.MethodReadCache(tmp_path / "session2", "endpoint-a").present("fetch", value) == value
    receipt = cache.present("fetch", value)
    Path(receipt["artifact"]).write_text("broken")
    assert cache.present("fetch", value) == value
    assert Path(receipt["artifact"]).read_text() == "broken"
    assert cache.present("fetch", value) == value


def test_planted_symlink_never_followed_or_overwritten(tmp_path):
    value = method()
    cache = module.MethodReadCache(tmp_path / "cache", "endpoint")
    cache.present("fetch", value)
    artifact = Path(cache.present("fetch", value)["artifact"])
    artifact.unlink()
    victim = tmp_path / "unrelated.json"
    victim.write_text("do not alter")
    artifact.symlink_to(victim)
    assert cache.present("fetch", value) == value
    assert victim.read_text() == "do not alter"
    assert artifact.is_symlink()


def test_live_feedback_is_separate_and_unknown_fields_are_not_ignored(tmp_path):
    cache = module.MethodReadCache(tmp_path, "endpoint")
    value = method()
    cache.present("bundle", bundle(value))
    full = dict(value, outcomes=[{"id": "outcome_a"}], opinions=[], feedback_counts={"outcomes": 1})
    receipt = cache.present("fetch", full)
    assert receipt["already_read"]
    assert receipt["source_hash"] == module.fingerprint(value)
    assert receipt["fresh_feedback"]["outcomes"] == full["outcomes"]
    changed = deepcopy(full)
    changed["opinions"].append({"id": "opinion_new", "body": "New limitation"})
    assert cache.present("fetch", changed)["fresh_feedback"]["opinions"] == changed["opinions"]
    unknown = dict(full, future_source_evidence="must display")
    assert cache.present("fetch", unknown) == unknown


def test_real_bundle_get_and_new_feedback_wire_contract(archive, tmp_path):
    from test_research_methods import BASE, create, post, outcome_payload, opinion_payload
    client, _ = archive
    stored = create(client)
    query = {"situation": "network blocked environment", "goal": "preserve evidence citations",
             "mode": "lexical", "max_tokens": 4096}
    packet = client.get(BASE + "/bundle", params=query).json()
    assert packet["items"][0]["complete"]
    cache = module.MethodReadCache(tmp_path / "bundle-first", "endpoint")
    cache.present("bundle", packet)
    full = client.get(BASE + "/" + stored["id"]).json()
    receipt = cache.present("fetch", full)
    assert receipt["already_read"]
    assert receipt["source_hash"] == packet["items"][0]["source_hash"]
    assert len(module.canonical(receipt)) < len(module.canonical(full))
    assert post(client, "/"+stored["id"]+"/outcomes", outcome_payload(), "outcome-new").status_code == 201
    assert post(client, "/"+stored["id"]+"/opinions", opinion_payload(), "opinion-new").status_code == 201
    updated = client.get(BASE + "/" + stored["id"]).json()
    assert updated["version"] == full["version"]
    receipt2 = cache.present("fetch", updated)
    assert receipt2["already_read"]
    assert receipt2["fresh_feedback"] == {key: updated[key] for key in ("outcomes", "opinions", "feedback_counts")}
    reverse = module.MethodReadCache(tmp_path / "get-first", "endpoint")
    assert reverse.present("fetch", updated) == updated
    assert reverse.present("bundle", packet)["items"][0]["method_read_receipt"]["already_read"]
