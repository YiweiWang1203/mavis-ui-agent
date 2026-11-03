import copy
import json
import os
from pathlib import Path

import pytest

from src.utils.region_plan_diagnostics import diagnose_region_plan


def fixture():
    evidence=[{'source':'model_inference','reason':'synthetic uncertainty'}]
    def leaf(identity,order):
        return {'id':identity,'parent':'region_local','order':order,'evidence':copy.deepcopy(evidence)}
    state={'elements':[leaf('alpha',0),leaf('beta',1)],'region_contract':{
        'root_id':'region_root','regions':[
            {'id':'region_root','parent':None,'layout':{'direction':'column'},'evidence':[{'source':'system_root'}]},
            {'id':'region_local','parent':'region_root','order':0,'layout':{'direction':'row'},'evidence':copy.deepcopy(evidence)}]},
        'relation_plan':{'relations':[{'id':'rel_horizontal','subject':'alpha','object':'beta',
           'kind':'left_of','status':'proposed','evidence':[{'source':'asr','quote':'alpha precedes beta'}]}]}}
    return state,{'elements':[{'id':'alpha'},{'id':'beta'}]},'alpha precedes beta. another exact span.'


def run(state,vision,intent):
    before=copy.deepcopy((state,vision,intent))
    result=diagnose_region_plan(state,vision,intent)
    assert (state,vision,intent)==before
    assert result['can_generate_page'] is False and result['production_acceptance']=='NOT_DECIDED'
    return result


def test_valid_synthetic_tree_is_observed_not_semantically_accepted():
    s,v,i=fixture();r=run(s,v,i)
    assert r['issues']==[]
    assert r['relation_checks'][0]['status']=='OBSERVED'
    assert r['relation_checks'][0]['semantic_support']=='UNKNOWN'


def test_multiple_errors_do_not_hide_independent_tree_conflict():
    s,v,i=fixture();s['region_contract']['regions'][1]['layout']['direction']='column'
    second=copy.deepcopy(s['relation_plan']['relations'][0]);second.update(id='rel_bad_quote')
    second['evidence']=[{'source':'asr','quote':'alpha...beta'}]
    s['relation_plan']['relations'].append(second)
    r=run(s,v,i)
    assert {'RELATION_TREE_CONFLICT','UNKNOWN_QUOTE_ABSENT','DUPLICATE_RELATION_CLAIM'}<=set(x['code'] for x in r['issues'])
    assert r['relation_checks'][1]['status']=='BLOCKED'
    assert r['relation_checks'][1]['conditional_tree_consistency']=='CONFLICT_WITH_DECLARATION'
    assert r['relation_checks'][1]['related_paths']


def test_regions_and_elements_share_order_domain_and_block_dependents():
    s,v,i=fixture();s['elements'][0].update(parent='region_root',order=0)
    r=run(s,v,i);collision=next(x for x in r['issues'] if x['code']=='AMBIGUOUS_SIBLING_ORDER')
    assert set(collision['facts']['node_ids'])=={'region_local','alpha'}
    assert collision['field_path'].endswith('.order') and collision['related_paths'][0].endswith('.order')
    assert r['relation_checks'][0]['status']=='BLOCKED'


@pytest.mark.parametrize('damage',['cycle','missing_parent','duplicate_id','bad_order','bad_direction','bad_endpoint'])
def test_invalid_dependencies_never_produce_relation_acceptance(damage):
    s,v,i=fixture()
    if damage=='cycle':s['region_contract']['regions'][1]['parent']='region_local'
    elif damage=='missing_parent':s['elements'][0]['parent']='region_absent'
    elif damage=='duplicate_id':s['elements'].append(copy.deepcopy(s['elements'][0]))
    elif damage=='bad_order':s['elements'][0]['order']=True
    elif damage=='bad_direction':s['region_contract']['regions'][1]['layout']['direction']='diagonal'
    else:s['relation_plan']['relations'][0]['subject']='nonexistent'
    r=run(s,v,i)
    assert r['issues'] and r['relation_checks'][0]['status']=='BLOCKED'


def test_quote_checks_continuity_overlap_count_and_unknown_status():
    s,v,i=fixture();c=s['relation_plan']['relations'][0]
    c.update(status='unknown');c['evidence']=[{'source':'asr','quote':'aa'},
        {'source':'asr','quote':'absent'}, {'source':'asr','quote':''}]
    r=run(s,v,'aaa')
    assert [(x['code'],x['facts'].get('occurrences')) for x in r['issues']]==[
        ('UNKNOWN_QUOTE_AMBIGUOUS',2),('UNKNOWN_QUOTE_ABSENT',0),('UNKNOWN_INVALID_QUOTE',0)]
    assert r['relation_checks'][0]['status']=='BLOCKED'
    s,v,i=fixture();s['relation_plan']['relations'][0]['status']='unknown'
    assert run(s,v,i)['relation_checks'][0]['status']=='UNKNOWN'


