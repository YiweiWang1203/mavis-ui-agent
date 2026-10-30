import copy
import math
import pytest
from src.utils.layout_solver import solve_ui_layout, TargetGeometryRejected, _line_count


def state():
    return {'page_meta':{'viewport':{'width':375,'height':812},'page_kind':'mobile_product_detail'},
            'elements':[{'id':'a','type':'input','text':'商品名','rpa_action':'input_name',
                         'spatial_info':{'bbox':[20,20,200,48],'source':'compiled_target','original_ratio':'evidence'}},
                        {'id':'b','type':'image_carousel','text':'gallery','rpa_action':'swipe_images',
                         'spatial_info':{'bbox':[20,60,300,220]}}]}


def preserve(s, space='target_px_xyxy'):
    return solve_ui_layout(s, layout_mode='preserve_target', coordinate_space=space)


def test_preserve_geometry_semantics_and_derive_from_retained_boxes():
    s=state();before=copy.deepcopy(s);r=preserve(s)
    assert s==before and r['page_meta']['layout_solver']['status']=='applied'
    for source,target in zip(s['elements'],r['elements']):
        for key in source: assert target[key]==source[key]
        box=source['spatial_info']['bbox'];g=target['render_geometry'];t=target['typography']
        assert g['center_ratio']==[(box[0]+box[2])/750,(box[1]+box[3])/1624]
        assert g['size_ratio']==[(box[2]-box[0])/375,(box[3]-box[1])/812]
        assert g['aspect_ratio']==(box[2]-box[0])/(box[3]-box[1])
        assert t['line_count']==_line_count(source['text'],box[2]-box[0],t['font_size_px'])


@pytest.mark.parametrize('space',[None,'photo_px','normalized'])
def test_coordinate_domain_must_be_explicit(space):
    with pytest.raises(TargetGeometryRejected): preserve(state(),space)


@pytest.mark.parametrize('box',[[20,20,10,40],[-1,20,10,40],[20,20,400,40],
                              [20,20,200,21],[20,20,21,40],[0,0,math.nan,40],
                              [0,0,math.inf,40],[False,0,30,40]])
def test_invalid_box_rejected_without_mutation_or_coder_admission(box):
    s=state();s['elements'][0]['spatial_info']['bbox']=box
    submitted=[]
    with pytest.raises(TargetGeometryRejected):
        result=preserve(s)
        submitted.append(result)
    assert submitted==[]


@pytest.mark.parametrize('bad',['missing_viewport','duplicate_id','missing_id','empty_elements'])
def test_invalid_contract_is_explicit_failure(bad):
    s=state()
    if bad=='missing_viewport': del s['page_meta']['viewport']
    if bad=='duplicate_id': s['elements'][1]['id']='a'
    if bad=='missing_id': del s['elements'][1]['id']
    if bad=='empty_elements':s['elements']=[]
    with pytest.raises(TargetGeometryRejected):preserve(s)


def test_legal_thin_divider_and_unresolved_containment_are_preserved():
    s=state();s['elements'].append({'id':'rule','type':'divider','text':'',
                                  'spatial_info':{'bbox':[20,50,300,51]}})
    s['elements'].append({'id':'inside','type':'button','text':'x','parent_id':'b',
                         'spatial_info':{'bbox':[50,80,80,110]}})
    s['elements'].append({'id':'unresolved','type':'button','text':'y',
                         'spatial_info':{'bbox':[60,90,90,120]}})
    r=preserve(s)
    assert [e['spatial_info'] for e in r['elements']]==[e['spatial_info'] for e in s['elements']]
    assert r['elements'][-1].get('parent_id') is None


def test_default_legacy_remains_legacy():
    s=state()
    assert solve_ui_layout(s)==solve_ui_layout(s,layout_mode='legacy')
    with pytest.raises(ValueError):solve_ui_layout(s,layout_mode='unknown')
