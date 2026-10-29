"""Synthetic D1 invariants; these are not user-page effect scores."""
import copy
import unittest

from src.utils.hierarchy_contract import build_structure, solve_hierarchy
from src.utils.coordinate_contract import (
    CoordinateResponsibilityError,
    audit_architect_coordinate_responsibility,
    enforce_architect_coordinate_responsibility,
)


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
    def responsibility_fixture(self):
        state, vision, contract = fixture()
        vision['canvas'] = {'width': 600, 'height': 900}
        provenance = {'observation_frame': copy.deepcopy(contract['frame']),
                      'target_viewport': copy.deepcopy(contract['viewport'])}
        for element, placement in zip(state['elements'], contract['placements']):
            element['spatial_info'] = {
                'bbox': copy.deepcopy(placement['bbox']),
                'coordinate_space': 'viewport_px', 'viewport_id': 'vp1',
                'derivation': copy.deepcopy(placement['derivation']),
            }
        return state, vision, provenance

    def test_pre_overwrite_audit_accepts_declared_dual_spaces(self):
        state, vision, provenance = self.responsibility_fixture()
        report = enforce_architect_coordinate_responsibility(state, vision, provenance)
        self.assertEqual((report['valid_count'], report['invalid_count'], report['skipped_count']), (2, 0, 0))
        self.assertEqual(report['observation_geometry']['size'], {'width': 600, 'height': 900})
        self.assertEqual(report['target_placement']['size'], {'width': 1000, 'height': 700})
        self.assertEqual(report['mapping_strategy'], 'pending_user_decision')

    def test_pre_overwrite_audit_rejects_zero_area_without_repair(self):
        state, vision, provenance = self.responsibility_fixture()
        for element in state['elements']:
            element['spatial_info']['bbox'] = [1000, 700, 1000, 700]
        original = copy.deepcopy(state)
        with self.assertRaises(CoordinateResponsibilityError) as caught:
            enforce_architect_coordinate_responsibility(state, vision, provenance)
        report = caught.exception.diagnostic
        self.assertEqual((report['invalid_count'], report['element_count'], report['skipped_count']), (2, 2, 0))
        self.assertTrue(all(item['raw_bbox'] == [1000, 700, 1000, 700] for item in report['elements']))
        self.assertEqual(state, original)

    def test_pre_overwrite_audit_reports_missing_space_derivation_and_partial_placement(self):
        state, vision, provenance = self.responsibility_fixture()
        state['elements'][0]['spatial_info'].pop('coordinate_space')
        state['elements'][0]['spatial_info'].pop('derivation')
        state['elements'][1]['spatial_info'].pop('bbox')
        report = audit_architect_coordinate_responsibility(state, vision, provenance)
        codes = [{issue['code'] for issue in item['issues']} for item in report['elements']]
        self.assertIn('missing_or_wrong_coordinate_space', codes[0])
        self.assertIn('missing_derivation', codes[0])
        self.assertIn('missing_placement', codes[1])
        self.assertEqual((report['invalid_count'], report['skipped_count']), (2, 1))

    def test_pre_overwrite_audit_reports_object_coverage(self):
        state, vision, provenance = self.responsibility_fixture()
        state['elements'].pop()
        report = audit_architect_coordinate_responsibility(state, vision, provenance)
        coverage = [item for item in report['global_issues']
                    if item['code'] == 'architect_vision_coverage_mismatch']
        self.assertEqual(coverage[0]['missing'], ['v2'])
        self.assertEqual(report['status'], 'rejected')

    def test_pre_overwrite_audit_rejects_unknown_derivation_reference(self):
        state, vision, provenance = self.responsibility_fixture()
        state['elements'][0]['spatial_info']['derivation']['evidence_refs'] = [
            'vision:does_not_exist']
        report = audit_architect_coordinate_responsibility(state, vision, provenance)
        issues = report['elements'][0]['issues']
        unknown = [item for item in issues if item['code'] == 'unknown_derivation_sources']
        self.assertEqual(unknown[0]['references'], ['vision:does_not_exist'])
        self.assertEqual(report['status'], 'rejected')

    def test_pre_overwrite_audit_rejects_nonfinite_outside_and_photo_sized_target(self):
        for bbox in ([0, 0, float('nan'), 10], [-1, 0, 20, 20]):
            state, vision, provenance = self.responsibility_fixture()
            state['elements'][0]['spatial_info']['bbox'] = bbox
            self.assertEqual(audit_architect_coordinate_responsibility(
                state, vision, provenance)['invalid_count'], 1)
        state, vision, provenance = self.responsibility_fixture()
        provenance['target_viewport'] = {'id': 'vp1', 'width': 600, 'height': 900}
        report = audit_architect_coordinate_responsibility(state, vision, provenance)
        self.assertIn('target_viewport_mismatch', {item['code'] for item in report['global_issues']})
        self.assertEqual(report['status'], 'rejected')

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
