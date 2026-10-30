"""Generic engineering counterexamples, not case scoring or generated pages."""
import copy
import json
from types import SimpleNamespace

import pytest

from test_region_tree_contract import sample
from src.utils.region_tree_contract import compile_region_tree, locate_quote


def propose(state, field, value, quote='can edit'):
    item=state['elements'][0]
    item[field]=value
    item.setdefault('change_sources',{})[field]={'quote':quote,'reason':'synthetic proposal; interpretation still requires independent review'}


def add_region(state):
    region=copy.deepcopy(state['region_contract']['regions'][0])
    region.update(id='region_group',parent='region_page',order=0,relation_status='proposed',
                  evidence=[{'source':'model_inference','reason':'generic grouping proposal'}],
                  sizing={'basis_px':'auto','grow':1,'shrink':1})
    state['region_contract']['regions'].append(region)
    for item in state['elements']:item['parent']='region_group'
    return region


@pytest.mark.parametrize('text,quote,status,count',[
    ('abc edit def','edit','UNIQUE_EXACT_QUOTE',1),
    ('edit then edit','edit','UNKNOWN_QUOTE_AMBIGUOUS',2),
    ('aaaa','aa','UNKNOWN_QUOTE_AMBIGUOUS',3),
    ('other','edit','UNKNOWN_QUOTE_ABSENT',0),
    ('other','','UNKNOWN_INVALID_QUOTE',0),
    ('other',None,'UNKNOWN_INVALID_QUOTE',0),
])
def test_quote_unique_exact_overlapping_and_unknown(text,quote,status,count):
    result=locate_quote(quote,text)
    assert result['status']==status and result['occurrences']==count
    assert result['semantic_support']=='UNKNOWN'
    assert ('start' in result)==(status=='UNIQUE_EXACT_QUOTE')


def test_unicode_offsets_computed_not_model_supplied():
    s,v=sample();propose(s,'type','input','可以编辑')
    intent='前言🙂可以编辑，然后保留。';before=copy.deepcopy(s);original=copy.deepcopy(v)
    out=compile_region_tree(s,v,intent)
    row=out['observation_provenance']['changes'][0]
    span=row['source_location']
    assert span['start']==3 and intent[span['start']:span['end']]=='可以编辑'
    assert row['before']=={'present':True,'value':'text'}
    assert row['after']=={'present':True,'value':'input'}
    assert s==before and v==original and out['elements']==before['elements']
    assert out['observation_provenance']['original_vision']==original


@pytest.mark.parametrize('quote,intent',[('not found','can edit'),('edit','edit and edit'),('edited','can edit'),('','can edit')])
def test_unknown_quote_stops_changed_plan(quote,intent):
    s,v=sample();propose(s,'type','input',quote)
    with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,intent)


def test_quote_presence_not_semantic_support_or_human_acceptance():
    s,v=sample();propose(s,'actions',[{'type':'unsupported_business_claim'}],'unrelated statement')
    out=compile_region_tree(s,v,'unrelated statement')
    row=out['observation_provenance']['changes'][0]
    assert row['status']=='SOURCED_PLANNING_PROPOSAL'
    assert row['semantic_support']=='UNKNOWN'
    assert out['observation_provenance']['semantic_confirmation']=='NOT_CONFIRMED_BY_REFERENCE_EXISTENCE'


def test_missing_to_empty_actions_keeps_missing_observation():
    s,v=sample();s['elements'][0]['actions']=[]
    out=compile_region_tree(s,v,'')
    assert 'actions' not in v['elements'][0]
    assert 'actions' not in out['observation_provenance']['original_vision']['elements'][0]
    row=out['observation_provenance']['changes'][0]
    assert row['status']=='NO_ADDITIONAL_ACTION_PLAN'
    assert row['before']['present'] is False and row['after']=={'present':True,'value':[]}


@pytest.mark.parametrize('field,old,new',[
    ('actions',[{'type':'click'}],[]),('actions',[{'type':'click'}],None),
    ('action','click',''),('rpa_action','display_a',''),('text','same',''),('type','text',None),
])
def test_observed_nonempty_cannot_be_cleared_even_with_unique_quote(field,old,new):
    s,v=sample();v['elements'][0][field]=old;propose(s,field,new)
    with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,'can edit')


@pytest.mark.parametrize('field,value',[('actions',[{'type':'click'}]),('action','click'),('rpa_action','new'),('type','input'),('text','new')])
def test_unsourced_substantive_expansion_rejected(field,value):
    s,v=sample();s['elements'][0][field]=value
    with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,'can edit')


