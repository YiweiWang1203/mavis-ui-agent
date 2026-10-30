import copy
import pytest
from src.utils.layout_solver import solve_ui_layout
from src.utils.functional_content import FunctionalContentRejected


def source():
    return {'page_meta':{'viewport':{'width':1000,'height':600}},'elements':[
       {'id':'text','type':'input_field','text':'entry','rpa_action':'edit','spatial_info':{'bbox':[100,400,800,480]}},
       {'id':'left','type':'button','text':'attach','rpa_action':'attach','spatial_info':{'bbox':[100,420,180,460]}},
       {'id':'voice','type':'button','text':'voice','rpa_action':'voice','spatial_info':{'bbox':[720,420,800,460]}},
       {'id':'send','type':'button','text':'send','rpa_action':'send','spatial_info':{'bbox':[760,440,840,480]}}],
       'interaction_groups':[{'id':'compose','kind':'composer','editable_id':'text','left_tools':['left'],
         'right_tools':['voice','send'],'footprint_policy':'union_of_source_boxes',
         'style_metrics':{'border_px':1,'content_inset_px':8,'caret_px':1},
         'evidence':{'status':'reviewed_structure','origin':'manual_structure_annotation',
                     'review_ref':'independent review','source_refs':['asr offsets','image region']}}]}


def compile(s):return solve_ui_layout(s,layout_mode='functional_content_v1',coordinate_space='target_px_xyxy')


def test_preserves_source_and_joint_surfaces():
    s=source();before=copy.deepcopy(s);r=compile(s)
    assert s==before
    for a,b in zip(s['elements'],r['elements']):
        for k,v in a.items():assert b[k]==v
    assert r['elements'][0]['functional_content']['render_bbox']==[180,400,680,480]
    assert r['elements'][0]['functional_content']['editable_content_rect']==[189,409,671,471]
    assert r['elements'][2]['functional_content']['render_bbox']==[680,420,760,460]


def test_no_group_exact_preserve_invariance():
    s=source();del s['interaction_groups']
    assert compile(s)==solve_ui_layout(s,layout_mode='preserve_target',coordinate_space='target_px_xyxy')


def test_translation_and_scale():
    s=source();base=compile(s)
    for e in s['elements']:e['spatial_info']['bbox']=[x+10 for x in e['spatial_info']['bbox']]
    shifted=compile(s)
    for a,b in zip(base['elements'],shifted['elements']):assert b['functional_content']['render_bbox']==[x+10 for x in a['functional_content']['render_bbox']]
    s=source();s['page_meta']['viewport']={'width':2000,'height':1200}
    for e in s['elements']:e['spatial_info']['bbox']=[x*2 for x in e['spatial_info']['bbox']]
    scaled=compile(s)
    for a,b in zip(base['elements'],scaled['elements']):assert b['functional_content']['render_bbox']==[x*2 for x in a['functional_content']['render_bbox']]


def test_unequal_sizes():
    s=source();s['elements'][2]['spatial_info']['bbox'][0]=700;r=compile(s)
    assert r['elements'][2]['functional_content']['render_bbox'][2]-r['elements'][2]['functional_content']['render_bbox'][0]==100
    assert r['elements'][0]['functional_content']['render_bbox'][2]==660


@pytest.mark.parametrize('bad',['unreviewed','missing_member','duplicate_member','unknown_policy','role_type','small','external','double_group'])
def test_rejects_not_squeezes(bad):
    s=source();g=s['interaction_groups'][0]
    if bad=='unreviewed':g['evidence']['status']='inferred'
    if bad=='missing_member':g['editable_id']='missing'
    if bad=='duplicate_member':g['left_tools']=['left','left']
    if bad=='unknown_policy':g['footprint_policy']='guess_parent'
    if bad=='role_type':s['elements'][0]['type']='image'
    if bad=='small':s['elements'][0]['spatial_info']['bbox']=[100,400,200,480]
    if bad=='external':s['elements'].append({'id':'overlay','type':'button','spatial_info':{'bbox':[200,400,300,480]}})
    if bad=='double_group':s['interaction_groups'].append(copy.deepcopy(g))
    with pytest.raises(FunctionalContentRejected):compile(s)


def test_explicit_ancestor_background_permitted():
    s=source();s['elements'].append({'id':'panel','type':'container','spatial_info':{'bbox':[50,350,900,500]}})
    for e in s['elements'][:-1]:e['parent_id']='panel'
    r=compile(s)
    assert all(e['parent_id']=='panel' for e in r['elements'][:-1])
    assert r['elements'][-1]==solve_ui_layout(s,layout_mode='preserve_target',coordinate_space='target_px_xyxy')['elements'][-1]


def test_unrelated_legal_containment_not_rejected():
    s=source();s['elements'] += [{'id':'background','type':'container','spatial_info':{'bbox':[0,0,90,90]}},
      {'id':'child','type':'text','text':'x','parent_id':'background','spatial_info':{'bbox':[10,10,50,50]}}]
    r=compile(s);baseline=solve_ui_layout(s,layout_mode='preserve_target',coordinate_space='target_px_xyxy')
    assert r['elements'][-2:]==baseline['elements'][-2:]
