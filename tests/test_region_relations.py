"""Generic synthetic relations; no reviewed case answers or external calls."""
import copy,json,importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.utils.region_tree_contract import compile_region_tree
from src.utils.region_relations import enabled,RegionRelationError


def fixture():
 ev=[{'source':'model_inference','reason':'synthetic organization; semantic support unknown'}]
 size={'basis_px':'auto','grow':1,'shrink':1,'cross':'stretch'}
 def region(name,parent,order,direction):
  r=dict(id=name,kind='semantic_region',parent=parent,evidence=copy.deepcopy(ev),layout=dict(direction=direction,gap_px=0,padding_px=0,overflow='visible'))
  if parent is not None:r.update(order=order,sizing=copy.deepcopy(size),relation_status='proposed')
  else:r['evidence']=[{'source':'system_root'}]
  return r
 regs=[region('region_root',None,None,'row'),region('region_stack','region_root',0,'column'),
       region('region_detail','region_root',1,'column'),region('region_tools','region_stack',0,'row'),
       region('region_footer','region_detail',1,'row')]
 elements=[]
 for name,parent,order in [('a','region_tools',0),('b','region_tools',1),('c','region_stack',1),('d','region_detail',0),('e','region_footer',0),('f','region_footer',1)]:
  elements.append(dict(id=name,type='text',text='same',actions=['existing_'+name],parent=parent,order=order,
      sizing=copy.deepcopy(size),relation_status='proposed',evidence=copy.deepcopy(ev)))
 vision={'elements':[{k:copy.deepcopy(e[k]) for k in ('id','type','text','actions')} for e in elements]}
 state={'page_meta':{'viewport':{'width':1000,'height':700}},'elements':elements,
        'region_contract':{'version':'region-tree-v2','root_id':'region_root','regions':regs},
        'relation_plan':{'version':'spatial-relations-v1','relations':[]}}
 return state,vision


def claim(kind,a,b,status='proposed',evidence=None):
 return {'id':'rel_'+kind+'_'+a+'_'+b,'kind':kind,'subject':a,'object':b,'status':status,
         'evidence':evidence or [{'source':'model_inference','reason':'synthetic uncertain proposal'}]}

@pytest.fixture(autouse=True)
def active(monkeypatch):
 monkeypatch.setenv('UI_REGION_TREE_MODE','region_tree_v1');monkeypatch.setenv('UI_REGION_RELATION_MODE','relation_first_v1')


def test_nested_mixed_axes_and_deep_containment_no_mutation():
 s,v=fixture();s['relation_plan']['relations']=[claim('left_of','a','b'),claim('above','b','c'),claim('contains','region_detail','f'),claim('above','d','e'),claim('left_of','c','d')]
 original=copy.deepcopy(s);vision=copy.deepcopy(v);out=compile_region_tree(s,v,'')
 assert s==original and v==vision and out['elements']==s['elements']
 assert out['region_layout']['parent_by_id']['e']=='region_footer'
 records=out['relation_review']['claims'];assert len(records)==5
 assert all(r['consistency']=='PROPOSED_CONSISTENT_WITH_TREE' and r['semantic_support']=='UNKNOWN' for r in records)
 assert records[1]['tree_fact']['lowest_common_ancestor']=='region_stack'
 assert out['relation_review']['source_relation_coverage']=='NOT_VERIFIED_BY_CODE'

@pytest.mark.parametrize('relation',[claim('left_of','b','a'),claim('above','a','b'),claim('contains','region_stack','f'),claim('left_of','region_stack','a'),claim('contains','a','b')])
def test_conflict_with_actual_tree_rejected_not_repaired(relation):
 s,v=fixture();s['relation_plan']['relations']=[relation];before=copy.deepcopy(s)
 with pytest.raises(RegionRelationError) as e:compile_region_tree(s,v,'')
 assert len(e.value.diagnostics)==1 and e.value.diagnostics[0]['relation']['consistency']=='CONFLICT_WITH_TREE'
 assert s==before


def test_opposite_claims_and_multiple_conflicts_all_recorded():
 s,v=fixture();s['relation_plan']['relations']=[claim('left_of','a','b'),claim('left_of','b','a'),claim('above','a','b')]
 with pytest.raises(RegionRelationError) as e:compile_region_tree(s,v,'')
 assert len(e.value.diagnostics)==2


def test_unknown_contradictory_claim_not_enforced_or_promoted():
 s,v=fixture();s['relation_plan']['relations']=[claim('above','a','b','unknown')]
 out=compile_region_tree(s,v,'');r=out['relation_review']
 assert r['claims'][0]['consistency']=='UNKNOWN_NOT_ENFORCED' and r['unknown_count']==1
 assert r['outcome']=='NO_PROPOSED_RELATIONS_NOT_VALIDATED' and out['relation_plan']==s['relation_plan']


def test_empty_claims_never_source_coverage_pass():
 s,v=fixture();out=compile_region_tree(s,v,'')
 assert out['relation_review']['outcome']=='NO_PROPOSED_RELATIONS_NOT_VALIDATED'

