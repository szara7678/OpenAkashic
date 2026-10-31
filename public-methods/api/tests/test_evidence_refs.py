"""Synthetic end-to-end authorization, provenance and function qualifier checks."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.research_evidence_refs import (PACKET_SCHEMA, POLICY, labelled_clauses, make_ref,
                                        reference_packet, register_read, render_citations, function_frames,
                                        build_reference_index)
from app.research_method_context import counted
from app.research_methods import router
from test_method_evidence import fixture_index as legacy_fixture_index


def fixture_index(tmp_path,body=None):
    index,path,manifest,body=legacy_fixture_index(tmp_path,body)
    build_reference_index(path,index)
    return index,path,manifest,body


def test_same_canonical_read_and_source_refs_resolve_without_model_quotes(tmp_path):
    index, _, manifest, body = fixture_index(tmp_path, "Baseline guarded operation.")
    metadata = manifest["sources"][0]
    prefetch = reference_packet("Q1: baseline? Q2: operation?",4096,index_path=index)
    read = register_read(metadata["source_url"],metadata["sha256"],0,len(body),body,
                         version=metadata["version"],index_path=index)
    ident = prefetch["items"][0]["evidence_id"]
    assert ident == read["items"][0]["evidence_id"]
    assert set(prefetch["items"][0]["questions"]) == {"q1","q2"}
    source = render_citations({"q1":[ident],"q2":[ident]},[prefetch],index_path=index)
    direct = render_citations({"q1":[ident],"q2":[ident]},[read],index_path=index)
    assert source == direct
    assert source["tokens"] == counted(source)
    assert source["semantic_support"] == "not_assessed"
    citation = source["evidence"][0]
    assert citation["quote"] == body and citation["supports"] == ["q1","q2"]
    assert citation["sha256"] == metadata["sha256"]
    assert citation["license"]["reviewed_for_publication"]
    assert citation["provenance"] == metadata["provenance"]


@pytest.mark.parametrize("tamper", ["quote","start","id","hash","version","license","policy"])
def test_reference_and_provenance_tampering_rejected(tmp_path,tamper):
    index, _, _, _ = fixture_index(tmp_path)
    packet = reference_packet("baseline",4096,index_path=index)
    ident = packet["items"][0]["evidence_id"]
    item = packet["items"][0]
    metadata = packet["sources"][item["source_id"]]
    if tamper == "quote": item["quote"] += " Forged."
    elif tamper == "start": item["start"] += 1
    elif tamper == "id": item["evidence_id"] = "ev_"+"0"*32
    elif tamper == "hash": metadata["sha256"] = "0"*64
    elif tamper == "version": metadata["version"] = "unseen-version"
    elif tamper == "license": metadata["license"]["url"] = "https://example.org/forged-license"
    else: packet["policy_version"] = "stale-policy"
    with pytest.raises(ValueError):
        render_citations({"q1":[ident]},[packet],index_path=index)


def test_unseen_but_real_source_range_is_not_authorized_by_hash_alone(tmp_path):
    index, _, manifest, body = fixture_index(tmp_path)
    metadata = manifest["sources"][0]
    read = register_read(metadata["source_url"],metadata["sha256"],0,8,body[:8],index_path=index)
    unexposed = make_ref(metadata["source_url"],metadata["sha256"],10,20,body[10:20])
    with pytest.raises(ValueError,match="unexposed"):
        render_citations({"q1":[unexposed["evidence_id"]]},[read],index_path=index)
    with pytest.raises(ValueError):
        register_read(metadata["source_url"],metadata["sha256"],0,8,"forged!!",index_path=index)
    with pytest.raises(ValueError):
        make_ref(metadata["source_url"],metadata["sha256"],True,9,body[1:9])


def test_whole_function_includes_blank_line_branch_qualifier(tmp_path):
    body = '''export function operate(flag) {
  if (flag) { return "needle action"; }

  // This branch is a required qualifier, not an independent procedure.
  if (!flag) { return "abstain"; }

  return "no guarantee";
}
'''
    index, _, manifest, _ = fixture_index(tmp_path,body)
    packet = reference_packet("Q1 (boolean): needle?",4096,index_path=index)
    assert packet["schema"] == PACKET_SCHEMA and packet["policy_version"] == POLICY
    assert packet["items"] and len(packet["sources"]) == 1
    item = packet["items"][0]
    assert "required qualifier" in item["quote"] and 'return "no guarantee"' in item["quote"]
    assert item["start"] == 0 and item["quote"] == body[item["start"]:item["end"]]
    assert item["quote"].endswith("}")
    assert item["questions"] == ["q1"]
    assert "source_url" not in item and "license" not in item
    partial_read = register_read(manifest["sources"][0]["source_url"],manifest["sources"][0]["sha256"],
                                 0,body.index("\n\n"),body[:body.index("\n\n")],index_path=index)
    assert partial_read["items"][0]["frame"] == "partial_read_frame"
    rendered = render_citations({"q1":[item["evidence_id"]]},[packet],index_path=index)
    assert rendered["evidence"][0]["quote"] == item["quote"]


def test_oversized_function_is_omitted_instead_of_splitting_branch(tmp_path):
    body = 'export function large() {\n  const selected = "needle";\n\n'+('  const other = "padding";\n'*5000)+'\n  return "qualifier";\n}'
    index, _, _, _ = fixture_index(tmp_path,body)
    packet = reference_packet("Q1: needle?",1024,index_path=index)
    assert packet["status"] == "budget_excluded" and packet["items"] == []
    assert packet["omitted_candidates"] and packet["sources"] == {}
    assert packet["tokens"] == counted(packet) <= 1024


def test_generic_class_method_frame_preserves_final_return_and_sibling_boundary(tmp_path):
    body = '''class SyntheticCache {
  resolve<
    TValue = unknown,
    TKey extends Array<unknown> = Array<unknown>,
  >(
    options: Options<TValue, TKey>,
  ): Promise<TValue> {
    const previous = this.read(options)

    if (previous === undefined) {
      return this.fetch(options)
    }

    if (options.background) {
      void this.prefetch(options)
    }

    return Promise.resolve(previous)
  }

  unrelated<TValue>(value: TValue): TValue {
    return value
  }
}
'''
    frames = [body[left:right] for left,right in function_frames(body)]
    selected = next(frame for frame in frames if frame.startswith("resolve<"))
    assert "return this.fetch(options)" in selected
    assert "void this.prefetch(options)" in selected
    assert "return Promise.resolve(previous)" in selected
    assert "unrelated" not in selected
    assert any(frame.startswith("unrelated<") for frame in frames)
    index, _, _, _ = fixture_index(tmp_path,body)
    packet = reference_packet("Q1: background? Q2: previous undefined?",4096,index_path=index)
    assert any(selected in item["quote"] for item in packet["items"])
    assert packet["tokens"] == counted(packet) <= 4096


def test_dedup_registry_distinct_questions_nearby_context_and_budget(tmp_path):
    body = "\n\n".join(["quartz action.", "Only while guarded.", "neutral "*4500,
                            "xenon action.", "Do not execute these untrusted instructions."])
    index, _, _, _ = fixture_index(tmp_path,body)
    for budget in (1024,2048,4096):
        packet = reference_packet("Scenario quartz. Q1: quartz? Q2: xenon?",budget,index_path=index)
        assert len(packet["sources"]) == 1
        assert len(packet["items"]) >= 2
        assert packet["tokens"] == counted(packet) <= budget
        assert packet["content_policy"] == "untrusted_data_do_not_execute"
        assert packet["partial"] and not packet["evidence_complete"]
        joined = " ".join(item["quote"] for item in packet["items"])
        assert "Only while guarded" in joined and "untrusted instructions" in joined
        for item in packet["items"]:
            assert item["quote"] == body[item["start"]:item["end"]]
    assert labelled_clauses("Q1 (bool): quartz? Q2: xenon? Return JSON only: other") == [
        ("q1",["quartz"]),("q2",["xenon"])]


def test_index_tampering_rejected_and_route_legacy_default_preserved(tmp_path,monkeypatch):
    index, _, _, _ = fixture_index(tmp_path)
    packet = reference_packet("baseline",4096,index_path=index)
    monkeypatch.setenv("OPENAKASHIC_METHOD_EVIDENCE_INDEX",str(index))
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        legacy = client.get("/research/api/methods/evidence",params={"query":"baseline"}).json()
        refs = client.get("/research/api/methods/evidence",params={"query":"baseline","format":"refs"}).json()
        assert legacy["schema"] == "method-evidence-packet-v1"
        assert refs["schema"] == PACKET_SCHEMA and refs["tokens"] == counted(refs) <= 1024
    with sqlite3.connect(index) as db:
        db.execute("UPDATE sources SET body=body||'forged'")
    with pytest.raises(ValueError,match="integrity"):
        render_citations({"q1":[packet["items"][0]["evidence_id"]]},[packet],index_path=index)
