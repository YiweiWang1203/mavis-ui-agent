import copy
import unittest
from src.utils.unique_requirement_binding import bind_unique_requirements
from src.utils.spoken_input_evidence import compile_spoken_inputs
from src.utils.requirement_recovery_guard import validate_requirement_recovery


class UniqueBindingTests(unittest.TestCase):
    intent='输入框可以输入文字。'
    def fixture(self):
        v={'elements':[{'id':'v1','type':'text','text':'输入框'}]}
        s={'page_meta':{},'elements':[{'id':'v1','type':'text','text':'输入框','spatial_info':{'bbox':[10,20,100,60]}}]}
        return s,v
    def test_unique_strict_conversion_without_mutation_or_geometry_edits(self):
        s,v=self.fixture();old=copy.deepcopy(s);r=compile_spoken_inputs(bind_unique_requirements(s,v,self.intent),v,self.intent)
        self.assertEqual(s,old);self.assertEqual(validate_requirement_recovery(s,r)['changed_ids'],['v1'])
        self.assertEqual(r['page_meta']['unique_requirement_binding']['additional_model_calls'],0)
    def test_missing_multiple_and_duplicate_labels_do_not_select_best(self):
        for mode in ['missing','multiple','duplicate']:
            s,v=self.fixture()
            if mode=='missing':v['elements'][0]['text']='conversation'
            else:
                second={'id':'v2','type':'text','text':'输入' if mode=='multiple' else '输入框'}
                v['elements'].append(second);s['elements'].append(copy.deepcopy(second))
            r=bind_unique_requirements(s,v,self.intent)
            self.assertEqual(r['page_meta']['input_requirement_binding']['bound_count'],0)
            self.assertEqual(r['page_meta']['input_requirement_binding']['unresolved_count'],1)
    def test_negative_and_type_disagreement_keep_existing_compiler_rejections(self):
        s,v=self.fixture();r=bind_unique_requirements(s,v,'输入框不能输入文字。')
        self.assertEqual(r['page_meta']['input_requirement_binding']['eligible_count'],0)
        s['elements'][0]['type']='button';r=bind_unique_requirements(s,v,self.intent)
        self.assertEqual(r['page_meta']['input_requirement_binding']['unresolved'][0]['reason'],'source_architect_type_disagreement')
