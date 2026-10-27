import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agents import ui_architect
from src.utils.node_relation_evidence import compile_node_relations
from src.utils.relation_evidence import apply_relation_evidence
from scripts.run_pilot_experiment import image_url_hashes, safe_messages


class NodeRelationEvidenceTests(unittest.TestCase):
    quote = 'The card contains Send.'

    def state(self):
        return {'page_meta': {'viewport': {'width': 375, 'height': 812}}, 'elements': [
            {'id': 'region', 'vision_id': 'region', 'type': 'card', 'text': '', 'parent_id': None},
            {'id': 'send', 'vision_id': 'send', 'type': 'button', 'text': 'Send',
             'parent_id': 'region', 'parent_evidence_quote': self.quote}]}

    def test_one_edge_per_parent_declaration_preserves_input_and_validates_source(self):
        state = self.state(); original = copy.deepcopy(state)
        compiled = compile_node_relations(state)
        self.assertEqual(state, original)
        self.assertEqual(compiled['relationships'], [{'parent_id': 'region', 'child_id': 'send', 'evidence_quote': self.quote}])
        result = apply_relation_evidence(compiled, self.quote, isolate_source_errors=True)
        self.assertEqual(result['elements'][1]['parent_id'], 'region')
        self.assertEqual(result['page_meta']['relation_evidence']['accepted_count'], 1)

    def test_missing_quote_becomes_unresolved_never_accepted(self):
        state = self.state(); state['elements'][1].pop('parent_evidence_quote')
        result = apply_relation_evidence(compile_node_relations(state), self.quote, isolate_source_errors=True)
        self.assertIsNone(result['elements'][1]['parent_id'])
        self.assertEqual(result['page_meta']['relation_evidence']['unresolved_count'], 1)

    def test_parallel_truth_or_orphan_quote_and_duplicate_node_rejected(self):
        state = self.state(); state['relationships'] = [{'parent_id': 'region', 'child_id': 'send'}]
        with self.assertRaisesRegex(ValueError, 'parallel'):
            compile_node_relations(state)
        state = self.state(); state['elements'][0]['parent_evidence_quote'] = self.quote
        with self.assertRaisesRegex(ValueError, 'no parent'):
            compile_node_relations(state)
        state = self.state(); state['elements'].append(copy.deepcopy(state['elements'][1]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            compile_node_relations(state)

    def test_invalid_container_and_cycles_not_hidden_by_source_isolation(self):
        state = self.state(); state['elements'][0]['type'] = 'button'
        with self.assertRaisesRegex(ValueError, 'not a container'):
            apply_relation_evidence(compile_node_relations(state), self.quote, isolate_source_errors=True)
        state = self.state(); state['elements'][1]['type'] = 'card'
        state['elements'][0].update(parent_id='send', parent_evidence_quote=self.quote)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            apply_relation_evidence(compile_node_relations(state), self.quote, isolate_source_errors=True)

    def test_real_architect_compiles_node_quotes_with_one_multimodal_call(self):
        seen = []
        def create(**kw):
            seen.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.state())))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        vision = {'elements': [
            {'id': 'region', 'type': 'card', 'bbox': {'x_min': 0, 'y_min': .5, 'x_max': 1, 'y_max': .8}},
            {'id': 'send', 'type': 'button', 'text': 'Send', 'bbox': {'x_min': .1, 'y_min': .6, 'x_max': .4, 'y_max': .7}}]}
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_node_evidence_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=client):
            result = ui_architect.generate_ui_state(self.quote, vision, image_data_url='data:image/jpeg;base64,YQ==')
        self.assertNotIn('error', result)
        self.assertEqual(result['elements'][0]['parent_id'], 'region')
        self.assertEqual(len(seen), 1)
        self.assertNotIn('Source-grounded containment ledger', seen[0]['messages'][0]['content'])
        self.assertIn('parent_evidence_quote', seen[0]['messages'][0]['content'])

    def test_image_hashes_distinguish_images_hidden_by_same_redacted_placeholder(self):
        def messages(data):
            return [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': data}}]}]
        a = messages('data:image/jpeg;base64,YQ=='); b = messages('data:image/jpeg;base64,Yg==')
        self.assertEqual(safe_messages(a), safe_messages(b))
        self.assertNotEqual(image_url_hashes(a), image_url_hashes(b))
        self.assertEqual(len(image_url_hashes(a)[0]), 64)


if __name__ == '__main__':
    unittest.main()
