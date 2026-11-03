"""Offline synthetic executor/guard tests, not evidence of generated-page quality."""
import copy
import json
from pathlib import Path
import pytest

from src.utils.bounded_plan_correction import MODEL, correction_request, correction_invariants
from scripts.run_bounded_plan_correction import correction_transport, run_correction


def fixture():
    ev = [{'source':'asr', 'quote':'first left of second'}]
    size = dict(basis_px='auto', grow=1, shrink=1, cross='stretch')
    objects = [dict(id=name, type='text', text='preserve '+name, actions=['action '+name],
                    opaque={'do_not_drop':[1,2]}, parent='region_root', order=i,
                    relation_status='proposed', sizing=copy.deepcopy(size), evidence=copy.deepcopy(ev))
               for i, name in enumerate(('item_a', 'item_b'))]
    region = dict(id='region_root', kind='semantic_region', parent=None,
                  evidence=[{'source':'system_root'}],
                  layout=dict(direction='column',gap_px=0,padding_px=0,overflow='visible'))
    relation = dict(id='rel_synthetic',kind='left_of',subject='item_a',object='item_b',
                    status='proposed',evidence=copy.deepcopy(ev))
    old = dict(page_meta={'viewport':{'width':1000,'height':700}}, elements=objects,
               region_contract={'version':'region-tree-v2','root_id':'region_root','regions':[region]},
               relation_plan={'version':'spatial-relations-v1','relations':[relation]})
    vision = {'elements':[{k:copy.deepcopy(v) for k,v in e.items() if k in {'id','type','text','actions'}} for e in objects]}
    new = copy.deepcopy(old)
    new['region_contract']['regions'][0]['layout']['direction']='row'
    envelope = {'corrected_plan':new, 'relation_changes':[
        dict(id=relation['id'],operation='keep',reason='same proposition, organizational tree corrected',evidence=[])]}
    request = dict(model=MODEL,messages=[dict(role='system',content='Synthetic original contract'),
                                      dict(role='user',content='first left of second')])
    return old, vision, 'first left of second', envelope, request


def packet(content, finish='stop'):
    return {'ok':True,'response':{'choices':[{'finish_reason':finish,'message':{'content':content}}],
                                'usage':{'total_tokens':7}}}


def test_actual_original_inputs_and_answer_are_exact_not_review_targets():
    old,v,i,env,req=fixture();before=copy.deepcopy((old,v,req))
    answer=json.dumps(old);r,feedback=correction_request(req,answer,v,i)
    payload=json.loads(r['messages'][1]['content'])
    assert payload['original_messages']==req['messages']
    assert payload['original_answer']==answer and payload['frozen_vision']==v and payload['frozen_intent']==i
    assert payload['machine_diagnostics']==feedback
    assert (old,v,req)==before
    assert r['model']==MODEL and r['max_tokens']==8192 and r['timeout']==600 and r['temperature']==.3


def test_valid_synthetic_one_correction_then_coder_and_once_slots(tmp_path):
    old,v,i,env,req=fixture();requests=[]
    def dispatch(request,deadline):
        requests.append(copy.deepcopy(request));assert deadline==600
        return packet(json.dumps(env) if len(requests)==1 else '<html><body>synthetic fixture</body></html>')
    transport=correction_transport(tmp_path/'transport','synthetic_once',dispatch=dispatch)
    result=run_correction(req,json.dumps(old),v,i,tmp_path/'run',transport)
    assert result['new_requests_dispatched']==2 and result['coder_dispatched']
    assert result['once_correction_mechanical_pass'] and not result['html_exists']
    assert result['source_coverage']=='NOT_EVALUATED' and result['semantic_acceptance']=='UNKNOWN'
    with pytest.raises(ValueError,match='ONCE_ONLY'):transport('candidate','coder',requests[-1])
    with pytest.raises(ValueError,match='ONCE_ONLY'):transport('control','architect',requests[0])
    with pytest.raises(FileExistsError):correction_transport(tmp_path/'transport','other',dispatch=dispatch)
    assert len(requests)==2


