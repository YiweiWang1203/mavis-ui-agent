"""Offline integration checks; no claims about model generation quality."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.agents import coder
from scripts.run_generation_comparison import BudgetClient, artifact_status, run_one


class GenerationContractTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / 'outputs/optimization/generation_test_tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'UI_RENDERER_MODE': 'llm',
            'UI_INPUT_CONTRACT_MODE': 'off', 'UI_CODER_CONTRACT_MODE': 'baseline'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_real_coder_request_changes_prompt_but_never_repairs_response(self):
        requests = []
        raw = '<!DOCTYPE html><html><div id="s"></div></html>'
        def create(**kw):
            requests.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        state = {'elements': [{'id': 's', 'type': 'search_bar'}]}
        base_prompt = (Path(coder.__file__).parents[1] / 'prompts/coder.md').read_text(encoding='utf-8')
        with patch.object(coder, '_get_openai_client', return_value=fake), \
             patch.object(coder, 'HTML_OUTPUT_DIR', self.folder):
            baseline = coder.generate_frontend_code(state)
            os.environ['UI_CODER_CONTRACT_MODE'] = 'native_controls_v1'
            candidate = coder.generate_frontend_code(state)
        self.assertEqual(requests[0]['messages'][0]['content'], base_prompt)
        self.assertNotEqual(requests[0]['messages'][0], requests[1]['messages'][0])
        self.assertEqual(requests[0]['messages'][1], requests[1]['messages'][1])
        self.assertEqual(baseline['code'], raw)
        self.assertEqual(candidate['code'], raw)  # an intentionally wrong mock stays wrong
        self.assertEqual(set(baseline), set(candidate))

    def test_retired_repair_and_invalid_modes_rejected_before_call(self):
        with patch.object(coder, '_get_openai_client') as client:
            os.environ['UI_INPUT_CONTRACT_MODE'] = 'repair_empty'
            with self.assertRaisesRegex(ValueError, 'retired'):
                coder.generate_frontend_code({})
            os.environ['UI_INPUT_CONTRACT_MODE'] = 'off'
            os.environ['UI_CODER_CONTRACT_MODE'] = 'typo'
            with self.assertRaises(ValueError):
                coder.generate_frontend_code({})
            client.assert_not_called()

    def test_budgets_in_actual_request_and_raw_call_trace(self):
        seen = []
        payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': '<html></html>'}}]}
        def create(**kw):
            seen.append(kw)
            return SimpleNamespace(model_dump=lambda: payload)
        client = BudgetClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), self.folder)
        client.stage = 'vision'
        client.create(model='fixture', messages=[], max_tokens=1)
        self.assertEqual(seen[0]['max_tokens'], 8192)
        self.assertEqual(seen[0]['timeout'], 600)
        record = json.loads((self.folder / 'call_01.json').read_text())
        self.assertEqual(record['response'], payload)

    def test_failures_recorded_without_exception_text(self):
        out = self.folder / 'run'
        with patch('scripts.run_generation_comparison.execute', side_effect=RuntimeError('secret')):
            result = run_one({}, 'baseline', out, 'fixture', None, {})
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('secret', (out / 'run_summary.json').read_text())

    def test_truncation_any_stage_and_incomplete_html_are_not_success(self):
        calls = [{'response': {'choices': [{'finish_reason': 'length'}]}},
                 {'response': {'choices': [{'finish_reason': 'stop'}]}}]
        self.assertEqual(artifact_status('<html></html>', calls)[0], 'output_truncated')
        self.assertEqual(artifact_status('<html>', [calls[-1]])[0], 'incomplete_html')
        self.assertEqual(artifact_status('<html></html>', [calls[-1]])[0], 'html_generated_pending_browser_validation')

    def test_cli_dry_run_freezes_inputs_without_provider_dependencies(self):
        import subprocess
        import sys
        case = self.folder / 'case'
        case.mkdir()
        (case / 'case.json').write_text(json.dumps({'prompt': 'p.txt', 'image': 'i.jpg',
            'transcript': 't.txt', 'transcript_source': 'funasr'}))
        for name, content in [('p.txt', 'fixed prompt'), ('t.txt', 'spoken intent'), ('i.jpg', 'fixture')]:
            (case / name).write_text(content)
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'scripts/run_generation_comparison.py'),
            '--cases', str(case), '--output-root', str(self.folder / 'runs'), '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest_path = next((self.folder / 'runs').glob('*/batch.json'))
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest['status'], 'dry_run_only')
        self.assertEqual(manifest['runs'], [])
        frozen = Path(manifest['cases'][0]['folder'])
        self.assertEqual((frozen / 'image.jpg').read_bytes(), (case / 'i.jpg').read_bytes())


if __name__ == '__main__':
    unittest.main()
