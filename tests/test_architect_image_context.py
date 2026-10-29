import unittest
from src.utils.architect_image_context import architect_request_content


class ArchitectImageContextTests(unittest.TestCase):
    def test_real_architect_keeps_system_and_text_equal_and_changes_only_image(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from src.agents import ui_architect
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"elements":[],"page_meta":{}}'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        env = {'UI_STRUCTURE_MODE': 'hierarchy_v1', 'UI_SEMANTIC_TYPE_MODE': 'off',
               'UI_RELATION_SPECIALIST_MODE': 'off', 'UI_INPUT_SEMANTIC_AUDIT_MODE': 'off'}
        with patch.dict(os.environ, env), patch.object(ui_architect, '_get_openai_client', return_value=client), \
             patch.object(ui_architect, 'finalize_ui_state', side_effect=lambda state, *args: state):
            ui_architect.generate_ui_state('PC target 1440x900', {'canvas': {'width': 406, 'height': 720}, 'elements': []})
            ui_architect.generate_ui_state('PC target 1440x900', {'canvas': {'width': 406, 'height': 720}, 'elements': []},
                image_data_url='data:image/jpeg;base64,AA==', attach_observation_image=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['messages'][0], calls[1]['messages'][0])
        self.assertEqual(calls[0]['messages'][1]['content'], calls[1]['messages'][1]['content'][0]['text'])
        self.assertEqual(calls[0]['temperature'], calls[1]['temperature'])
        self.assertEqual(calls[1]['messages'][1]['content'][1]['image_url']['url'], 'data:image/jpeg;base64,AA==')

    def test_default_keeps_text_even_with_supplied_image(self):
        self.assertEqual(architect_request_content('intent', 'hierarchy_v1', 'data:image/jpeg;base64,AA=='), 'intent')

    def test_opt_in_transports_exact_bytes_without_text_changes(self):
        url = 'data:image/jpeg;base64,AABB=='
        content = architect_request_content('original text', 'hierarchy_v1', url, attach_observation_image=True)
        self.assertEqual(content, [{'type': 'text', 'text': 'original text'}, {'type': 'image_url', 'image_url': {'url': url}}])

    def test_missing_image_fails_instead_of_falling_back(self):
        for value in (None, '', 'http://example.org/image.jpg'):
            with self.assertRaises(ValueError):
                architect_request_content('t', 'hierarchy_v1', value, attach_observation_image=True)

    def test_old_image_modes_remain_image_modes(self):
        for mode in ('hierarchy_registry_image_v1', 'hierarchy_node_evidence_v1'):
            with self.assertRaises(ValueError):
                architect_request_content('t', mode)
            self.assertIsInstance(architect_request_content('t', mode, 'data:image/png;base64,AA=='), list)

    def test_isolation_rejects_other_modes_and_truthy_non_boolean(self):
        with self.assertRaises(ValueError):
            architect_request_content('t', 'baseline', 'data:image/png;base64,AA==', attach_observation_image=True)
        with self.assertRaises(ValueError):
            architect_request_content('t', 'hierarchy_v1', attach_observation_image='yes')
