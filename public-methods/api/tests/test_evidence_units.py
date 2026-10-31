"""Generic approved-metadata anchoring and identifier retrieval, no real task fixtures."""
import hashlib
import json
import sqlite3

import pytest

from app.research_evidence_refs import (ApprovedIndex, anchored_source_ids, build_reference_index,
                                        inspect_candidate_rank, reference_packet, register_read, render_citations,
                                        public_projection)
from app.research_evidence_units import anchored_sources, search_terms, structural_frames
from app.research_method_context import counted
from test_method_evidence import fixture_index


def product_index(tmp_path):
    _,path,manifest,_=fixture_index(tmp_path)
    source=manifest['sources'][0]
    sources=[]
    bodies={
        ('aurora','1.2.3'):"## Terminal Mode\n\nMulti-line editing is enabled by default.\n\nHistory includes multi-line entries.",
        ('aurora','2.0.0'):"## Terminal Mode\n\nSingle-line editing is the new default.",
        ('orbit','1.2.3'):"## Terminal Mode\n\nMulti-line editing and history.\n\nDo not confuse this unrelated product."}
    for n,((product,version),body) in enumerate(bodies.items()):
        local=tmp_path/f'product-{n}.txt';local.write_bytes(body.encode())
        sources.append({**source,'path':str(local),'source_url':f'https://example.org/{product}/{version}/manual.md',
                        'version':f'{product.title()} {version} approved snapshot',
                        'sha256':hashlib.sha256(local.read_bytes()).hexdigest()})
    path.write_text(json.dumps({**manifest,'sources':sources}))
    index=tmp_path/'refs.sqlite3';build_reference_index(path,index)
    return index,path,sources,bodies


def test_unique_explicit_product_and_version_anchor_and_ambiguity(tmp_path):
    index,_,_,_=product_index(tmp_path)
    packet=reference_packet('Aurora 1.2.3 Q1: multi-line editing? Q2: history?',4096,index_path=index)
    assert packet['anchoring']['status']=='product_and_version'
    assert packet['anchoring']['product']=='aurora'
    assert packet['sources']
    assert all('/aurora/1.2.3/' in s['source_url'] for s in packet['sources'].values())
    assert counted(packet)==packet['tokens']<=4096
    with ApprovedIndex(index) as approved:
        allowed,scope=anchored_source_ids('Compare Aurora and Orbit modes',approved)
        assert allowed is None and scope['status']=='multiple_explicit_products'
        allowed,scope=anchored_source_ids('Aurora 9.9.9 mode',approved)
        assert len(allowed)==2 and scope['status']=='product_requested_version_not_pinned'
        allowed,scope=anchored_source_ids('No product given, just terminal history',approved)
        assert allowed is None and scope['status']=='unanchored'
    # The same helper accepts a direct browser's manifest IDs, not just SQLite IDs.
    allowed,_=anchored_sources([('manifest-a',{'source_url':'https://example.org/aurora/manual',
                                               'version':'Aurora 1.2.3'})], 'Aurora history')
    assert allowed==['manifest-a']


def test_uncorroborated_version_prefix_does_not_invent_product_scope():
    allowed,scope=anchored_sources([(1,{'source_url':'https://example.org/manual',
                                       'version':'Version 1.2.3'})], 'Version 1.2.3 editing')
    assert allowed is None and scope['product'] is None


def test_camel_snake_normalized_search_keeps_original_quotes_hashes(tmp_path):
    _,path,manifest,_=fixture_index(tmp_path)
    body='''export function partialMatchKey(value, prefix) {
  if (prefix) { return value.match(prefix); }

  return false;
}

export function stable_hash_key(value) {
  return sorted(value);
}
'''
    local=tmp_path/'identifiers.ts';local.write_bytes(body.encode())
    manifest['sources'][0].update(path=str(local),source_url='https://example.org/engine/utils.ts',
                                  version='Engine 1.2.3',sha256=hashlib.sha256(local.read_bytes()).hexdigest())
    path.write_text(json.dumps(manifest));index=tmp_path/'refs.sqlite3';build_reference_index(path,index)
    assert {'partialmatchkey','partial','match','key'}<=set(search_terms('partialMatchKey'))
    assert {'stable','hash','key'}<=set(search_terms('stable_hash_key'))
    packet=reference_packet('Engine 1.2.3 Q1: partial matching key? Q2: stable hash key?',4096,index_path=index)
    combined='\n'.join(i['quote'] for i in packet['items'])
    assert 'export function partialMatchKey' in combined and 'return false;' in combined
    assert 'export function stable_hash_key' in combined
    for item in packet['items']:
        assert item['quote']==body[item['start']:item['end']]
        assert packet['sources'][item['source_id']]['sha256']==hashlib.sha256(body.encode()).hexdigest()
    with sqlite3.connect(index) as db:
        normalized=' '.join(r[0] for r in db.execute('SELECT text FROM reference_units'))
        assert {'partial','match','key'}<=set(normalized.split()) and 'partialMatchKey' not in normalized
    trace=inspect_candidate_rank('Engine Q1: partial matching key?',index_path=index)
    assert trace['selected'] and all('rrf' in row for c in trace['clauses'] for row in c['ranked_units'])


