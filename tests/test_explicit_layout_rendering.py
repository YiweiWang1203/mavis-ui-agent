"""Integration gate from actual regional compiler to unchanged controlled HTML."""
import copy
import unittest

from src.utils.region_layout_contract import compile_region_structure
from src.renderers.controlled_components import render_controlled_components
from src.utils.placement_contract import compile_placement_contract


class ExplicitLayoutRenderingTests(unittest.TestCase):
    def state(self):
        from tests.test_region_layout_contract import fixture
        state, vision, frame, viewport, plan = fixture()
        return compile_region_structure(state, vision, frame=frame, viewport=viewport, region_plan=plan)

    def test_real_compiler_to_renderer_preserves_pixels_semantics_and_input(self):
        state = self.state(); before = copy.deepcopy(state)
        self.assertNotIn('layout_solver', state['page_meta'])
        manifest = compile_placement_contract(state)
        self.assertEqual(manifest['coordinate_space'], 'viewport_px')
        self.assertIn('left:325px;top:656px;width:600px;height:96px;', manifest['placements'][1]['style'])
        html = render_controlled_components(state)
        self.assertIn('<input id="v2" data-parent-id="v1"', html)
        self.assertIn('top:656px;', html)
        self.assertNotIn('top:1296px;', html)
        self.assertEqual(state, before)

    def test_rejects_wrong_units_viewport_counts_provenance_and_boxes(self):
        mutations = [
            lambda s:s['page_meta']['coordinate_contract'].update(version='fake'),
            lambda s:s['page_meta']['coordinate_contract'].update(status='unvalidated'),
            lambda s:s['page_meta']['coordinate_contract'].update(placement_count=0),
            lambda s:s['page_meta']['coordinate_contract']['viewport'].update(width=5),
            lambda s:s['page_meta']['coordinate_contract']['frame'].update(sha256='not-a-hash'),
            lambda s:s['elements'][1]['spatial_info'].update(coordinate_space='image_norm'),
            lambda s:s['elements'][1]['spatial_info'].update(viewport_id='other'),
            lambda s:s['elements'][1]['spatial_info'].update(source='legacy'),
            lambda s:s['elements'][1]['spatial_info']['derivation'].update(evidence_refs=[]),
            lambda s:s['elements'][1]['spatial_info'].update(bbox=[0,0,1001,800]),
            lambda s:s['elements'][1]['spatial_info'].update(bbox=[0,0,float('nan'),800]),
            lambda s:s['elements'][1].update(id='v1'),
        ]
        for mutate in mutations:
            state = self.state(); mutate(state)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                render_controlled_components(state)

    def test_legacy_output_and_component_escaping_remain_unchanged(self):
        from tests.test_placement_contract import PlacementTests
        legacy = PlacementTests().state()
        self.assertEqual(compile_placement_contract(legacy)['coordinate_space'], 'page_global')
        html = render_controlled_components(legacy)
        self.assertIn('top:568px;', html)
        state = self.state(); state['elements'][1]['text'] = '<script>bad()</script>'
        html = render_controlled_components(state)
        self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', html)
        self.assertNotIn('<script>bad()</script>', html)


if __name__ == '__main__':
    unittest.main()
