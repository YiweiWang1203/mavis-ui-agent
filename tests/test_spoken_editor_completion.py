import copy
import unittest
from src.agents.spoken_editor_completion import compile_spoken_editors
from src.renderers.controlled_components import render_controlled_components


class SpokenEditorTests(unittest.TestCase):
    intent='输入框可以输入文字。'
    def fixture(self):
        s={'page_meta':{'viewport':{'width':1440,'height':900},'layout_solver':{'version':'hierarchy-v1'}},'elements':[{'id':'v1','type':'button','text':'send','parent_id':None,'spatial_info':{'bbox':[1000,700,1100,750]},'rpa_action':'click'}]}
        row={'requirement_id':'r1','status':'missing','existing_id':None,'observed_bbox':[.2,.6,.8,.8],'target_bbox':[400,800,1200,850]}
        return s,{'slots':[row]}
    def run_compile(self,s,d):return compile_spoken_editors(s,self.intent,d,frame_sha256='a'*64)
    def test_add_source_backed_editor_preserves_old_fields_and_separate_spaces(self):
        s,d=self.fixture();old=copy.deepcopy(s);r=self.run_compile(s,d)
        self.assertEqual(s,old);self.assertEqual(r['elements'][:-1],s['elements']);e=r['elements'][-1]
        self.assertIsNone(e['vision_id']);self.assertEqual(e['spoken_evidence']['quote'],self.intent)
        self.assertNotEqual(e['observation_geometry'][0]['bbox'],e['spatial_info']['bbox'])
        self.assertIn('<input ',render_controlled_components(r))
    def test_overlap_bounds_small_nonfinite_rejected(self):
        for box in ([900,700,1200,800],[-1,800,1200,850],[400,800,420,850],[400,800,float('nan'),850]):
            s,d=self.fixture();d['slots'][0]['target_bbox']=box
            with self.subTest(box=box),self.assertRaises(ValueError):self.run_compile(s,d)
    def test_duplicate_missing_unknown_or_free_quote_rejected(self):
        for mode in ['duplicate','omitted','unknown','quote']:
            s,d=self.fixture()
            if mode=='duplicate':d['slots']*=2
            if mode=='omitted':d['slots']=[]
            if mode=='unknown':d['slots'][0]['requirement_id']='fake'
            if mode=='quote':d['slots'][0]['quote']='fabricated'
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.run_compile(s,d)
    def test_existing_native_blocks_duplicate_and_unresolved_does_not_create(self):
        s,d=self.fixture();s['elements'][0]['type']='input'
        with self.assertRaises(ValueError):self.run_compile(s,d)
        s,d=self.fixture();d['slots'][0].update(status='unresolved',observed_bbox=None,target_bbox=None)
        self.assertEqual(len(self.run_compile(s,d)['elements']),1)