def test_markdown_prose_does_not_become_a_false_code_function(tmp_path):
    body='''## Storage

A notation such as name => {value} is prose here. It is not a code function.

Compression is unrelated to terminal editing.

## Terminal Mode

Multi-line editing is the default.

Unclosed quotes are highlighted as errors.
'''
    index,path,manifest,_=fixture_index(tmp_path,body)
    manifest['sources'][0].update(source_url='https://example.org/aurora/manual.md',version='Aurora 1.2.3')
    path.write_text(json.dumps(manifest));build_reference_index(path,index)
    assert structural_frames(manifest['sources'][0],body)==[]
    packet=reference_packet('Aurora Q1: multi-line editing? Q2: unclosed quotes?',4096,index_path=index)
    editing=next(i for i in packet['items'] if 'Multi-line editing is the default.' in i['quote'])
    assert 'Compression' not in editing['quote'] and 'Storage' not in editing['quote']
    assert 'Unclosed quotes' in editing['quote']


def test_explicit_character_and_line_read_actions_and_tamper_rejection(tmp_path):
    body='한글 제목\r\n\r\nneedle operation.\r\n\r\nOnly with the guard.\r\n'
    index,path,manifest,_=fixture_index(tmp_path,body)
    build_reference_index(path,index)
    start=body.index('needle');end=body.index('\r\n',start)
    source=manifest['sources'][0]
    read=register_read(source['source_url'],source['sha256'],start,end,body[start:end],index_path=index)
    item=read['items'][0];metadata=read['sources'][item['source_id']]
    assert item['start']==start and item['start_line']==3
    assert item['start']!=item['read_action']['start']
    assert item['read_action']=={'id':item['source_id'],'start':3,'lines':1,'unit':'one_based_lines'}
    assert item['offset_unit']=='unicode_codepoints'
    assert metadata['read_url']==source['source_url'] and metadata['total_lines']==5
    render_citations({'q1':[item['evidence_id']]},[read],index_path=index)
    item['read_action']['start']=start
    with pytest.raises(ValueError):
        render_citations({'q1':[item['evidence_id']]},[read],index_path=index)


def test_new_index_preferred_environment_legacy_read_validation_and_upgrade(tmp_path,monkeypatch):
    legacy,path,manifest,body=fixture_index(tmp_path)
    assert reference_packet('baseline',index_path=legacy)['status']=='index_upgrade_required'
    source=manifest['sources'][0]
    # Existing approved original indexes still validate direct reads/rendering.
    packet=register_read(source['source_url'],source['sha256'],0,len(body),body,index_path=legacy)
    assert render_citations({'q1':[packet['items'][0]['evidence_id']]},[packet],index_path=legacy)['evidence']
    new=tmp_path/'new.sqlite3';build_reference_index(path,new)
    monkeypatch.setenv('OPENAKASHIC_METHOD_REFS_INDEX',str(new))
    monkeypatch.setenv('OPENAKASHIC_METHOD_EVIDENCE_INDEX',str(tmp_path/'missing-legacy'))
    assert reference_packet('baseline')['status']=='ready'


def test_reference_builder_failure_does_not_replace_installed_index(tmp_path):
    index,path,manifest,_=fixture_index(tmp_path)
    build_reference_index(path,index);before=index.read_bytes()
    manifest['sources'][0]['sha256']='0'*64;path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):build_reference_index(path,index)
    assert index.read_bytes()==before


def test_public_api_redacts_local_license_metadata_after_packing(tmp_path,monkeypatch):
    import copy
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.research_methods import router
    index,path,manifest,body=fixture_index(tmp_path)
    local_pointer='/home/operator/nonpublic-license-copy.txt'
    manifest['sources'][0]['license'].update(preserved_file=local_pointer,
        sha256='a'*64,notice='Copyright Synthetic Authors',unknown_operator_field='private metadata')
    path.write_text(json.dumps(manifest));build_reference_index(path,index)
    before=index.read_bytes()
    # Capture the original packing boundary; projection must not add candidates
    # using space freed by redaction and must never mutate the host-held input.
    import app.research_evidence_refs as module
    real_projection=module.public_projection
    with monkeypatch.context() as context:
        context.setattr(module,'public_projection',lambda packet:copy.deepcopy(packet))
        original=module.reference_packet('baseline',1024,index_path=index)
    untouched=copy.deepcopy(original)
    expected=real_projection(original)
    assert original==untouched
    assert [i['evidence_id'] for i in original['items']]==[i['evidence_id'] for i in expected['items']]
    monkeypatch.setenv('OPENAKASHIC_METHOD_REFS_INDEX',str(index))
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        response=client.get('/research/api/methods/evidence',params={'query':'baseline','format':'refs','max_tokens':1024})
    assert response.status_code==200 and response.json()==expected
    assert local_pointer not in response.text and 'preserved_file' not in response.text
    assert 'unknown_operator_field' not in response.text
    license_=next(iter(response.json()['sources'].values()))['license']
    assert license_['sha256']=='a'*64 and license_['notice']=='Copyright Synthetic Authors'
    assert response.json()['tokens']==counted(response.json())<=1024
    assert index.read_bytes()==before
    selected=expected['items'][0]['evidence_id']
    # Both original frozen and already-public host exposures remain valid.
    rendered=render_citations({'q1':[selected]},[original,expected],index_path=index)
    assert rendered['evidence'][0]['quote'] in body
    assert 'preserved_file' not in json.dumps(rendered)


def test_public_attribution_fields_cannot_carry_a_local_path(tmp_path):
    index,path,manifest,_=fixture_index(tmp_path)
    manifest['sources'][0]['license']['attribution']='/home/operator/private-attribution.txt'
    path.write_text(json.dumps(manifest));build_reference_index(path,index)
    with pytest.raises(ValueError,match='public text'):
        reference_packet('baseline',index_path=index)
