import copy
import unittest
from src.utils.requirement_recovery_guard import validate_requirement_recovery


class RecoveryGuardTests(unittest.TestCase):
    def fixture(self):
        a={'elements':[{'id':'v1','type':'text','text':'entry','spatial_info':{'bbox':[0,0,100,50]}}]}
        b=copy.deepcopy(a)
        b['elements'][0].update(type='input',semantic_type_evidence={'quote':'entry can type'})
        b['page_meta']={'spoken_input_evidence':{'accepted':[{'vision_id':'v1'}]}}
        return a,b

    def test_only_accepted_type_change(self):
        a,b=self.fixture()
        self.assertEqual(validate_requirement_recovery(a,b)['changed_ids'],['v1'])
        self.assertEqual(a['elements'][0]['type'],'text')

    def test_geometry_identity_text_parent_action_and_inventory_rejected(self):
        for field,value in [('id','v2'),('text','other'),('parent_id','new'),('rpa_action','send'),('spatial_info',{'bbox':[0,0,200,50]})]:
            a,b=self.fixture();b['elements'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_requirement_recovery(a,b)
        a,b=self.fixture();b['elements'].append(copy.deepcopy(b['elements'][0]))
        with self.assertRaises(ValueError):validate_requirement_recovery(a,b)

    def test_no_acceptance_rejected_and_unchanged_allowed(self):
        a,b=self.fixture();b['page_meta']={}
        with self.assertRaises(ValueError):validate_requirement_recovery(a,b)
        self.assertEqual(validate_requirement_recovery(a,copy.deepcopy(a))['changed_ids'],[])
