import copy
import json
from types import SimpleNamespace
import pytest
from src.utils.region_tree_contract import compile_region_tree, enabled, neutral_instructions, NEUTRAL


def sample():
    ev=[{'source':'model_inference','reason':'synthetic engineering fixture; not a judged correct UI'}]
    size={'basis_px':'auto','grow':1,'shrink':1,'cross':'stretch'}
    state={'page_meta':{'viewport':{'width':1440,'height':900}},'elements':[
        {'id':'left','type':'text','text':'same','rpa_action':'display_a','spatial_info':{'bbox':[0,0,10,10]}},
        {'id':'right','type':'input','text':'same','rpa_action':'type_text','spatial_info':{'bbox':[5,5,15,15]}}],
        'region_contract':{'version':'region-tree-v2','root_id':'region_page','regions':[
            {'id':'region_page','kind':'semantic_region','parent':None,'evidence':[{'source':'system_root'}],
             'layout':{'direction':'row','gap_px':8,'padding_px':0,'overflow':'visible'}}],
            }}
    for i,item in enumerate(state['elements']):
        item.update(parent='region_page',order=i,evidence=copy.deepcopy(ev),sizing=copy.deepcopy(size),relation_status='proposed')
    vision={'canvas':{'width':406,'height':720},'elements':[{'id':e['id'],'type':e['type'],'text':e['text'],'rpa_action':e['rpa_action'],'bbox':{'x_min':0,'y_min':0,'x_max':1,'y_max':1}} for e in state['elements']]}
    return state,vision


def test_preserve_objects_same_text_overlapping_boxes_and_coordinate_evidence():
    s,v=sample();before=copy.deepcopy(s);out=compile_region_tree(s,v,'')
    assert s==before and out['elements']==s['elements']
    assert out['region_layout']['children']['region_page']==['left','right']
    assert out['source_coordinate_evidence']['vision']==v
    assert out['region_layout']['css_by_id']['region_page']['width']=='1440px'
    assert not any(e['id'].startswith('region_') for e in out['elements'])


@pytest.mark.parametrize('mutate',[
    lambda s:s['elements'].pop(),
    lambda s:s['elements'].append(copy.deepcopy(s['elements'][0])),
    lambda s:s['region_contract'].update(objects=[]),
    lambda s:s['elements'][0].update(parent='missing'),
    lambda s:s['elements'][1].update(order=0),
    lambda s:s['elements'][0].update(evidence=[]),
    lambda s:s['elements'][0]['sizing'].update(grow=float('nan')),
    lambda s:s['elements'][0].update(parent_id='wrong'),
    lambda s:s['region_contract']['regions'][0]['layout'].update(direction='equal-five'),
])
def test_invalid_contract_fails_without_fallback(mutate):
    s,v=sample();mutate(s)
    with pytest.raises((ValueError,TypeError)):compile_region_tree(s,v,'')


def test_asr_reference_existence_not_semantic_confirmation():
    s,v=sample();s['elements'][0]['evidence']=[{'source':'asr','quote':'left'}]
    out=compile_region_tree(s,v,'left area')
    assert out['region_layout']['review'][1]['status']=='model_proposed_not_human_confirmed'
    with pytest.raises(ValueError):compile_region_tree(s,v,'different')


def test_cycles_and_unreachable_regions_rejected():
    s,v=sample();node=copy.deepcopy(s['region_contract']['regions'][0]);node.update(id='region_cycle',parent='region_cycle',order=2,relation_status='proposed',evidence=[{'source':'model_inference','reason':'test'}],sizing={'basis_px':'auto','grow':1,'shrink':1})
    s['region_contract']['regions'].append(node)
    with pytest.raises(ValueError,match='REGION_CYCLE'):compile_region_tree(s,v,'')


def test_missing_relation_does_not_get_inferred_from_bbox():
    s,v=sample();del s['elements'][0]['parent']
    with pytest.raises(ValueError,match='EXPLICIT_PARENT_REQUIRED'):compile_region_tree(s,v,'')


def test_unknown_root_membership_preserved_not_confirmed():
    s,v=sample();s['elements'][0]['relation_status']='unknown'
    out=compile_region_tree(s,v,'')
    assert out['region_layout']['review'][1]['status']=='unknown'


def test_default_off_and_conflict_matrix(monkeypatch):
    monkeypatch.delenv('UI_REGION_TREE_MODE',raising=False);assert enabled() is False
    monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1');assert enabled()
    monkeypatch.setenv('UI_STRUCTURE_MODE','hierarchy_v1')
    with pytest.raises(ValueError,match='CONFLICTING_LEGACY_MODE'):enabled()


def test_neutral_same_for_both_modes(monkeypatch):
    monkeypatch.setenv('UI_NEUTRAL_VISUAL_MODE','neutral_v1')
    neutral=neutral_instructions();monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1')
    assert neutral==neutral_instructions() and all(color in neutral for color in NEUTRAL.values())


def test_real_finalize_bypasses_legacy_layout(monkeypatch):
    from src.agents import ui_architect
    monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1')
    monkeypatch.setattr(ui_architect,'repair_ui_state_with_vision',lambda *a,**k:pytest.fail('legacy repair entered'))
    monkeypatch.setattr(ui_architect,'solve_ui_layout',lambda *a,**k:pytest.fail('legacy layout entered'))
    s,v=sample();assert ui_architect.finalize_ui_state(s,'',v,'baseline')['elements']==s['elements']


def test_disabled_finalize_still_uses_original_path(monkeypatch):
    from src.agents import ui_architect
    monkeypatch.setenv('UI_REGION_TREE_MODE','off');seen=[]
    def stage(name):
        def run(state,*args,**kwargs):seen.append(name);return state
        return run
    monkeypatch.setattr(ui_architect,'repair_ui_state_with_vision',stage('repair'))
    monkeypatch.setattr(ui_architect,'apply_ui_priors',stage('priors'))
    monkeypatch.setattr(ui_architect,'solve_ui_layout',stage('layout'))
    s,v=sample();ui_architect.finalize_ui_state(s,'',v,'baseline')
    assert seen==['repair','priors','layout']


def test_real_model_message_consumption_without_network(monkeypatch):
    from src.agents import ui_architect,coder
    s,v=sample();calls=[]
    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(s) if len(calls)==1 else 'SYNTHETIC_CODER_RESPONSE_NOT_A_PAGE'),finish_reason='stop')])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1');monkeypatch.setenv('UI_RENDERER_MODE','llm');monkeypatch.setenv('UI_NEUTRAL_VISUAL_MODE','neutral_v1')
    monkeypatch.setattr(ui_architect,'_get_openai_client',lambda:client);monkeypatch.setattr(coder,'_get_openai_client',lambda:client)
    monkeypatch.setattr(coder,'save_html_asset',lambda code:None)
    result=ui_architect.generate_ui_state('',v);coder.generate_frontend_code(result)
    assert len(calls)==2 and 'region_contract schema' in calls[0]['messages'][0]['content']
    assert 'region_layout' in calls[1]['messages'][1]['content']
    assert all(c['max_tokens']==8192 and c['timeout']==600 for c in calls)
    assert all(color in calls[1]['messages'][0]['content'] for color in NEUTRAL.values())
