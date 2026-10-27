"""Cross-source identity safety tests; no model or case annotation dependencies."""
import copy
import os
import unittest
from unittest.mock import patch
from src.utils.source_alignment import align_source_ids
from src.agents.ui_architect import repair_ui_state_with_vision

VIEW = {'width': 400, 'height': 800}


def model(eid='renamed', box=None, kind='button', text='Item'):
    return {'id': eid, 'type': kind, 'text': text,
            'spatial_info': {'bbox': box or [40, 80, 160, 160]}, 'rpa_action': 'open_item'}


def vision(eid='e1', box=None, kind='button', text='Item'):
    b = box or [.1, .1, .4, .2]
    return {'id': eid, 'type': kind, 'text': text, 'bbox': dict(zip(('x_min','y_min','x_max','y_max'), b))}


class SourceAlignmentTests(unittest.TestCase):
    def test_renamed_object_becomes_one_with_original_action_and_provenance(self):
        state = {'page_meta': {'viewport': VIEW}, 'elements': [model()]}
        payload = {'elements': [vision()]}; original = copy.deepcopy((state, payload))
        with patch.dict(os.environ, {'UI_FUSION_MODE': 'source_alignment_v1'}):
            out = repair_ui_state_with_vision(state, payload)
        self.assertEqual(len(out['elements']), 1)
        e = out['elements'][0]
        self.assertEqual(e['id'], 'e1'); self.assertEqual(e['model_id'], 'renamed')
        self.assertEqual(e['rpa_action'], 'open_item')
        self.assertEqual(e['source_refs'][0], {'source': 'vision', 'id': 'e1'})
        self.assertEqual((state, payload), original)

    def test_exact_id_mode_retains_baseline_fallback_behavior(self):
        with patch.dict(os.environ, {'UI_FUSION_MODE': 'exact_id'}):
            out = repair_ui_state_with_vision({'elements': [model()], 'page_meta': {'viewport': VIEW}}, {'elements': [vision()]})
        self.assertEqual([e['id'] for e in out['elements']], ['renamed','e1'])

    def test_same_label_different_positions_are_not_collapsed(self):
        models = [model('a'), model('b', [200,80,320,160])]
        visuals = [vision(), vision('e2',[.5,.1,.8,.2])]
        out, _ = align_source_ids(models, visuals, VIEW)
        self.assertEqual([e['id'] for e in out], ['e1','e2'])

    def test_equal_geometry_ambiguous_candidates_are_not_forced(self):
        out, decisions = align_source_ids([model()], [vision(), vision('e2')], VIEW)
        self.assertEqual(out[0]['id'], 'renamed')
        self.assertIsNone(decisions[0]['vision_id'])

    def test_two_models_competing_for_same_source_are_not_arbitrarily_merged(self):
        out, decisions = align_source_ids([model('a'), model('b')], [vision()], VIEW)
        self.assertTrue(all(d['vision_id'] is None for d in decisions))
        self.assertEqual(len(out), 2)

    def test_new_spoken_element_is_retained_and_labels_types_protect_distinct_items(self):
        for entry in [model(text='Other'), model(kind='image'), model(box=[280,600,390,700])]:
            out, d = align_source_ids([entry], [vision()], VIEW)
            self.assertEqual(out[0]['id'], 'renamed'); self.assertIsNone(d[0]['vision_id'])

    def test_parent_child_references_follow_aliases(self):
        parent = model('region', kind='card', text='')
        parent['children_ids'] = ['child']
        child = model('child', [50,90,100,130]); child['parent_id'] = 'region'
        v = [vision(kind='card', text=''), vision('e2',[.125,.1125,.25,.1625])]
        out, _ = align_source_ids([parent, child], v, VIEW)
        self.assertEqual(out[0]['children_ids'], ['e2']); self.assertEqual(out[1]['parent_id'], 'e1')

    def test_exact_match_is_reserved_before_geometric_matching(self):
        out, decisions = align_source_ids([model('e1'), model('other')], [vision()], VIEW)
        self.assertEqual(out[0]['id'], 'e1'); self.assertIsNone(decisions[1]['vision_id'])

    def test_duplicate_model_ids_fail_explicitly(self):
        with self.assertRaises(ValueError):
            align_source_ids([model(), model()], [vision()], VIEW)

    def test_below_threshold_runner_up_still_prevents_ambiguous_match(self):
        with patch('src.utils.source_alignment._score', side_effect=[.46, .44]):
            out, decisions = align_source_ids([model()], [vision(), vision('e2')], VIEW)
        self.assertIsNone(decisions[0]['vision_id'])

    def test_missing_id_new_object_does_not_alias_existing_vision_id(self):
        item = model(box=[280,600,390,700]); item.pop('id')
        out, decisions = align_source_ids([item], [vision()], VIEW)
        self.assertEqual(out[0]['id'], 'architect_only_0')
        self.assertIsNone(decisions[0]['vision_id'])


if __name__ == '__main__':
    unittest.main()
