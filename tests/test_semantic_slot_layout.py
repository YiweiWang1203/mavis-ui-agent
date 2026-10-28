import copy
import unittest
from src.utils.semantic_slot_layout import compile_semantic_slots


class SemanticSlotTests(unittest.TestCase):
    def setUp(self):
        self.state={'page_meta':{'viewport':{'width':400,'height':800}},'elements':[
            {'id':'nav','type':'navigation_bar','spatial_info':{'bbox':[0,700,300,760]}},
            {'id':'a','type':'button','text':'A','spatial_info':{'bbox':[0,700,100,760]}},
            {'id':'b','type':'button','text':'B','spatial_info':{'bbox':[100,700,200,760]}},
            {'id':'c','type':'button','text':'C','spatial_info':{'bbox':[200,700,300,760]}},
            {'id':'line','type':'divider','spatial_info':{'bbox':[0,20,400,22]}}]}
        self.groups=[{'id':'nav','children':['a','c','b'],'axis':'row','quote':'A C B in navigation'}]
        self.transcript='A C B in navigation.'

    def test_complete_inventory_kept_with_partial_order_assignments(self):
        old=copy.deepcopy(self.state);r=compile_semantic_slots(self.state,self.transcript,self.groups)
        self.assertEqual(self.state,old);by={e['id']:e for e in r['elements']}
        self.assertEqual(by['line'],old['elements'][-1]|{'children_ids':[]})
        self.assertEqual(by['c']['spatial_info']['bbox'],[100,700,200,760])
        self.assertEqual(by['b']['parent_id'],'nav')
        self.assertEqual(len(by),5)

    def test_membership_expands_existing_region_without_moving_children(self):
        s=copy.deepcopy(self.state);s['elements'][0]['spatial_info']['bbox']=[0,700,150,750]
        g=copy.deepcopy(self.groups);g[0]['axis']=None
        r=compile_semantic_slots(s,self.transcript,g)
        self.assertEqual(r['elements'][0]['spatial_info']['bbox'],[0,700,300,760])
        self.assertEqual(r['elements'][3]['spatial_info']['bbox'],[200,700,300,760])

    def test_bad_parent_unknown_and_quote_fail_atomically(self):
        for key in ['a','unknown']:
            g=copy.deepcopy(self.groups);g[0]['id']=key
            with self.assertRaises(ValueError):compile_semantic_slots(self.state,self.transcript,g)
        g=copy.deepcopy(self.groups);g[0]['quote']='fabricated'
        with self.assertRaises(ValueError):compile_semantic_slots(self.state,self.transcript,g)

    def test_multirow_not_flattened_and_duplicate_child_not_accepted(self):
        s=copy.deepcopy(self.state);s['elements'][3]['spatial_info']['bbox']=[200,500,300,560]
        with self.assertRaisesRegex(ValueError,'single observed'):compile_semantic_slots(s,self.transcript,self.groups)
        g=copy.deepcopy(self.groups);g.append({'id':'layout_extra','children':['a'],'axis':None,'quote':self.groups[0]['quote']})
        with self.assertRaises(ValueError):compile_semantic_slots(self.state,self.transcript,g)

    def test_empty_plan_preserves_objects_not_coverage(self):
        r=compile_semantic_slots(self.state,self.transcript,[])
        self.assertEqual(len(r['elements']),5)
        self.assertEqual(r['page_meta']['semantic_slot_layout']['assigned_ids'],[])


if __name__=='__main__':unittest.main()
