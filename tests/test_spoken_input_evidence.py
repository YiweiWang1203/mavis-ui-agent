import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.utils.spoken_input_evidence import compile_spoken_inputs
from src.agents import ui_architect
from src.renderers.controlled_components import render_controlled_components


class SpokenInputTests(unittest.TestCase):
    quote='输入框是可以输入文字的'
    def fixture(self):
        vision={'elements':[{'id':'entry','type':'text','text':'输入框','bbox':{'x_min':.1,'y_min':.7,'x_max':.8,'y_max':.8}}]}
        state={'page_meta':{'viewport':{'width':1440,'height':900}},'relationships':[],
            'relation_evidence_sources':[{'source':'architect','relationships':[]},{'source':'specialist','relationships':[]}],
            'elements':[{'id':'entry','vision_id':'entry','type':'text','text':'输入框','parent_id':None,'rpa_action':None}],
            'semantic_input_overrides':[{'vision_id':'entry','target_type':'input','evidence_quote':self.quote}]}
        return state,vision

    def test_bounded_source_changes_only_type_and_attaches_evidence(self):
        state,vision=self.fixture();original=copy.deepcopy(state)
        output=compile_spoken_inputs(state,vision,self.quote)
        self.assertEqual(state,original)
        self.assertEqual(output['elements'][0]['type'],'input')
        self.assertEqual(output['elements'][0]['id'],'entry')
        self.assertEqual(output['page_meta']['spoken_input_evidence']['accepted_count'],1)
        for k,v in original['elements'][0].items():
            if k!='type':self.assertEqual(output['elements'][0][k],v)

    def test_quote_must_be_original_and_support_editing(self):
        for quote,intent in [('fabricated',self.quote),('输入框',self.quote),('输入框不能输入文字','输入框不能输入文字')]:
            state,vision=self.fixture();state['semantic_input_overrides'][0]['evidence_quote']=quote
            output=compile_spoken_inputs(state,vision,intent)
            self.assertEqual(output['elements'][0]['type'],'text')
            self.assertEqual(output['page_meta']['spoken_input_evidence']['unresolved_count'],1)

    def test_cannot_coerce_button_or_create_unknown_input(self):
        state,vision=self.fixture();state['elements'][0]['type']='button'
        self.assertEqual(compile_spoken_inputs(state,vision,self.quote)['elements'][0]['type'],'button')
        state['semantic_input_overrides'][0]['vision_id']='missing'
        with self.assertRaisesRegex(ValueError,'Unknown'):compile_spoken_inputs(state,vision,self.quote)

    def test_same_visible_label_is_ambiguous(self):
        state,vision=self.fixture();other=copy.deepcopy(vision['elements'][0]);other['id']='second';vision['elements'].append(other)
        output=compile_spoken_inputs(state,vision,self.quote)
        self.assertEqual(output['page_meta']['spoken_input_evidence']['unresolved'][0]['reason'],'ambiguous_literal_label')

    def test_extra_geometry_fields_and_duplicate_proposals_rejected(self):
        state,vision=self.fixture();state['semantic_input_overrides'][0]['bbox']=[0,0,1,1]
        with self.assertRaises(ValueError):compile_spoken_inputs(state,vision,self.quote)
        state,vision=self.fixture();state['semantic_input_overrides']*=2
        with self.assertRaisesRegex(ValueError,'repeated'):compile_spoken_inputs(state,vision,self.quote)

    def test_fresh_state_finalizer_renders_native_input_opt_in_only(self):
        state,vision=self.fixture()
        with patch.dict(os.environ,{'UI_SEMANTIC_TYPE_MODE':'declare_spoken_input_v1','UI_RELATION_AGGREGATION_MODE':'validated_union_v1'}):
            baseline=ui_architect.finalize_ui_state(state,self.quote,vision,'hierarchy_registry_image_v1')
        with patch.dict(os.environ,{'UI_SEMANTIC_TYPE_MODE':'spoken_input_v1','UI_RELATION_AGGREGATION_MODE':'validated_union_v1'}):
            candidate=ui_architect.finalize_ui_state(state,self.quote,vision,'hierarchy_registry_image_v1')
        self.assertNotIn('<input ',render_controlled_components(baseline))
        self.assertIn('<input ',render_controlled_components(candidate))
        self.assertEqual(baseline['elements'][0]['spatial_info'],candidate['elements'][0]['spatial_info'])

    def test_generation_declares_in_same_request_and_off_is_unchanged(self):
        state,vision=self.fixture();seen=[]
        def create(**kwargs):
            seen.append(kwargs);return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(state)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(ui_architect,'_get_openai_client',return_value=client),patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_registry_inline_v1','UI_RELATION_SPECIALIST_MODE':'off','UI_SEMANTIC_TYPE_MODE':'declare_spoken_input_v1','UI_RELATION_AGGREGATION_MODE':'validated_union_v1'}):
            result=ui_architect.generate_ui_state(self.quote,vision)
        self.assertEqual(len(seen),1)
        self.assertIn('semantic_input_overrides',seen[0]['messages'][0]['content'])
        self.assertEqual(result['elements'][0]['type'],'text')


if __name__=='__main__':unittest.main()
