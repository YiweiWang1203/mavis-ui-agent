import copy
import unittest
from tests import test_symbolic_flow_layout as fixtures
from src.utils.projection_flow_layout import projection_tree, compile_projection_flow
from src.agents.frozen_region_planner import frozen_inventory


class ProjectionFlowTests(unittest.TestCase):
    def fixture(self):
        _,state,vision,kw=fixtures.SymbolicFlowTests().fixture()
        vision['elements'][0]['bbox']=dict(x_min=.1,y_min=.1,x_max=.3,y_max=.8)
        vision['elements'][1]['bbox']=dict(x_min=.5,y_min=.1,x_max=.9,y_max=.8)
        return state,vision,kw

    def test_cut_uses_source_order_not_inventory_order(self):
        state,vision,kw=self.fixture(); state['elements'].reverse()
        tree,ds=projection_tree(state,vision)
        self.assertEqual(tree['root']['axis'],'row')
        self.assertEqual([n['entity_id'] for n in tree['root']['children']],['v1','v2'])
        self.assertEqual(ds[0]['kind'],'observed_non_crossing_cut')
        result=compile_projection_flow(state,vision,**kw)
        self.assertEqual(frozen_inventory(result),frozen_inventory(state))
        self.assertEqual(result['page_meta']['projection_flow']['ambiguous_groups'],0)

    def test_similarity_transform_does_not_change_tree(self):
        state,vision,_=self.fixture();first,_=projection_tree(state,vision)
        for e in vision['elements']:
            e['bbox']={k:v*2+3 for k,v in e['bbox'].items()}
        second,_=projection_tree(state,vision)
        self.assertEqual(first,second)

    def test_overlapping_sources_are_explicitly_ambiguous_not_semantic_success(self):
        state,vision,kw=self.fixture();vision['elements'][1]['bbox']=copy.deepcopy(vision['elements'][0]['bbox'])
        result=compile_projection_flow(state,vision,**kw)
        self.assertEqual(result['page_meta']['projection_flow']['ambiguous_groups'],1)
        self.assertFalse(result['page_meta']['projection_flow']['semantic_coverage_evaluated'])

    def test_missing_source_and_duplicate_identity_are_not_guessed(self):
        state,vision,_=self.fixture()
        vision['elements'].pop()
        with self.assertRaises(ValueError):projection_tree(state,vision)
        state,vision,_=self.fixture();state['elements'].append(copy.deepcopy(state['elements'][0]))
        with self.assertRaises(ValueError):projection_tree(state,vision)
