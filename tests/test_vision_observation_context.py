import unittest
from src.utils.vision_observation_context import observation_context


class ObservationContextTests(unittest.TestCase):
    def test_native_extractor_switches_context_without_changing_image_or_schema(self):
        import importlib.util
        if any(importlib.util.find_spec(name) is None for name in ('dotenv','openai')):
            self.skipTest('Native vision dependencies absent locally; required in Ubuntu UV gate')
        import json
        import os
        from pathlib import Path
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        spec=importlib.util.spec_from_file_location('test_photo_vision',Path(__file__).resolve().parents[1]/'src/tools/vision_tool.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        calls=[]
        def create(**kwargs):
            calls.append(kwargs)
            raw={'canvas':{'width':406,'height':720},'elements':[{'id':'e1','type':'input','bbox':[.1,.2,.4,.3]}]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'fixture.jpg';Image.new('RGB',(406,720),'white').save(image)
            with patch.dict(os.environ,{'VISION_MODEL':'test','SILICONFLOW_API_KEY':'not-a-real-key'}),patch.object(module,'OpenAI',return_value=client):
                module.extract_ui_layout(str(image),user_context='target PC1440x900')
                module.extract_ui_layout(str(image),user_context='target PC1440x900',context_mode='photo_observation_v1')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['messages'][1]['content'][1],calls[1]['messages'][1]['content'][1])
        self.assertEqual(calls[0]['temperature'],calls[1]['temperature'])
        self.assertEqual(calls[0]['response_format'],calls[1]['response_format'])
        self.assertIn('PC1440',calls[0]['messages'][1]['content'][0]['text'])
        self.assertNotIn('1440',calls[1]['messages'][1]['content'][0]['text'])

    def test_default_transports_original_request_unchanged(self):
        self.assertEqual(observation_context('PC 1440x900 and spoken intent', 406, 720), 'PC 1440x900 and spoken intent')

    def test_photo_mode_uses_actual_dimensions_without_target_or_speech(self):
        text = observation_context('PC 1440x900 private spoken intent', 406, 720, 'photo_observation_v1')
        self.assertIn('406 pixels wide, 720 pixels high', text)
        self.assertNotIn('1440', text)
        self.assertNotIn('private spoken intent', text)
        self.assertIn('full photograph', text)

    def test_unknown_mode_and_invalid_sizes_fail(self):
        with self.assertRaises(ValueError):
            observation_context('t', 406, 720, 'typo')
        for width in (False, 0, -1, 406.0):
            with self.assertRaises(ValueError):
                observation_context('t', width, 720, 'photo_observation_v1')

    def test_no_layout_or_object_answers_in_candidate_context(self):
        text = observation_context('back button at .2, .3', 100, 200, 'photo_observation_v1')
        self.assertNotIn('back button', text)
        self.assertNotIn('.2', text)
