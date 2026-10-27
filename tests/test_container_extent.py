import copy
import os
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.utils.hierarchy_contract import build_structure, solve_hierarchy
from tests.test_hierarchy_contract import fixture


class ContainerExtentTests(unittest.TestCase):
    def test_trace_input_hash_and_single_stage_required(self):
        from scripts.run_layout_extent_comparison import fresh_layout_input
        root=Path(__file__).resolve().parents[1]/'outputs/optimization_cycles'
        root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            shared=Path(folder);trace=shared/'pipeline_trace';trace.mkdir()
            raw=json.dumps({'inputs':{'ui_state':{'elements':[]}}}).encode()
            (trace/'input.json').write_bytes(raw)
            event={'stage':'architect.hierarchy_layout.input','file':'input.json','sha256':hashlib.sha256(raw).hexdigest()}
            (trace/'manifest.json').write_text(json.dumps({'events':[event]}),encoding='utf-8')
            self.assertEqual(fresh_layout_input(shared),{'elements':[]})
            (trace/'input.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):fresh_layout_input(shared)
            (trace/'manifest.json').write_text(json.dumps({'events':[event,event]}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'one current-run'):fresh_layout_input(shared)

    def state(self):
        s,v=fixture()
        v['elements'][0]['bbox'].update(x_max=.3)
        return build_structure(s,v)

    def test_narrow_parent_does_not_collapse_separate_children(self):
        state=self.state();original=copy.deepcopy(state)
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'baseline'}):baseline=solve_hierarchy(state)
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'container_extent_v1'}):result=solve_hierarchy(state)
        boxes={e['id']:e['spatial_info']['bbox'] for e in result['elements']}
        self.assertLessEqual(boxes['v2'][2],boxes['v3'][0])
        self.assertEqual(boxes['v3'],[240,680,320,760])
        self.assertEqual(result['elements'][0]['spatial_info']['evidence_bbox'],[0,640,120,800])
        self.assertEqual(state,original)
        self.assertTrue(baseline['page_meta']['layout_solver']['sibling_conflicts'])
        self.assertFalse(result['page_meta']['layout_solver']['sibling_conflicts'])

    def test_already_valid_geometry_is_preserved(self):
        s,v=fixture();state=build_structure(s,v)
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'container_extent_v1'}):result=solve_hierarchy(state)
        self.assertEqual([e['spatial_info']['bbox'] for e in result['elements']],[e['spatial_info']['bbox'] for e in state['elements']])

    def test_real_sibling_overlap_is_still_reported(self):
        state=self.state();state['elements'][2]['spatial_info']['bbox']=state['elements'][1]['spatial_info']['bbox'][:]
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'container_extent_v1'}):result=solve_hierarchy(state)
        self.assertEqual(result['page_meta']['layout_solver']['sibling_conflicts'],[['v2','v3']])

    def test_no_missing_parent_is_created(self):
        state=self.state();state['elements'][1]['parent_id']='missing'
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'container_extent_v1'}),self.assertRaises(KeyError):solve_hierarchy(state)

    def test_invalid_container_type_not_relaxed(self):
        state=self.state();state['elements'][0]['type']='button'
        with patch.dict(os.environ,{'UI_HIERARCHY_LAYOUT_MODE':'container_extent_v1'}),self.assertRaisesRegex(ValueError,'container'):solve_hierarchy(state)


if __name__=='__main__':unittest.main()