@pytest.mark.parametrize('failure',['timeout','truncated','json','production','invariant','ledger','empty','unknown'])
def test_failed_correction_never_dispatches_coder_or_retry(tmp_path,failure):
    old,v,i,env,req=fixture();calls=[]
    if failure=='production':env['corrected_plan']['region_contract']['regions'][0]['layout']['direction']='column'
    if failure=='invariant':env['corrected_plan']['elements'][0]['actions']=[]
    if failure=='ledger':
        env['corrected_plan']['relation_plan']['relations'][0]['evidence'].append(
            {'source':'model_inference','reason':'actual change requires a ledger row'})
        env['relation_changes']=[]
    if failure=='empty':env['corrected_plan']['relation_plan']['relations']=[]
    if failure=='unknown':env['corrected_plan']['relation_plan']['relations'][0]['status']='unknown'
    def dispatch(request,deadline):
        calls.append(request)
        if failure=='timeout':raise TimeoutError('SYNTHETIC_NO_NETWORK')
        return packet('not json' if failure=='json' else json.dumps(env), 'length' if failure=='truncated' else 'stop')
    t=correction_transport(tmp_path/'transport','failed_once',dispatch=dispatch)
    result=run_correction(req,json.dumps(old),v,i,tmp_path/'run',t)
    assert result['status']=='STOPPED_NO_RETRY' and not result['coder_dispatched'] and len(calls)==1
    assert not (tmp_path/'run/pre_coder_gate.json').exists()
    with pytest.raises(ValueError):t('candidate','architect',calls[0])
    with pytest.raises(ValueError):t('candidate','coder',dict(calls[0],temperature=.2))
    assert len(calls)==1


@pytest.mark.parametrize('mutation',[
    lambda p:p['elements'].pop(),
    lambda p:p['elements'].reverse(),
    lambda p:p['elements'][0].update(type='button'),
    lambda p:p['elements'][0].update(text='changed'),
    lambda p:p['elements'][0]['opaque'].update(extra='hidden'),
    lambda p:p['page_meta']['viewport'].update(width=406),
    lambda p:p.update(unapproved_business_extra=True),
    lambda p:[e.update(relation_status='unknown') for e in p['elements']],
])
def test_object_and_canvas_invariants_reject_changes(mutation):
    old,v,i,env,req=fixture();mutation(env['corrected_plan'])
    with pytest.raises(ValueError):correction_invariants(old,env['corrected_plan'],env['relation_changes'],v,i)


def test_drop_unsupported_proposition_allowed_with_source_not_coverage():
    old,v,i,env,req=fixture()
    unsupported=copy.deepcopy(old['relation_plan']['relations'][0]);unsupported.update(id='rel_bad',kind='above')
    old['relation_plan']['relations'].append(unsupported)
    env['relation_changes'].append(dict(id='rel_bad',operation='drop',reason='retracted competing synthetic claim',
                                      evidence=[{'source':'asr','quote':i}]))
    result=correction_invariants(old,env['corrected_plan'],env['relation_changes'],v,i)
    row=next(r for r in result['relation_changes'] if r['id']=='rel_bad')
    assert row['before']==unsupported and row['after'] is None and row['removed_or_unknown_not_coverage']
    assert row['semantic_support']=='UNKNOWN' and result['source_coverage']=='NOT_EVALUATED'


@pytest.mark.parametrize('issue',['missing','false_operation','bad_quote','all_unknown','empty'])
def test_changes_cannot_hide_loss_or_fabricate_evidence(issue):
    old,v,i,env,req=fixture();new=env['corrected_plan'];changes=env['relation_changes']
    if issue in {'missing','false_operation'}:
        new['relation_plan']['relations'][0]['evidence'].append({'source':'model_inference','reason':'changed annotation'})
    if issue=='missing':changes.clear()
    if issue=='false_operation':changes[0]['operation']='drop'
    if issue=='bad_quote':
        new['relation_plan']['relations'][0]['evidence']=[{'source':'asr','quote':'absent'}]
        changes[0].update(operation='modify',evidence=[{'source':'asr','quote':'absent'}])
    if issue=='all_unknown':new['relation_plan']['relations'][0]['status']='unknown'
    if issue=='empty':new['relation_plan']['relations'].clear()
    with pytest.raises(ValueError):correction_invariants(old,new,changes,v,i)


