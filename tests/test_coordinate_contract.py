"""Synthetic D1 invariants; these are not user-page effect scores."""
import copy
import unittest

from src.utils.hierarchy_contract import build_structure, solve_hierarchy


def fixture():
    vision = {'elements': [
        {'id': 'v1', 'type': 'container', 'bbox': dict(zip(
            ('x_min', 'y_min', 'x_max', 'y_max'), [.1, .2, .5, .9]))},
        {'id': 'v2', 'type': 'input', 'bbox': dict(zip(
            ('x_min', 'y_min', 'x_max', 'y_max'), [.2, .7, .4, .8]))},
    ]}
    state = {'page_meta': {'viewport': {'width': 1000, 'height': 700}}, 'elements': [
        {'id': 'area', 'vision_id': 'v1', 'type': 'container', 'parent_id': None},
        {'id': 'editor', 'vision_id': 'v2', 'type': 'input', 'parent_id': 'area'},
    ]}
    contract = {'version': 'evidence-layout-v1',
                'frame': {'id': 'f1', 'sha256': 'a' * 64, 'width': 600, 'height': 900},
                'viewport': {'id': 'vp1', 'width': 1000, 'height': 700}, 'placements': []}
    for eid, bbox in [('v1', [350, 0, 1000, 700]), ('v2', [400, 560, 930, 650])]:
        contract['placements'].append({'entity_id': eid, 'coordinate_space': 'viewport_px',
            'viewport_id': 'vp1', 'bbox': bbox,
            'derivation': {'kind': 'semantic_layout', 'evidence_refs': ['vision:' + eid],
                           'reason': 'Synthetic explicit region-local decision'}})
    return state, vision, contract


class CoordinateContractTests(unittest.TestCase):
    def test_background_shift_changes_observation_not_placement_or_identity(self):
        state, vision, contract = fixture()
        original = copy.deepcopy((state, vision, contract))
        first = build_structure(state, vision, coordinate_contract=contract)
        shifted = copy.deepcopy(vision)
        for entity in shifted['elements']:
            for key in ('x_min', 'x_max'):
                entity['bbox'][key] += .25
        second = build_structure(state, shifted, coordinate_contract=contract)
        self.assertEqual([e['spatial_info'] for e in first['elements']],
                         [e['spatial_info'] for e in second['elements']])
        self.assertNotEqual(first['elements'][1]['observation_geometry'],
                            second['elements'][1]['observation_geometry'])
        self.assertEqual(first['elements'][1]['parent_id'], 'v1')
        self.assertEqual(first['elements'][0]['children_ids'], ['v2'])
        self.assertEqual((state, vision, contract), original)

    def test_changing_layout_does_not_rewrite_observation(self):
        state, vision, contract = fixture()
        first = build_structure(state, vision, coordinate_contract=contract)
        contract['placements'][1]['bbox'] = [420, 570, 950, 660]
        second = build_structure(state, vision, coordinate_contract=contract)
        self.assertEqual(first['elements'][1]['observation_geometry'], second['elements'][1]['observation_geometry'])
        self.assertNotEqual(first['elements'][1]['spatial_info']['bbox'], second['elements'][1]['spatial_info']['bbox'])

    def test_old_baseline_still_scales_photo(self):
        state, vision, _ = fixture()
        self.assertEqual(build_structure(state, vision)['elements'][1]['spatial_info']['bbox'], [200, 490, 400, 560])

    def test_omitted_visual_identity_cannot_invent_placement(self):
        state, vision, contract = fixture()
        state['elements'].pop()
        contract['placements'].pop()
        with self.assertRaisesRegex(ValueError, 'missing=.*v2'):
            build_structure(state, vision, coordinate_contract=contract)

    def test_omitted_visual_identity_with_explicit_placement_retained_once(self):
        state, vision, contract = fixture()
        state['elements'].pop()
        result = build_structure(state, vision, coordinate_contract=contract)
        self.assertEqual([e['id'] for e in result['elements']], ['v1', 'v2'])
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'], [400, 560, 930, 650])

    def test_spoken_entity_has_no_fake_visual_observation(self):
        state, vision, contract = fixture()
        state['elements'].append({'id': 'u_notice', 'origin': 'spoken', 'type': 'text', 'parent_id': None})
        placement = copy.deepcopy(contract['placements'][1])
        placement.update(entity_id='u_notice', bbox=[10, 10, 200, 50])
        placement['derivation']['evidence_refs'] = ['spoken_intent:u_notice']
        contract['placements'].append(placement)
        result = build_structure(state, vision, coordinate_contract=contract)
        self.assertEqual(result['elements'][-1]['observation_geometry'], [])

    def test_legacy_parent_clamping_cannot_silently_run_on_new_contract(self):
        state, vision, contract = fixture()
        with self.assertRaisesRegex(ValueError, 'dedicated compiler'):
            solve_hierarchy(build_structure(state, vision, coordinate_contract=contract))

    def test_invalid_geometry_and_provenance_rejected_without_repair(self):
        mutations = [
            lambda c: c['placements'][0].update(coordinate_space='image_norm'),
            lambda c: c['placements'][0].update(viewport_id='other'),
            lambda c: c['placements'][0].update(bbox=[-1, 0, 1000, 700]),
            lambda c: c['placements'][0].update(bbox=[0, 0, float('nan'), 700]),
            lambda c: c['placements'][0].update(bbox=[0, 0, True, 700]),
            lambda c: c['placements'][0].update(bbox=[1, 0, 1.1, 700]),
            lambda c: c['placements'][0]['derivation'].update(evidence_refs=['vision:unknown']),
            lambda c: c['placements'][0]['derivation'].update(reason=''),
            lambda c: c['placements'][0]['derivation'].update(kind='photo_scaled_to_page'),
            lambda c: c['frame'].update(sha256='not-a-hash'),
            lambda c: c['frame'].update(width=0),
            lambda c: c['viewport'].update(width=500),
            lambda c: c['placements'].append(copy.deepcopy(c['placements'][0])),
            lambda c: c['placements'][0].update(entity_id='extra'),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                state, vision, contract = fixture()
                mutation(contract)
                with self.assertRaises(ValueError):
                    build_structure(state, vision, coordinate_contract=contract)

    def test_invalid_observation_not_silently_clamped(self):
        state, vision, contract = fixture()
        vision['elements'][0]['bbox']['x_min'] = -0.01
        with self.assertRaisesRegex(ValueError, 'outside'):
            build_structure(state, vision, coordinate_contract=contract)


if __name__ == '__main__':
    unittest.main()
