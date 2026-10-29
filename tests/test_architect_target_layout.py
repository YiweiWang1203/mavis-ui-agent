import copy
import unittest
from unittest.mock import patch
from src.utils.architect_target_layout import compile_architect_target_layout
from src.utils.coordinate_contract import CoordinateResponsibilityError
from src.utils.hierarchy_contract import build_structure
from src.agents.ui_architect import finalize_ui_state
from src.renderers.controlled_components import render_controlled_components


def fixture():
    raw={'page_meta':{'viewport':{'width':1440,'height':900}},'elements':[
        {'id':'e1','vision_id':'e1','origin':'vision','type':'input','text':'Edit','parent_id':None,
         'rpa_action':'fill','spatial_info':{'bbox':[400,700,1200,770]}}]}
    vision={'canvas':{'width':406,'height':720},'elements':[{'id':'e1','type':'input',
        'bbox':{'x_min':.1,'y_min':.1,'x_max':.2,'y_max':.2}}]}
    return raw,vision,{'id':'f','width':406,'height':720,'sha256':'a'*64},{'id':'pc','width':1440,'height':900}


class TargetLayoutTests(unittest.TestCase):
    def test_strict_finalize_uses_pre_overwrite_gate_and_preserves_target(self):
        raw,v,f,vp=fixture()
        raw['page_meta']['coordinate_provenance']={'observation_frame':f,'target_viewport':vp}
        submitted={'kind':'semantic_layout','evidence_refs':['vision:e1'],'reason':'declared test plan'}
        raw['elements'][0]['spatial_info'].update(
            coordinate_space='viewport_px', viewport_id='pc',
            derivation=copy.deepcopy(submitted))
        with patch.dict('os.environ', {'UI_COORDINATE_RESPONSIBILITY_MODE':'strict_v1'}):
            result=finalize_ui_state(raw,'',v,'hierarchy_v1')
        self.assertEqual(result['elements'][0]['spatial_info']['bbox'],[400,700,1200,770])
        self.assertEqual(result['elements'][0]['spatial_info']['derivation'],submitted)
        self.assertTrue(result['page_meta']['architect_target_layout']['submitted_derivation_preserved'])
        self.assertEqual(result['page_meta']['architect_target_layout']['compiler_derivation_fallback_count'],0)
        self.assertFalse(result['page_meta']['coordinate_contract']['implicit_photo_to_viewport_mapping'])

    def test_compiler_preserves_submitted_derivation_fields(self):
        raw,v,f,vp=fixture()
        submitted={'kind':'semantic_layout','evidence_refs':['vision:e1'],
                   'reason':'original source rationale','review_note':'semantics unverified'}
        raw['elements'][0]['spatial_info']['derivation']=copy.deepcopy(submitted)
        result=compile_architect_target_layout(raw,v,frame=f,viewport=vp)
        self.assertEqual(result['elements'][0]['spatial_info']['derivation'],submitted)

    def test_compiler_rejects_unknown_submitted_source_without_rewriting(self):
        raw,v,f,vp=fixture()
        raw['elements'][0]['spatial_info']['derivation']={
            'kind':'semantic_layout','evidence_refs':['vision:does_not_exist'],
            'reason':'invalid source probe'}
        before=copy.deepcopy(raw)
        with self.assertRaisesRegex(ValueError,'evidence references'):
            compile_architect_target_layout(raw,v,frame=f,viewport=vp)
        self.assertEqual(raw,before)

    def test_strict_finalize_rejects_round65_shape_before_overwrite(self):
        raw,v,f,vp=fixture()
        raw['page_meta']['coordinate_provenance']={'observation_frame':f,'target_viewport':vp}
        raw['elements'][0]['spatial_info']['bbox']=[1440,900,1440,900]
        before=copy.deepcopy(raw)
        with patch.dict('os.environ', {'UI_COORDINATE_RESPONSIBILITY_MODE':'strict_v1'}):
            with self.assertRaises(CoordinateResponsibilityError) as caught:
                finalize_ui_state(raw,'',v,'hierarchy_v1')
        self.assertEqual(caught.exception.diagnostic['invalid_count'],1)
        self.assertEqual(caught.exception.diagnostic['elements'][0]['raw_bbox'],[1440,900,1440,900])
        self.assertEqual(raw,before)

    def test_target_is_retained_observations_do_not_move_it(self):
        raw,v,f,vp=fixture();before=copy.deepcopy((raw,v))
        first=compile_architect_target_layout(raw,v,frame=f,viewport=vp)
        v2=copy.deepcopy(v);v2['elements'][0]['bbox']['x_min']=.15
        second=compile_architect_target_layout(raw,v2,frame=f,viewport=vp)
        self.assertEqual(first['elements'][0]['spatial_info']['bbox'],[400,700,1200,770])
        self.assertEqual(first['elements'][0]['spatial_info'],second['elements'][0]['spatial_info'])
        self.assertNotEqual(first['elements'][0]['observation_geometry'],second['elements'][0]['observation_geometry'])
        self.assertEqual((raw,v),before)
        self.assertIn('input',render_controlled_components(first))

    def test_legacy_baseline_still_scales_photo(self):
        raw,v,_,_=fixture()
        self.assertEqual(build_structure(raw,v)['elements'][0]['spatial_info']['bbox'],[144,90,288,180])

    def test_missing_observed_entity_has_no_invented_placement(self):
        raw,v,f,vp=fixture();raw['elements']=[]
        with self.assertRaises(ValueError):compile_architect_target_layout(raw,v,frame=f,viewport=vp)

    def test_outside_or_tiny_control_rejected_without_clamp(self):
        for b in ([400,700,1500,770],[400,700,1200,910],[400,700,420,770]):
            raw,v,f,vp=fixture();raw['elements'][0]['spatial_info']['bbox']=b
            with self.assertRaises(ValueError):compile_architect_target_layout(raw,v,frame=f,viewport=vp)

    def test_unknown_source_rejected(self):
        raw,v,f,vp=fixture();raw['elements'][0]['vision_id']='missing'
        with self.assertRaises(ValueError):compile_architect_target_layout(raw,v,frame=f,viewport=vp)

    def test_parent_conflict_is_reported_without_moving_child(self):
        raw,v,f,vp=fixture();raw['elements'].insert(0,{'id':'u_parent','origin':'spoken','type':'container','parent_id':None,
            'spatial_info':{'bbox':[0,0,300,300]}});raw['elements'][1]['parent_id']='u_parent'
        result=compile_architect_target_layout(raw,v,frame=f,viewport=vp)
        self.assertEqual(len(result['page_meta']['architect_target_layout']['parent_containment_conflicts']),1)
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'],[400,700,1200,770])