def test_coder_requires_explicit_gate_and_failed_coder_is_consumed(tmp_path):
    old,v,i,env,req=fixture();calls=[]
    def dispatch(request,deadline):
        calls.append(request)
        if len(calls)==2:raise TimeoutError('SYNTHETIC_CODER_TIMEOUT')
        return packet(json.dumps(env))
    t=correction_transport(tmp_path/'transport','coder_failure',dispatch=dispatch)
    with pytest.raises(ValueError):t.permit_coder({'status':'INVALID'})
    result=run_correction(req,json.dumps(old),v,i,tmp_path/'run',t)
    assert result['new_requests_dispatched']==2 and result['status']=='STOPPED_NO_RETRY'
    with pytest.raises(ValueError):t('candidate','coder',calls[-1])
    assert len(calls)==2


def test_no_empty_gate_uses_assert_in_executable_modules():
    root=Path(__file__).resolve().parents[1]
    for name in ('src/utils/bounded_plan_correction.py','scripts/run_bounded_plan_correction.py'):
        assert 'assert ' not in (root/name).read_text(encoding='utf-8')


@pytest.mark.parametrize('notes',[
    None, [],
    [{'id':'rel_synthetic','operation':'keep','reason':'optional note','evidence':[{'source':'asr','quote':'first left of second'}]}],
    [{'id':'rel_synthetic','operation':'keep','reason':'invalid note retained','evidence':[{'source':'asr','quote':'not in source'}]}],
    [{'id':'rel_synthetic','operation':'drop','reason':'false annotation cannot delete a claim','evidence':[]}],
])
def test_code_derives_keep_and_notes_never_become_effective_sources(notes):
    old,v,i,env,req=fixture();new=env['corrected_plan']
    supplied=[] if notes is None else copy.deepcopy(notes)
    result=correction_invariants(old,new,supplied,v,i)
    row=result['relation_changes'][0]
    assert row['operation']=='keep' and row['before']==row['after'] and row['evidence']==[]
    assert row['audit_annotation_unvalidated']==(supplied[0] if supplied else None)
    assert row['annotation_evidence_status']=='NOT_USED_AS_EFFECTIVE_SOURCE'
    assert result['source_coverage']=='NOT_EVALUATED'
    if supplied and supplied[0]['evidence'] and supplied[0]['evidence'][0]['quote']=='not in source':
        assert row['annotation_warnings'][0]['code']=='UNKNOWN_QUOTE_ABSENT'
    if supplied and supplied[0]['operation']=='drop':
        assert row['annotation_warnings'][0]['code']=='DECLARED_OPERATION_DISAGREES_WITH_DERIVED_KEEP'


def test_real_stopped_answer_compatibility_does_not_override_original_production_gate(monkeypatch):
    import hashlib,os
    from unittest.mock import patch
    from src.utils.bounded_plan_correction import ENVIRONMENT
    from src.agents.ui_architect import finalize_ui_state
    location=os.environ.get('BOUNDED_CORRECTION_STOPPED_FIXTURE')
    if not location:pytest.skip('External real stopped-answer fixture not configured')
    p=Path(location)
    paths=[p/'inputs/original_answer.txt',p/'results/architect_response.json']
    hashes=[hashlib.sha256(x.read_bytes()).hexdigest() for x in paths]
    old=json.loads(paths[0].read_text(encoding='utf-8'))
    envelope=json.loads(json.loads(paths[1].read_text(encoding='utf-8'))['content'])
    vision=json.loads((p/'inputs/vision.json').read_text(encoding='utf-8'))
    intent=(p/'inputs/intent.txt').read_text(encoding='utf-8')
    result=correction_invariants(old,envelope['corrected_plan'],envelope['relation_changes'],vision,intent)
    assert any(x.get('annotation_warnings') for x in result['relation_changes'])
    assert result['source_coverage']=='NOT_EVALUATED'
    # POST-HOC OFFLINE CHECK ONLY: original raw plan is not repaired or reclassified.
    with patch.dict(os.environ,ENVIRONMENT),pytest.raises(ValueError,match='UNKNOWN_QUOTE_ABSENT'):
        finalize_ui_state(copy.deepcopy(envelope['corrected_plan']),intent,copy.deepcopy(vision),'baseline')
    assert hashes==[hashlib.sha256(x.read_bytes()).hexdigest() for x in paths]
