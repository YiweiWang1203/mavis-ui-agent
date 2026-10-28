import copy
import unittest
from src.utils.global_spatial_contract import compile_global_spatial
from src.renderers.controlled_components import render_controlled_components
from src.agents.global_spatial_planner import parse_spatial_response


class GlobalSpatialTests(unittest.TestCase):
    def test_duplicate_json_fields_cannot_silently_discard_regions(self):
        with self.assertRaisesRegex(ValueError,'Duplicate spatial JSON field'):
            parse_spatial_response('{"regions":[],"placements":[],"regions":[{}]}')

    def fixture(self):
        state={'page_meta':{'viewport':{'width':1440,'height':900}},'elements':[
            {'id':'v','type':'button','text':'操作','parent_id':None,'rpa_action':'click','spatial_info':{'bbox':[10,10,50,50]}}]}
        declaration={'page_bbox':[.1,.4,.9,.8],'regions':[
            {'id':'u_region_a','parent_id':None,'label':'左栏','evidence_quote':'左侧区域','bbox':[.1,.4,.3,.8]}],
            'placements':[{'id':'v','region_id':'u_region_a','bbox':[.12,.42,.2,.46]}]}
        return state,declaration

    def test_photo_page_region_transform_and_no_input_mutation(self):
        state,d=self.fixture();before=copy.deepcopy(state)
        out=compile_global_spatial(state,'左侧区域',d)
        self.assertEqual(state,before)
        self.assertEqual(out['elements'][0]['spatial_info']['bbox'],[0,0,360,900])
        self.assertEqual(out['elements'][1]['spatial_info']['bbox'],[36,45,180,135])
        self.assertEqual(out['elements'][1]['type'],'button')
        self.assertEqual(out['elements'][0]['children_ids'],['v'])
        html=render_controlled_components(out)
        self.assertIn('left:36px;top:45px;',html)
        self.assertIn('data-parent-id="u_region_a"',html)

    def test_mobile_uses_same_normalized_mapping(self):
        state,d=self.fixture();state['page_meta']['viewport']={'width':375,'height':812}
        out=compile_global_spatial(state,'左侧区域',d)
        self.assertEqual(out['elements'][0]['spatial_info']['bbox'],[0,0,94,812])

    def test_rejects_outside_parent_missing_object_forged_source_duplicate_and_cycle(self):
        for mode in ['outside','missing','quote','duplicate','cycle']:
            with self.subTest(mode=mode):
                state,d=self.fixture()
                if mode=='outside':d['placements'][0]['bbox']=[.2,.42,.4,.46]
                if mode=='missing':d['placements']=[]
                if mode=='quote':d['regions'][0]['evidence_quote']='invented'
                if mode=='duplicate':d['placements']*=2
                if mode=='cycle':d['regions'][0]['parent_id']='u_region_a'
                with self.assertRaises(ValueError):compile_global_spatial(state,'左侧区域',d)

    def test_conflict_reported_without_silent_relayout(self):
        state,d=self.fixture();state['elements'].append(dict(copy.deepcopy(state['elements'][0]),id='w'))
        d['placements'].append(dict(d['placements'][0],id='w'))
        out=compile_global_spatial(state,'左侧区域',d)
        self.assertEqual(out['page_meta']['layout_solver']['sibling_conflicts'],[['v','w']])


if __name__=='__main__':unittest.main()
