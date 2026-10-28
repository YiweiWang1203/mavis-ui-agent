import copy
import unittest
from tests.test_relative_region_layout import node
from src.utils.relative_region_layout import compile_observed_extent_layout


class ObservedExtentTests(unittest.TestCase):
    def setUp(self):
        self.state={'page_meta':{'viewport':{'width':400,'height':800}},'elements':[
            {'id':'a','type':'image','spatial_info':{'bbox':[20,20,380,420]}},
            {'id':'b','type':'button','spatial_info':{'bbox':[20,440,180,480]}},
            {'id':'c','type':'button','spatial_info':{'bbox':[180,440,380,480]}}]}
        self.tree=node('page',[node('a'),node('layout_actions',[node('b'),node('c')],'row',1,'actions below')],'column')

    def test_replaces_arbitrary_weight_with_observed_extent_without_mutation(self):
        before=copy.deepcopy((self.state,self.tree))
        r=compile_observed_extent_layout(self.state,'actions below',self.tree)
        a,b,c=r['elements']
        self.assertAlmostEqual(a['spatial_info']['bbox'][3]/800,400/440)
        self.assertAlmostEqual(b['spatial_info']['bbox'][2]/400,160/360)
        self.assertEqual((self.state,self.tree),before)
        self.assertEqual([e['id'] for e in r['elements']],['a','b','c'])
        self.assertEqual(len(r['page_meta']['observed_extent_weights']['evidence']),2)

    def test_invalid_plan_not_rescued(self):
        t=copy.deepcopy(self.tree);t['children'][0]['weight']=0
        with self.assertRaises(ValueError):compile_observed_extent_layout(self.state,'actions below',t)

    def test_invalid_source_geometry_rejected_not_clamped(self):
        for box in [[0,0,0,20],[-1,0,40,20],[0,0,401,20],[0,0,float('nan'),20]]:
            s=copy.deepcopy(self.state);s['elements'][0]['spatial_info']['bbox']=box
            with self.assertRaises(ValueError):compile_observed_extent_layout(s,'actions below',self.tree)


if __name__=='__main__':unittest.main()
