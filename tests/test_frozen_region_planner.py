import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from src.agents.frozen_region_planner import compile_frozen_regions, frozen_inventory, generate_frozen_region_plan


class FrozenRegionTests(unittest.TestCase):
    def fixture(self):
        from tests.test_region_layout_contract import fixture
        from src.utils.hierarchy_contract import build_structure
        state, vision, frame, viewport, plan = fixture()
        state = build_structure(state, vision)
        for e in state['elements']:
            e['rpa_action'] = 'immutable_action'
        return plan, state, vision, dict(request='Make an interface.', speech='Editor below content.', frame=frame, viewport=viewport)

    def test_geometry_changes_but_semantics_and_inputs_are_immutable(self):
        plan, state, vision, kwargs = self.fixture()
        before = copy.deepcopy((plan, state, vision))
        result = compile_frozen_regions(plan, state, vision, **kwargs)
        self.assertEqual(frozen_inventory(result), frozen_inventory(state))
        self.assertEqual(result['elements'][1]['spatial_info']['bbox'], [325, 656, 925, 752])
        self.assertIsNone(result['page_meta']['frozen_inventory_layout']['requirements_coverage'])
        self.assertEqual((plan, state, vision), before)

    def test_missing_duplicate_unknown_and_semantic_edits_fail(self):
        plan, state, vision, kwargs = self.fixture()
        edits = []
        p = copy.deepcopy(plan); p['entities'] = []; edits.append(p)
        p = copy.deepcopy(plan); p['placements'].pop(); edits.append(p)
        p = copy.deepcopy(plan); p['placements'].append(copy.deepcopy(p['placements'][0])); edits.append(p)
        p = copy.deepcopy(plan); p['placements'][0]['entity_id'] = 'not_observed'; edits.append(p)
        p = copy.deepcopy(plan); p['placements'][0]['evidence_refs'] = ['speech:invented']; edits.append(p)
        for p in edits:
            with self.subTest(p=p), self.assertRaises(ValueError):
                compile_frozen_regions(p, state, vision, **kwargs)

    def test_wrong_parent_and_overlap_are_preserved_as_conflicts(self):
        plan, state, vision, kwargs = self.fixture()
        plan['placements'][0]['region_id'] = 'side'
        result = compile_frozen_regions(plan, state, vision, **kwargs)
        self.assertEqual(result['elements'][1]['parent_id'], state['elements'][1]['parent_id'])
        self.assertTrue(any(c['kind'] == 'semantic_parent_layout_conflict' for c in result['page_meta']['region_layout']['conflicts']))

    def test_single_call_no_retry_and_no_baseline_layout_in_inventory(self):
        plan, state, vision, kwargs = self.fixture()
        for good in (True, False):
            calls = []
            raw = json.dumps(plan if good else {'entities': []})
            def create(**args):
                calls.append(args)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason='stop')])
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with TemporaryDirectory() as directory:
                if good:
                    generate_frozen_region_plan(state, vision, **kwargs, image_data_url='data:image/jpeg;base64,AA==', client=client, model='test', output=directory)
                else:
                    with self.assertRaises(ValueError):
                        generate_frozen_region_plan(state, vision, **kwargs, image_data_url='data:image/jpeg;base64,AA==', client=client, model='test', output=directory)
                payload = json.loads((Path(directory) / 'region_plan_input.json').read_text(encoding='utf8'))
                self.assertTrue(all('spatial_info' not in e for e in payload['immutable_entities']))
                self.assertEqual((Path(directory) / 'region_plan_raw.txt').read_text(encoding='utf8'), raw)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['max_tokens'], 8192)
                self.assertEqual(calls[0]['timeout'], 600)


if __name__ == '__main__':
    unittest.main()
