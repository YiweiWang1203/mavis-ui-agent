import copy
import unittest
from src.utils.relative_region_layout import compile_relative_layout
from src.renderers.controlled_components import render_controlled_components


def node(key,children=None,axis=None,weight=1,quote=None):
    return {'id':key,'children':children or [],'axis':axis,'weight':weight,'quote':quote}


class RelativeRegionTests(unittest.TestCase):
    def setUp(self):
        self.state={'page_meta':{'viewport':{'width':400,'height':800},'locale':'zh-CN','layout_solver':{'version':'hierarchy-v1'}},'elements':[
            {'id':'a','type':'image','text':'map','spatial_info':{'bbox':[10,10,20,20]}},
            {'id':'b','type':'card','text':'','spatial_info':{'bbox':[40,40,80,80]}},
            {'id':'c','type':'button','text':'First','spatial_info':{'bbox':[40,40,60,60]}},
            {'id':'d','type':'button','text':'Second','spatial_info':{'bbox':[40,40,60,60]}}]}
        self.tree=node('page',[node('a',weight=3),node('b',[node('c'),node('d')],'row',1,'two buttons in card')],'column')
        self.transcript='Map above; two buttons in card.'

    def test_partition_identity_immutability_and_render(self):
        old=copy.deepcopy(self.state);r=compile_relative_layout(self.state,self.transcript,self.tree)
        self.assertEqual(self.state,old)
        self.assertEqual([(e['id'],e['type'],e['text']) for e in r['elements']],[(e['id'],e['type'],e['text']) for e in old['elements']])
        by={e['id']:e for e in r['elements']}
        self.assertEqual(by['a']['spatial_info']['bbox'],[0,0,400,600])
        self.assertEqual(by['c']['spatial_info']['bbox'],[0,600,200,800])
        self.assertEqual(by['d']['parent_id'],'b')
        self.assertIn('data-parent-id="b"',render_controlled_components(r))

    def test_missing_duplicate_unknown_objects_rejected(self):
        for key in ['missing','c']:
            t=copy.deepcopy(self.tree);t['children'][1]['children'][1]['id']=key
            with self.assertRaises(ValueError):compile_relative_layout(self.state,self.transcript,t)
        t=copy.deepcopy(self.tree);t['children'][1]['children'].pop()
        with self.assertRaises(ValueError):compile_relative_layout(self.state,self.transcript,t)

    def test_button_not_promoted_to_parent(self):
        t=copy.deepcopy(self.tree);t['children'][1]['id']='c'
        with self.assertRaisesRegex(ValueError,'cannot become a container'):compile_relative_layout(self.state,self.transcript,t)

    def test_layout_only_groups_do_not_create_ui_objects(self):
        t=node('page',[self.tree],'column');t['children'][0]['id']='layout_body';t['children'][0]['quote']='Map above'
        r=compile_relative_layout(self.state,self.transcript,t)
        self.assertEqual(len(r['elements']),4)
        self.assertTrue(r['page_meta']['relative_region_layout']['groups'][0]['layout_only'])

    def test_unquoted_group_and_invalid_weight_rejected(self):
        for quote in ['invented','',None]:
            t=copy.deepcopy(self.tree);t['children'][1]['quote']=quote
            with self.assertRaises(ValueError):compile_relative_layout(self.state,self.transcript,t)
        for value in [0,-1,float('nan'),True,101]:
            t=copy.deepcopy(self.tree);t['children'][0]['weight']=value
            with self.assertRaises(ValueError):compile_relative_layout(self.state,self.transcript,t)


if __name__=='__main__':unittest.main()
