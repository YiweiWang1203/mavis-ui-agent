import copy
import unittest
from tests.test_projection_flow_layout import ProjectionFlowTests as Fixtures
from src.utils.projection_flow_layout import compile_projection_flow
from src.agents.frozen_region_planner import frozen_inventory
from src.renderers.controlled_components import render_controlled_components

# Do not export imported TestCase as a second runnable suite.
fixture = Fixtures().fixture
del Fixtures


class ButtonFootprintTests(unittest.TestCase):
    def compare(self, caption='返回'):
        state, vision, kw = fixture()
        state['elements'][0]['type'] = 'button'
        state['elements'][0]['text'] = caption
        a = compile_projection_flow(state, vision, **kw)
        b = compile_projection_flow(state, vision, button_footprints=True, **kw)
        return state, a, b

    def test_regions_and_semantics_preserved_nonbuttons_unchanged(self):
        state, a, b = self.compare()
        self.assertEqual(frozen_inventory(a), frozen_inventory(b))
        self.assertEqual(a['page_meta']['symbolic_flow'], b['page_meta']['symbolic_flow'])
        self.assertEqual(a['elements'][1], b['elements'][1])
        self.assertNotIn('button_footprints', a['page_meta'])
        self.assertNotIn('button_footprints', state.get('page_meta', {}))

    def test_atomic_button_stays_in_own_region_with_fixed_height(self):
        _, a, b = self.compare()
        outer = a['elements'][0]['spatial_info']['bbox']
        inner = b['elements'][0]['spatial_info']['bbox']
        self.assertTrue(outer[0] <= inner[0] < inner[2] <= outer[2])
        self.assertTrue(outer[1] <= inner[1] < inner[3] <= outer[3])
        self.assertLessEqual(inner[3]-inner[1], 48)
        self.assertGreaterEqual(inner[3]-inner[1], 24)
        self.assertAlmostEqual(outer[0]+outer[2], inner[0]+inner[2], delta=1)
        self.assertIn('<button', render_controlled_components(b))

    def test_long_caption_limited_to_allocation_not_spilling(self):
        _, a, b = self.compare('長'*100)
        outer=a['elements'][0]['spatial_info']['bbox']; inner=b['elements'][0]['spatial_info']['bbox']
        self.assertEqual(outer[0], inner[0]); self.assertEqual(outer[2], inner[2])
        self.assertTrue(b['page_meta']['button_footprints']['placements'][0]['caption_width_is_estimate'])

    def test_nonbutton_inventory_has_no_footprint_changes(self):
        state, vision, kw = fixture()
        for e in state['elements']: e['type']='text'
        a=compile_projection_flow(state,vision,**kw)
        b=compile_projection_flow(state,vision,button_footprints=True,**kw)
        self.assertEqual(a['elements'],b['elements'])
        self.assertEqual(b['page_meta']['button_footprints']['placements'],[])