def test_separate_exact_quote_items_are_accepted_without_joining_or_inference():
    s,v,i=fixture();s['relation_plan']['relations'][0]['evidence'].append({'source':'asr','quote':'another exact span'})
    assert run(s,v,i)['issues']==[]


def test_invalid_ancestor_source_blocks_enforcement_but_keeps_raw_tree_fact():
    s,v,i=fixture();s['region_contract']['regions'][1]['evidence']=[{'source':'asr','quote':'missing'}]
    r=run(s,v,i)
    assert r['relation_checks'][0]['status']=='BLOCKED'
    assert r['relation_checks'][0]['conditional_tree_consistency']=='CONSISTENT_WITH_DECLARATION'


@pytest.mark.parametrize('state',[None,{}, {'elements':None,'region_contract':{'root_id':{},'regions':[None]}},
    {'elements':[{'id':'x','parent':[]}],'region_contract':{'root_id':'none','regions':[]},'relation_plan':[]}])
def test_malformed_inputs_are_diagnostic_not_unhandled_exceptions(state):
    r=run(state,{},None)
    assert r['issues']


def test_all_ids_can_be_renamed_without_case_rules():
    s,v,i=fixture();before=run(s,v,i)
    replacements={'alpha':'gamma_77','beta':'delta_8','region_root':'region_new',
                  'region_local':'region_other','rel_horizontal':'rel_renamed'}
    def rename(x):
        if isinstance(x,str):return replacements.get(x,x)
        if isinstance(x,list):return [rename(v) for v in x]
        if isinstance(x,dict):return {k:rename(v) for k,v in x.items()}
        return x
    after=run(rename(s),rename(v),i)
    assert [x['code'] for x in before['relation_checks']]==[x['code'] for x in after['relation_checks']]


def test_real_saved_failure_fixtures_without_correction_or_network(monkeypatch):
    root=os.getenv('REGION_DIAGNOSTIC_FIXTURE_DIR')
    if not root:pytest.skip('external frozen failure fixture not configured')
    root=Path(root)
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        s=json.loads((directory/'state.json').read_text(encoding='utf-8'))
        v=json.loads((directory/'vision.json').read_text(encoding='utf-8'))
        i=(directory/'intent.txt').read_text(encoding='utf-8')
        expected=json.loads((directory/'expected.json').read_text(encoding='utf-8'))
        from src.utils.region_tree_contract import compile_region_tree
        monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1')
        monkeypatch.setenv('UI_REGION_RELATION_MODE',expected['relation_mode'])
        with pytest.raises(ValueError,match='^'+expected['production_rejection']+'$'):
            compile_region_tree(s,v,i)
        r=run(s,v,i)
        with pytest.raises(ValueError,match='^'+expected['production_rejection']+'$'):
            compile_region_tree(s,v,i)
        for code,count in expected['issue_counts'].items():
            assert sum(x['code']==code for x in r['issues'])==count
        for code,count in expected['check_counts'].items():
            assert sum(x.get('code')==code for x in r['relation_checks'])==count
        identifiers=[x['id'] for x in s['elements']+s['region_contract']['regions']]
        identifiers += [x['id'] for x in s.get('relation_plan',{}).get('relations',[])]
        mapping={identity:('region_' if identity.startswith('region_') else
                          'rel_' if identity.startswith('rel_') else 'obj_')+str(n)
                 for n,identity in enumerate(identifiers)}
        def rename(value):
            if isinstance(value,str):return mapping.get(value,value)
            if isinstance(value,list):return [rename(x) for x in value]
            if isinstance(value,dict):return {k:rename(v) for k,v in value.items()}
            return value
        renamed=run(rename(s),rename(v),i)
        assert [x['code'] for x in renamed['issues']]==[x['code'] for x in r['issues']]
        assert [x.get('code') for x in renamed['relation_checks']]==[x.get('code') for x in r['relation_checks']]


def test_cli_is_offline_exclusive_write_only(tmp_path):
    import subprocess
    import sys
    s,v,i=fixture()
    for name,value in [('state',s),('vision',v)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    (tmp_path/'intent.txt').write_text(i,encoding='utf-8')
    cli=Path(__file__).resolve().parents[1]/'scripts/diagnose_region_plan.py'
    args=[sys.executable,str(cli),'--state',str(tmp_path/'state.json'),'--vision',str(tmp_path/'vision.json'),
          '--intent',str(tmp_path/'intent.txt'),'--out',str(tmp_path/'diagnosis.json')]
    first=subprocess.run(args,capture_output=True,text=True,timeout=10)
    assert first.returncode==0,first.stderr
    original=(tmp_path/'diagnosis.json').read_bytes()
    second=subprocess.run(args,capture_output=True,text=True,timeout=10)
    assert second.returncode!=0 and (tmp_path/'diagnosis.json').read_bytes()==original