def test_single_plan_explicit_nested_region_and_business_ancestry():
    s,v=sample();add_region(s)
    out=compile_region_tree(s,v,'')
    assert out['region_layout']['children']=={'region_page':['region_group'],'region_group':['left','right']}
    assert out['region_layout']['parent_by_id']['left']=='region_group'
    assert out['elements']==s['elements'] and 'objects' not in out['region_contract']


@pytest.mark.parametrize('mutate',[
    lambda s:s['region_contract'].update(objects=[]),
    lambda s:s['region_contract'].update(version='region-tree-v1'),
    lambda s:s['region_contract']['regions'][0].update(objects=[]),
    lambda s:s['region_contract']['regions'][0].update(children=[]),
    lambda s:s['region_contract']['regions'][0].update(regions=[]),
    lambda s:s['region_contract']['regions'][0].update(members=[]),
    lambda s:s['elements'][0].update(children_ids=['right']),
    lambda s:s['elements'][0].update(parent_id='region_page'),
    lambda s:s['elements'][0].pop('parent'),
    lambda s:s['region_contract']['regions'][0].pop('parent'),
    lambda s:s['elements'][0].pop('order'),
    lambda s:s['elements'][0].pop('sizing'),
    lambda s:s['elements'][0].pop('relation_status'),
    lambda s:s['elements'][0].update(parent='left'),
    lambda s:s['elements'][0].update(evidence=[{'source':'asr','quote':'can edit','start':0,'end':8}]),
    lambda s:s.update(observation_change_evidence=[]),
])
def test_missing_nested_or_duplicate_contract_rejected_not_guessed(mutate):
    s,v=sample();mutate(s)
    with pytest.raises(ValueError):compile_region_tree(s,v,'can edit')


def test_unknown_membership_cannot_be_hidden_inside_subregion():
    s,v=sample();add_region(s);s['elements'][0]['relation_status']='unknown'
    with pytest.raises(ValueError,match='UNKNOWN_MEMBERSHIP_MUST_STAY_AT_ROOT'):compile_region_tree(s,v,'')


def test_ten_same_labels_remain_independent_not_deduplicated():
    s,v=sample();template=copy.deepcopy(s['elements'][0]);visual=copy.deepcopy(v['elements'][0])
    s['elements']=[];v['elements']=[]
    for i in range(10):
        s['elements'].append(dict(copy.deepcopy(template),id=f'generic_{i}',order=i))
        v['elements'].append(dict(copy.deepcopy(visual),id=f'generic_{i}'))
    out=compile_region_tree(s,v,'')
    assert len(out['elements'])==10 and len(out['region_layout']['children']['region_page'])==10
    s['elements'].pop()
    with pytest.raises(ValueError,match='SOURCE_OBJECT_LOST'):compile_region_tree(s,v,'')


@pytest.mark.parametrize('intent',['can edit','edit and edit'])
def test_spoken_object_requires_unique_quote_and_explicit_relation(intent):
    s,v=sample();new=copy.deepcopy(s['elements'][0])
    new.update(id='u_generic',origin='spoken',order=2,source_evidence=[{'source':'asr','quote':'edit'}])
    s['elements'].append(new)
    if intent=='can edit':assert len(compile_region_tree(s,v,intent)['elements'])==3
    else:
        with pytest.raises(ValueError,match='UNKNOWN_QUOTE_AMBIGUOUS'):compile_region_tree(s,v,intent)


def test_real_entry_rejects_candidate_contract_without_coder_or_retry(monkeypatch,tmp_path):
    from test_region_tree_review_fixes import runner
    s,v=sample();bad=copy.deepcopy(s);bad['elements'][0].pop('parent');calls=[]
    def transport(arm,node,request):
        calls.append((arm,node))
        content=json.dumps(bad if arm=='candidate' else s) if node=='architect' else 'SYNTHETIC_NOT_A_PAGE'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),finish_reason='stop')])
    result=runner().run_pair(v,'','SYNTHETIC_MODEL',tmp_path/'pair',transport,transport_identity='SYNTHETIC_ZERO_NETWORK')
    assert calls==[('control','architect'),('control','coder'),('candidate','architect')]
    assert result['results'][1]['status']=='FAILED_NO_RETRY'
    assert result['new_html_files']==0
    traces=list((tmp_path/'pair/candidate/trace').glob('*region_tree_rejected.json'))
    assert len(traces)==1 and 'EXPLICIT_PARENT_REQUIRED' in traces[0].read_text()
