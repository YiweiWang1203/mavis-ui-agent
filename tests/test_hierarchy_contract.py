import copy
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from src.utils.hierarchy_contract import build_structure,solve_hierarchy,contains


def visual(eid,kind,b):
    return {'id':eid,'type':kind,'bbox':dict(zip(('x_min','y_min','x_max','y_max'),b))}


def fixture():
    vision={'elements':[visual('v1','navigation',[0,.8,1,1]),visual('v2','button',[.1,.85,.3,.95]),visual('v3','button',[.6,.85,.8,.95])]}
    state={'page_meta':{'viewport':{'width':400,'height':800}},'elements':[
        {'id':'area','vision_id':'v1','type':'navigation','parent_id':None},
        {'id':'left','vision_id':'v2','type':'button','parent_id':'area'},
        {'id':'right','vision_id':'v3','type':'button','parent_id':'area'}]}
    return state,vision


class HierarchyTests(unittest.TestCase):
    def test_explicit_sources_aliases_and_containment_no_global_row_pushing(self):
        state,vision=fixture();original=copy.deepcopy((state,vision))
        result=solve_hierarchy(build_structure(state,vision));items={e['id']:e for e in result['elements']}
        self.assertEqual(len(items),3);self.assertEqual(items['v2']['parent_id'],'v1')
        self.assertEqual(items['v1']['children_ids'],['v2','v3'])
        self.assertTrue(contains(items['v1']['spatial_info']['bbox'],items['v2']['spatial_info']['bbox']))
        self.assertEqual(items['v2']['spatial_info']['bbox'],[40,680,120,760])
        self.assertEqual(result['page_meta']['layout_solver']['sibling_conflicts'],[])
        self.assertEqual((state,vision),original)

    def test_candidate_is_on_actual_architect_generation_path(self):
        from src.agents import ui_architect
        state,vision=fixture();requests=[]
        def create(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(state)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            result=ui_architect.generate_ui_state('A toolbar with controls inside',vision)
        self.assertEqual(result['page_meta']['layout_solver']['version'],'hierarchy-v1')
        self.assertIn('parent_id',requests[0]['messages'][0]['content'])
        self.assertEqual(len(requests),1)

    def test_reused_visual_source_rejected(self):
        state,vision=fixture();state['elements'][2]['vision_id']='v2'
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_unknown_source_rejected(self):
        state,vision=fixture();state['elements'][1]['vision_id']='fake'
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_unknown_parent_rejected(self):
        state,vision=fixture();state['elements'][1]['parent_id']='fake'
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_noncontainer_parent_rejected(self):
        state,vision=fixture();state['elements'][1]['parent_id']='right'
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_cycle_rejected(self):
        state,vision=fixture();state['elements'][0]['parent_id']='area'
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_missing_visual_object_backfilled_once(self):
        state,vision=fixture();state['elements'].pop()
        result=build_structure(state,vision)
        self.assertEqual(len(result['elements']),3)
        self.assertEqual(result['page_meta']['structure_contract']['fallback_sources'],1)

    def test_additional_spoken_object_retained(self):
        state,vision=fixture();state['elements'].append({'id':'u_extra','vision_id':None,'origin':'spoken','type':'text','parent_id':None,'spatial_info':{'bbox':[20,20,100,60]}})
        self.assertEqual(len(build_structure(state,vision)['elements']),4)

    def test_unreferenced_visual_copy_not_accepted_as_new_object(self):
        state,vision=fixture();state['elements'][1].pop('vision_id')
        with self.assertRaises(ValueError):build_structure(state,vision)

    def test_child_outside_parent_fits_without_becoming_one_pixel(self):
        state,vision=fixture();vision['elements'][1]['bbox']=dict(zip(('x_min','y_min','x_max','y_max'),[.1,.72,.3,.82]))
        result=solve_hierarchy(build_structure(state,vision));child=result['elements'][1]
        self.assertEqual(child['spatial_info']['bbox'],[40,640,120,720])
        self.assertEqual(child['spatial_info']['evidence_bbox'],[40,576,120,656])

    def test_sibling_overlap_reported_without_corrupting_geometry(self):
        state,vision=fixture();vision['elements'][2]['bbox']=copy.deepcopy(vision['elements'][1]['bbox'])
        result=solve_hierarchy(build_structure(state,vision))
        self.assertEqual(result['page_meta']['layout_solver']['sibling_conflicts'],[['v2','v3']])
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'],result['elements'][2]['spatial_info']['bbox'])

    def test_impossible_small_control_fails_instead_of_hidden_one_pixel_strip(self):
        state,vision=fixture();vision['elements'][1]['bbox']=dict(zip(('x_min','y_min','x_max','y_max'),[.1,.85,.101,.95]))
        with self.assertRaises(ValueError):solve_hierarchy(build_structure(state,vision))


if __name__=='__main__':unittest.main()
