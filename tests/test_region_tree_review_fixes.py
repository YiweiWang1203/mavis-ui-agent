import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_region_tree_contract import sample
from src.utils.region_tree_contract import compile_region_tree


def declaration(s, v, field='type'):
    return {'quote':'editable','reason':'synthetic sourced planning proposal, not semantic confirmation'}


@pytest.mark.parametrize('field,value',[('type','input'),('text','other'),('rpa_action','send'),('actions',['click'])])
def test_unsourced_changes(field,value):
    s,v=sample();s['elements'][0][field]=value
    with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,'editable')


def test_sourced_refinement_retains_both_observation_and_plan():
    s,v=sample();s['elements'][0]['type']='input';s['elements'][0]['change_sources']={'type':declaration(s,v)}
    original=copy.deepcopy(v);out=compile_region_tree(s,v,'editable')
    assert out['elements']==s['elements'] and v==original
    assert out['observation_provenance']['original_vision']==original
    assert out['observation_provenance']['changes'][0]['status']=='SOURCED_PLANNING_PROPOSAL'
    assert out['observation_provenance']['changes'][0]['semantic_support']=='UNKNOWN'


@pytest.mark.parametrize('kind',['wrong_quote','deletion','unused_field','model_before'])
def test_bad_declarations(kind):
    s,v=sample();s['elements'][0]['type']='input';d=declaration(s,v);s['elements'][0]['change_sources']={'type':d}
    if kind=='wrong_quote':d['quote']='missing'
    if kind=='deletion':
        del s['elements'][0]['type']
    if kind=='unused_field':s['elements'][0]['change_sources']['text']=copy.deepcopy(d)
    if kind=='model_before':d['before']='wrong'
    with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,'editable')


@pytest.mark.parametrize('new_mode',[True,False])
def test_actual_coder_prompt_isolates_old_marker(monkeypatch,new_mode):
    from src.agents import coder
    s,v=sample();s['page_meta']['layout_solver']={'version':'hierarchy-v1'}
    state=compile_region_tree(s,v,'') if new_mode else s;calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='<html><body>SYNTHETIC OFFLINE FIXTURE</body></html>'),finish_reason='stop')])
    monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1' if new_mode else 'off');monkeypatch.setenv('UI_RENDERER_MODE','llm')
    monkeypatch.setattr(coder,'_get_openai_client',lambda:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(coder,'save_html_asset',lambda code:None);coder.generate_frontend_code(state)
    assert ('Render all elements absolutely under one positioned page root' in calls[0]['messages'][0]['content'])==(not new_mode)
    assert state['page_meta']['layout_solver']['version']=='hierarchy-v1'


def runner():
    p=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py'
    spec=importlib.util.spec_from_file_location('paired_runner',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('finish',['stop','length','timeout'])
def test_shared_runner_budget_and_terminal_rules(tmp_path,finish):
    s,v=sample();calls=[]
    def transport(arm,node,request):
        calls.append((arm,node,request))
        if finish=='timeout':raise TimeoutError('synthetic timeout')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(s) if node=='architect' else '<html><body>SYNTHETIC OFFLINE FIXTURE</body></html>'),finish_reason=finish)])
    result=runner().run_pair(v,'','SYNTHETIC_MODEL',tmp_path/'pair',transport,transport_identity='SYNTHETIC_NO_NETWORK')
    assert len(calls)==(4 if finish=='stop' else 2)
    for arm,node,request in calls:
        assert request['model']=='SYNTHETIC_MODEL' and request['max_tokens']==8192 and request['timeout']==600
        assert request['temperature']==(.3 if node=='architect' else .2)
    diff=json.loads((tmp_path/'pair/request_diff.json').read_text())
    assert diff['architect']['shared_policy_equal']
    assert all(r['status']==('PIPELINE_RETURNED_NOT_ACCEPTED' if finish=='stop' else 'FAILED_NO_RETRY') for r in result['results'])
    assert not list((tmp_path/'pair').rglob('*.html'))


def test_both_clients_zero_retries(monkeypatch):
    import sys
    from src.agents import coder,ui_architect
    calls=[]
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(OpenAI=lambda **kwargs:calls.append(kwargs)))
    monkeypatch.setenv('SILICONFLOW_API_KEY','SYNTHETIC_NOT_A_CREDENTIAL');monkeypatch.setenv('UI_PAIRED_RUN_POLICY','frozen_v1')
    for mode in ('off','region_tree_v1'):
        monkeypatch.setenv('UI_REGION_TREE_MODE',mode);coder._get_openai_client();ui_architect._get_openai_client()
    assert len(calls)==4 and all(c['max_retries']==0 and c['timeout']==600 for c in calls)
