import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agents import ui_architect


class ArchitectVisualContextTests(unittest.TestCase):
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0V8AAAAASUVORK5CYII='
    quote = 'The card contains Send.'

    def inputs(self):
        state = {'page_meta': {'viewport': {'width': 375, 'height': 812}},
                 'elements': [{'id': 'region', 'vision_id': 'region', 'type': 'card', 'text': ''},
                              {'id': 'send', 'vision_id': 'send', 'type': 'button', 'text': 'Send'}],
                 'relationships': [{'parent_id': 'region', 'child_id': 'send', 'evidence_quote': self.quote}]}
        vision = {'elements': [{'id': 'region', 'type': 'card', 'bbox': {'x_min': 0, 'y_min': .5, 'x_max': 1, 'y_max': .8}},
                               {'id': 'send', 'type': 'button', 'text': 'Send', 'bbox': {'x_min': .1, 'y_min': .6, 'x_max': .4, 'y_max': .7}}]}
        return state, vision

    def client(self, state, seen):
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(state)))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def test_only_image_part_differs_and_same_contract_executes(self):
        state, vision = self.inputs(); seen = []
        with patch.object(ui_architect, '_get_openai_client', return_value=self.client(state, seen)):
            with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_inline_v1'}):
                baseline = ui_architect.generate_ui_state(self.quote, vision)
            with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_image_v1'}):
                candidate = ui_architect.generate_ui_state(self.quote, vision, image_data_url=self.image)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]['messages'][0], seen[1]['messages'][0])
        content = seen[1]['messages'][1]['content']
        self.assertEqual(content[0]['text'], seen[0]['messages'][1]['content'])
        self.assertEqual(content[1], {'type': 'image_url', 'image_url': {'url': self.image}})
        self.assertEqual(candidate, baseline)
        self.assertEqual(candidate['elements'][0]['parent_id'], 'region')

    def test_missing_or_remote_image_never_silently_falls_back_or_calls_api(self):
        state, vision = self.inputs(); seen = []
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_image_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=self.client(state, seen)):
            for value in (None, '', 'https://example.org/image.png'):
                with self.assertRaisesRegex(ValueError, 'requires'):
                    ui_architect.generate_ui_state(self.quote, vision, image_data_url=value)
        self.assertEqual(seen, [])

    def test_visual_context_does_not_bypass_parent_type_check(self):
        state, vision = self.inputs(); seen = []
        state['relationships'][0].update(parent_id='send', child_id='region')
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_image_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=self.client(state, seen)):
            result = ui_architect.generate_ui_state(self.quote, vision, image_data_url=self.image)
        self.assertEqual(result['error'], 'Relation parent is not a container')
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
