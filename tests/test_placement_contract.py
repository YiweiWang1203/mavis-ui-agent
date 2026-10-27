import copy
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from src.utils.placement_contract import compile_placement_contract, compile_component_contract
from src.agents import coder

class PlacementTests(unittest.TestCase):
    def state(self):
        return {'page_meta':{'viewport':{'width':375,'height':812},'layout_solver':{'version':'hierarchy-v1'}},'elements':[
            {'id':'region','type':'card','spatial_info':{'bbox':[0,528,375,650]}},
            {'id':'child','parent_id':'region','type':'button','spatial_info':{'bbox':[0,568,188,609]}}]}
    def test_global_child_coordinate_is_not_added_to_parent(self):
        state=self.state();old=copy.deepcopy(state)
        manifest=compile_placement_contract(state)
        child=manifest['placements'][1]
        self.assertEqual(child['dom_parent'],'page-root')
        self.assertEqual(child['semantic_parent'],'region')
        self.assertIn('top:568px;',child['style'])
        self.assertEqual(state,old)
    def test_requires_valid_coordinate_contract(self):
        state=self.state();state['page_meta']['layout_solver']['version']='relation-v1'
        with self.assertRaises(ValueError):compile_placement_contract(state)
        for box in [[1,2,1,3],[0,0,float('nan'),5],[0,1,2]]:
            state=self.state();state['elements'][0]['spatial_info']['bbox']=box
            with self.assertRaises(ValueError):compile_placement_contract(state)
    def test_actual_coder_receives_compiled_contract_and_preserves_raw_response(self):
        seen=[];raw='<html><body>intentionally invalid placement</body></html>'
        def create(**kw):
            seen.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ,{'UI_RENDERER_MODE':'llm','UI_CODER_CONTRACT_MODE':'placement_v1','UI_INPUT_CONTRACT_MODE':'off'}),patch.object(coder,'_get_openai_client',return_value=client),patch.object(coder,'save_html_asset',return_value=None):
            result=coder.generate_frontend_code(self.state())
        prompt=seen[0]['messages'][0]['content']
        self.assertIn('COMPILED PLACEMENT CONTRACT',prompt)
        self.assertIn('top:568px;',prompt)
        self.assertEqual(result['code'],raw)
    def test_native_roles_do_not_make_passive_regions_interactive(self):
        state=self.state()
        state['elements'] += [
            {'id':'q','type':'search_bar','readonly':False,'spatial_info':{'bbox':[20,20,120,60]}},
            {'id':'photo','type':'image','spatial_info':{'bbox':[0,100,200,300]}},
            {'id':'secret','type':'password_input','readonly':True,'spatial_info':{'bbox':[0,60,200,100]}}]
        original=copy.deepcopy(state)
        specs={s['id']:s for s in compile_component_contract(state)}
        self.assertEqual(specs['q']['tag'],'input')
        self.assertEqual(specs['q']['input_type'],'search')
        self.assertFalse(specs['q']['disabled'])
        self.assertEqual(specs['child']['tag'],'button')
        self.assertIn('acknowledgement',specs['child']['feedback'])
        self.assertEqual(specs['photo']['feedback'],'none')
        self.assertTrue(specs['secret']['readonly'])
        self.assertEqual(state,original)
    def test_real_coder_adds_component_contract_without_repair(self):
        seen=[];raw='<html><div id="q"></div></html>'
        def create(**kw):
            seen.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ,{'UI_RENDERER_MODE':'llm','UI_CODER_CONTRACT_MODE':'typed_controls_v1','UI_INPUT_CONTRACT_MODE':'off'}),patch.object(coder,'_get_openai_client',return_value=client),patch.object(coder,'save_html_asset',return_value=None):
            result=coder.generate_frontend_code(self.state())
        self.assertIn('COMPILED PLACEMENT CONTRACT',seen[0]['messages'][0]['content'])
        self.assertIn('COMPILED COMPONENT CONTRACT',seen[0]['messages'][0]['content'])
        self.assertEqual(result['code'],raw)
if __name__=='__main__':unittest.main()
