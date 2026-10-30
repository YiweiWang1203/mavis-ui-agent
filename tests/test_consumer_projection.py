import copy,json
from pathlib import Path
import pytest
from src.utils.consumer_projection import compile_consumer_projection, compare_browser_observation, compare_display_click, PROJECTION_SEPARATOR
from src.agents.coder import read_coder_prompt,build_coder_user_content
from scripts.run_consumer_projection_pair import validate_requests,MODEL

def state():
 return {'page_meta':{'viewport':{'width':300,'height':200}},'elements':[{'id':'a','type':'input','rpa_action':'type_text','spatial_info':{'bbox':[0,0,200,40]},'functional_content':{'render_bbox':[20,0,180,40]}},{'id':'b','type':'chat_message','rpa_action':'display_message','spatial_info':{'bbox':[0,60,100,100]}},{'id':'c','type':'mystery','rpa_action':'unfamiliar','spatial_info':{'bbox':[150,60,250,100]}}]}

def test_projection_uses_final_box_preserves_source_and_unknown():
 s=state();old=copy.deepcopy(s);p=compile_consumer_projection(s)
 assert s==old
 assert p['objects'][0]['target_css_xyxy']==[20,0,180,40]
 assert [x['role'] for x in p['objects']]==['native_edit','display_only','unknown']

def test_no_case_or_array_position_rules():
 s=state();s['elements'].reverse();p=compile_consumer_projection(s)
 assert [x['id'] for x in p['objects']]==['c','b','a']
 s['elements'][0]['id']='new_id';assert compile_consumer_projection(s)['objects'][0]['id']=='new_id'

def test_unknown_geometry_duplicate_and_nonfinite_rejected():
 for mutate in [lambda s:s['elements'].append(copy.deepcopy(s['elements'][0])),lambda s:s['elements'][0]['functional_content'].update(render_bbox=[0,0,float('nan'),40]),lambda s:s['elements'][0].update(functional_content={'render_bbox':[0,0,500,40]})]:
  s=state();mutate(s)
  with pytest.raises(ValueError):compile_consumer_projection(s)

def test_browser_not_html_gate_detects_actual_offsets_and_missing():
 p=compile_consumer_projection(state());r=compare_browser_observation(p,{'objects':[{'id':'a','box':[20,0,160,40]},{'id':'b','box':[20,60,100,40]}]})
 assert [x['status'] for x in r['rows']]==['PASS','FAIL','UNKNOWN']
 assert compare_browser_observation(p,{})['display_behavior'].startswith('UNKNOWN')

def test_duplicate_and_display_click_side_effects():
 p=compile_consumer_projection(state());r=compare_browser_observation(p,{'objects':[{'id':'a'},{'id':'a'}]})
 assert r['rows'][0]['failure_code']=='DUPLICATE_RENDERED_ID'
 a={'objects':[{'id':'b','text':'original'}]};b={'objects':[{'id':'b','text':'changed'}]}
 assert compare_display_click(p,'b',a,b)['status']=='FAIL'
 assert compare_display_click(p,'b',a,a)['status']=='PASS'
 assert compare_display_click(p,'b',{},a)['status']=='UNKNOWN'

def test_real_request_path_and_derived_only_information(monkeypatch):
 s=state();r={}
 for arm,mode in [('control','behavior_feedback_v1'),('candidate','consumer_projection_v1')]:
  monkeypatch.setenv('UI_CODER_CONTRACT_MODE',mode)
  r[arm]={'model':MODEL,'messages':[{'role':'system','content':read_coder_prompt()},{'role':'user','content':build_coder_user_content(s,'original raw',consumer_projection=arm=='candidate')}],'temperature':.2,'max_tokens':8192}
 validate_requests(r)
 assert r['candidate']['messages'][1]['content'].startswith(r['control']['messages'][1]['content']+PROJECTION_SEPARATOR)
 r['candidate']['messages'][1]['content']+=' hidden answer'
 with pytest.raises(ValueError):validate_requests(r)