@pytest.mark.parametrize('mutation',[
 lambda s:s.pop('relation_plan'),lambda s:s['relation_plan'].update(extra='other_mapping'),
 lambda s:s['relation_plan']['relations'].append(claim('left_of','missing','b')),
 lambda s:s['relation_plan']['relations'].append(claim('left_of','a','a')),
 lambda s:s['relation_plan']['relations'].append(claim('below','a','b')),
 lambda s:s['relation_plan']['relations'].extend([claim('left_of','a','b'),claim('left_of','a','b')]),
 lambda s:s['relation_plan']['relations'].append(claim('left_of','a','b','confirmed'))])
def test_bad_or_missing_contract_rejected(mutation):
 s,v=fixture();mutation(s)
 with pytest.raises(ValueError):compile_region_tree(s,v,'')


def test_quote_location_not_semantic_truth_and_absent_quote_rejected():
 s,v=fixture();s['relation_plan']['relations']=[claim('left_of','a','b',evidence=[{'source':'asr','quote':'first before second'}])]
 out=compile_region_tree(s,v,'first before second')
 assert out['relation_review']['claims'][0]['evidence'][0]['status']=='UNIQUE_EXACT_QUOTE'
 assert out['relation_review']['claims'][0]['semantic_support']=='UNKNOWN'
 with pytest.raises(ValueError,match='ABSENT'):compile_region_tree(s,v,'other text')


def test_existing_source_protection_not_weakened():
 s,v=fixture();s['elements'][0]['actions']=[]
 with pytest.raises(ValueError,match='UNSOURCED_OBSERVATION_CHANGE'):compile_region_tree(s,v,'')


def test_off_keeps_previous_contract(monkeypatch):
 s,v=fixture();s.pop('relation_plan');monkeypatch.setenv('UI_REGION_RELATION_MODE','off')
 out=compile_region_tree(s,v,'');assert 'relation_review' not in out

@pytest.mark.parametrize('tree,mode',[('off','relation_first_v1'),('region_tree_v1','invalid')])
def test_mode_combinations_rejected(monkeypatch,tree,mode):
 monkeypatch.setenv('UI_REGION_TREE_MODE',tree);monkeypatch.setenv('UI_REGION_RELATION_MODE',mode)
 with pytest.raises(ValueError):enabled()


def test_actual_new_pair_entry_only_spatial_variable(tmp_path,monkeypatch):
 path=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py'
 spec=importlib.util.spec_from_file_location('relation_pair_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 s,v=fixture();s['relation_plan']['relations']=[claim('left_of','a','b')];calls=[]
 def transport(arm,node,request):
  calls.append((arm,node,copy.deepcopy(request)))
  state=copy.deepcopy(s)
  if arm=='control':state.pop('relation_plan')
  value=json.dumps(state) if node=='architect' else '```html\n<html><body>SYNTHETIC offline fixture</body></html>\n```\nExplanation'
  return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value),finish_reason='stop')])
 result=module.run_pair(v,'synthetic intent','SYNTHETIC',tmp_path/'pair',transport,transport_identity='OFFLINE_ZERO_NETWORK',export_original_html=True,comparison='region_relation_v1')
 assert len(calls)==4 and all(x['status']=='PIPELINE_RETURNED_NOT_ACCEPTED' for x in result['results'])
 arch=[c for c in calls if c[1]=='architect'];code=[c for c in calls if c[1]=='coder']
 assert arch[0][2]['messages'][1]==arch[1][2]['messages'][1]
 assert arch[0][2]['messages'][0]['content'] in arch[1][2]['messages'][0]['content']
 assert 'Relation-first mechanism' not in arch[0][2]['messages'][0]['content'] and 'Relation-first mechanism' in arch[1][2]['messages'][0]['content']
 assert code[0][2]['messages'][0]==code[1][2]['messages'][0]
 for _,_,r in calls:assert r['timeout']==600 and r['max_tokens']==8192
 for arm in ('control','candidate'):
  state=json.loads((tmp_path/'pair'/arm/'ui_state.json').read_text(encoding='utf-8'))
  assert state['region_layout']['version']=='region-flex-v1' and state['elements']==s['elements']
  assert (tmp_path/'pair'/arm/'html_export.json').is_file()


def test_real_pair_conflict_stops_candidate_coder_only(tmp_path):
 path=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py';spec=importlib.util.spec_from_file_location('relation_bad_pair_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 s,v=fixture();s['relation_plan']['relations']=[claim('above','a','b')];calls=[]
 def transport(arm,node,request):
  calls.append((arm,node));state=copy.deepcopy(s)
  if arm=='control':state.pop('relation_plan')
  value=json.dumps(state) if node=='architect' else '<html><body>SYNTHETIC</body></html>'
  return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value),finish_reason='stop')])
 r=module.run_pair(v,'','SYNTHETIC',tmp_path/'pair',transport,transport_identity='OFFLINE_ZERO_NETWORK',comparison='region_relation_v1')
 assert calls==[('control','architect'),('control','coder'),('candidate','architect')]
 assert r['results'][1]['original_error']=='RELATION_TREE_CONFLICT' and not r['results'][1]['coder_dispatched']
 assert r['results'][1]['error_details'][0]['node_id'].startswith('rel_')
