"""Synthetic hierarchical geometry and conflict invariants, not case answers."""
import copy
import unittest

from src.utils.region_layout_contract import compile_region_structure


def fixture():
    from tests.test_coordinate_contract import fixture as coordinates
    state, vision, coordinates = coordinates()
    state['page_meta']['viewport'] = {'width': 1000, 'height': 800}
    viewport = {'id': 'vp1', 'width': 1000, 'height': 800}
    plan = {'version': 'region-local-v1', 'root_region_id': 'canvas', 'regions': [], 'placements': []}
    for rid, parent, bbox in [('side', 'canvas', [0, 0, .25, 1]),
                              ('main', 'canvas', [.25, 0, 1, 1]),
                              ('editor', 'main', [0, .8, 1, 1])]:
        plan['regions'].append({'id': rid, 'parent_id': parent, 'coordinate_space': 'region_local',
            'bbox': bbox, 'proportion_basis': 'explicit_requirement',
            'evidence_refs': ['vision:v1'], 'reason': 'Synthetic declared region ratio'})
    for eid, region, bbox in [('v1', 'main', [0, 0, 1, 1]), ('v2', 'editor', [.1, .1, .9, .7])]:
        plan['placements'].append({'entity_id': eid, 'region_id': region,
            'coordinate_space': 'region_local', 'bbox': bbox,
            'evidence_refs': ['vision:' + eid], 'reason': 'Synthetic declared membership and placement'})
    return state, vision, coordinates['frame'], viewport, plan


def compile_fixture(values):
    state, vision, frame, viewport, plan = values
    return compile_region_structure(state, vision, frame=frame, viewport=viewport, region_plan=plan)


class RegionLayoutTests(unittest.TestCase):
    def test_nested_mapping_uses_regions_and_keeps_inputs_and_semantics(self):
        values = fixture()
        original = copy.deepcopy(values)
        compiled = compile_fixture(values)
        self.assertEqual(compiled['elements'][1]['spatial_info']['bbox'], [325, 656, 925, 752])
        self.assertEqual(compiled['elements'][1]['spatial_info']['derivation']['region_path'], ['canvas', 'main', 'editor'])
        self.assertEqual(compiled['elements'][1]['parent_id'], 'v1')
        self.assertEqual(compiled['elements'][1]['type'], 'input')
        self.assertEqual(compiled['page_meta']['region_layout']['conflicts'], [])
        self.assertEqual(values, original)

    def test_photo_shift_and_resolution_do_not_move_layout(self):
        values = fixture()
        original = compile_fixture(values)
        for observed in values[1]['elements']:
            observed['bbox']['x_min'] += .3
            observed['bbox']['x_max'] += .3
        values[2].update(width=1200, height=1800, id='frame_b', sha256='b' * 64)
        updated = compile_fixture(values)
        self.assertEqual([e['spatial_info'] for e in original['elements']],
                         [e['spatial_info'] for e in updated['elements']])
        self.assertNotEqual(original['elements'][0]['observation_geometry'], updated['elements'][0]['observation_geometry'])

    def test_mobile_target_is_explicit_and_rounding_only_at_final_output(self):
        values = fixture()
        values[0]['page_meta']['viewport'] = {'width': 375, 'height': 812}
        values[3].update(width=375, height=812)
        result = compile_fixture(values)
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'], [122, 666, 347, 763])

    def test_wrong_semantic_parent_is_reported_without_clamping_or_reparenting(self):
        values = fixture()
        values[4]['placements'][0]['region_id'] = 'side'
        result = compile_fixture(values)
        child = result['elements'][1]
        self.assertEqual(child['spatial_info']['bbox'], [325, 656, 925, 752])
        self.assertEqual(child['parent_id'], 'v1')
        conflicts = result['page_meta']['region_layout']['conflicts']
        wrong = next(c for c in conflicts if c['kind'] == 'semantic_parent_layout_conflict')
        self.assertEqual(wrong['outside_parent_sides'], ['right'])

    def test_region_overlap_reported_without_moving_boxes(self):
        values = fixture()
        values[4]['regions'][0]['bbox'][2] = .4
        result = compile_fixture(values)
        conflicts = result['page_meta']['region_layout']['conflicts']
        self.assertTrue(any(c['kind'] == 'region_extent_overlap' for c in conflicts))
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'], [325, 656, 925, 752])

    def test_entity_overlap_and_small_controls_are_separate_diagnostics(self):
        values = fixture()
        state, vision, _, _, plan = values
        state['elements'].append({'id': 'u_more', 'origin': 'spoken', 'type': 'button', 'parent_id': None})
        plan['placements'].append({'entity_id': 'u_more', 'region_id': 'editor',
            'coordinate_space': 'region_local', 'bbox': [.1, .1, .11, .2],
            'evidence_refs': ['spoken_intent:u_more'], 'reason': 'Synthetic tiny overlapping action'})
        result = compile_fixture(values)
        conflicts = result['page_meta']['region_layout']['conflicts']
        self.assertTrue(any(c['kind'] == 'insufficient_control_space' for c in conflicts))
        self.assertTrue(any(c['kind'] == 'entity_extent_overlap' and c['entities'] == ['v2', 'u_more'] for c in conflicts))

    def test_default_ratio_is_explicit_unverified_not_high_fidelity(self):
        values = fixture()
        values[4]['regions'][1]['proportion_basis'] = 'default'
        audit = compile_fixture(values)['page_meta']['region_layout']
        self.assertEqual(audit['status'], 'compiled_default_proportions')
        self.assertEqual(audit['default_proportions'][0]['region_id'], 'main')
        self.assertFalse(audit['semantic_correctness_evaluated'])

    def test_missing_or_invalid_region_decisions_never_repaired(self):
        changes = [
            lambda p: p['regions'][1].update(parent_id='unknown'),
            lambda p: p['regions'][1].update(parent_id='editor'),
            lambda p: p['regions'][1].update(coordinate_space='image_norm'),
            lambda p: p['regions'][1].update(bbox=[-.1, 0, 1, 1]),
            lambda p: p['regions'][1].update(bbox=[0, 0, float('inf'), 1]),
            lambda p: p['regions'][1].update(proportion_basis=None),
            lambda p: p['regions'][1].update(evidence_refs=['vision:not_observed']),
            lambda p: p['regions'].append(copy.deepcopy(p['regions'][1])),
            lambda p: p['placements'].pop(),
            lambda p: p['placements'][1].update(region_id='unknown'),
            lambda p: p['placements'][1].update(coordinate_space='viewport_px'),
            lambda p: p['placements'][1].update(bbox=[0, 0, .00001, 1]),
            lambda p: p['placements'].append(copy.deepcopy(p['placements'][1])),
            lambda p: p['placements'][1].update(reason=''),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                values = fixture()
                change(values[4])
                with self.assertRaises(ValueError):
                    compile_fixture(values)


if __name__ == '__main__':
    unittest.main()
