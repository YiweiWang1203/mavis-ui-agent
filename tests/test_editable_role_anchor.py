import copy
import unittest
from src.utils.editable_role_anchor import compile_unique_editable_role
from tests import test_projection_flow_layout as fixtures
from src.utils.projection_flow_layout import compile_projection_flow
from src.renderers.controlled_components import render_controlled_components


class EditableRoleTests(unittest.TestCase):
    def fixture(self):
        state,vision,kw=fixtures.ProjectionFlowTests().fixture()
        state['elements'][1]['type']='text';state['elements'][1]['text']='用户输入框'
        vision['elements'][1]['type']='text';vision['elements'][1]['text']='用户输入框'
        return state,vision,kw

    def test_unique_generic_owner_caption_and_verbatim_source(self):
        state,vision,_=self.fixture();before=copy.deepcopy(state)
        intent='下面是我的输入框，输入框可以输入文字。'
        result=compile_unique_editable_role(state,vision,intent)
        self.assertEqual(result['elements'][1]['type'],'input')
        self.assertEqual(result['page_meta']['editable_role_anchor']['accepted_type_changes'],1)
        self.assertEqual(result['elements'][1]['semantic_type_evidence']['quote'],intent)
        e=copy.deepcopy(result['elements'][1]);e['type']='text';e.pop('semantic_type_evidence')
        self.assertEqual(e,state['elements'][1]);self.assertEqual(state,before)

    def test_negative_specific_and_ambiguous_do_not_promote(self):
        for intent in ['输入框不可以输入文字。','密码输入框可以输入文字。','这个搜索输入框可以输入文字。']:
            state,vision,_=self.fixture();r=compile_unique_editable_role(state,vision,intent)
            self.assertEqual(r['elements'][1]['type'],'text')
            self.assertEqual(r['page_meta']['editable_role_anchor']['accepted_type_changes'],0)
        state,vision,_=self.fixture();vision['elements'][0]['text']='输入框'
        r=compile_unique_editable_role(state,vision,'输入框可以输入文字。')
        self.assertEqual(r['page_meta']['editable_role_anchor']['accepted_type_changes'],0)

    def test_native_confirmation_and_disagreement(self):
        state,vision,_=self.fixture();state['elements'][1]['type']='input';vision['elements'][1]['type']='input'
        r=compile_unique_editable_role(state,vision,'输入框可以输入文字。')
        self.assertEqual(r['page_meta']['editable_role_anchor']['native_confirmations'],1)
        self.assertEqual(r['page_meta']['editable_role_anchor']['accepted_type_changes'],0)
        vision['elements'][1]['type']='text'
        r=compile_unique_editable_role(state,vision,'输入框可以输入文字。')
        self.assertEqual(r['page_meta']['editable_role_anchor']['bound_slots'],0)

    def test_type_only_change_leaves_projection_boxes_identical(self):
        state,vision,kw=self.fixture();a=compile_projection_flow(state,vision,**kw)
        bound=compile_unique_editable_role(state,vision,'输入框可以输入文字。')
        b=compile_projection_flow(bound,vision,**kw)
        self.assertEqual([e['spatial_info']['bbox'] for e in a['elements']],[e['spatial_info']['bbox'] for e in b['elements']])
        self.assertNotIn('<input',render_controlled_components(a))
        self.assertIn('<input',render_controlled_components(b))
