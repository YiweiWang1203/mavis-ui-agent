import copy
import unittest
from src.utils.parent_geometry_guard import reconcile_parent_geometry


def node(i, b, parent=None, kind='container', origin='spoken'):
    return dict(id=i,type=kind,origin=origin,parent_id=parent,text=i,
                spatial_info={'bbox':b},children_ids=[])


class ParentGeometryTests(unittest.TestCase):
    def state(self):
        return {'page_meta':{'viewport':{'width':1000,'height':800}},'elements':[
            node('page',[0,0,1000,800]), node('left',[0,0,200,800],'page'),
            node('right',[200,0,1000,800],'page'), node('editor',[200,600,1000,800],'right'),
            node('control',[300,650,400,700],'left','button','vision')]}

    def test_moves_only_parent_preserves_observations_and_input(self):
        s=self.state(); original=copy.deepcopy(s); r=reconcile_parent_geometry(s)
        self.assertEqual(s,original)
        self.assertEqual(r['elements'][-1]['parent_id'],'editor')
        for old,new in zip(s['elements'],r['elements']):
            for k in ('id','type','text','origin','spatial_info'):
                self.assertEqual(old[k],new[k])

    def test_valid_parent_kept_even_if_deeper_region_exists(self):
        s=self.state(); s['elements'][-1]['parent_id']='right'
        self.assertEqual(reconcile_parent_geometry(s)['page_meta']['parent_geometry_guard']['conflicts'],0)

    def test_equal_box_ambiguity_keeps_original(self):
        s=self.state();s['elements'].append(node('other',[200,600,1000,800],'right'))
        r=reconcile_parent_geometry(s)
        self.assertEqual(r['elements'][4]['parent_id'],'left')
        self.assertEqual(r['page_meta']['parent_geometry_guard']['unresolved'],1)

    def test_crossing_regions_are_ambiguous(self):
        s=self.state();s['elements'].append(node('cross',[250,550,900,750],'right'))
        self.assertEqual(reconcile_parent_geometry(s)['elements'][4]['parent_id'],'left')

    def test_no_region_does_not_attach_to_page(self):
        s=self.state();s['elements']=s['elements'][:2]+[s['elements'][-1]]
        self.assertEqual(reconcile_parent_geometry(s)['elements'][-1]['parent_id'],'left')

    def test_spoken_objects_not_reinterpreted(self):
        s=self.state();s['elements'][-1]['origin']='spoken'
        self.assertEqual(reconcile_parent_geometry(s)['elements'][-1]['parent_id'],'left')

    def test_original_cycle_rejected(self):
        s=self.state();s['elements'][1]['parent_id']='left'
        with self.assertRaises(ValueError): reconcile_parent_geometry(s)

    def test_out_of_canvas_not_clamped(self):
        s=self.state();s['elements'][-1]['spatial_info']['bbox']=[900,650,1100,700]
        with self.assertRaises(ValueError): reconcile_parent_geometry(s)

if __name__=='__main__':unittest.main()
