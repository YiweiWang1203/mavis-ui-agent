import json
from types import SimpleNamespace
import unittest

from src.agents.ui_architect import generate_target_layout_attempt


class FakeClient:
    def __init__(self, raw='{}', finish_reason='stop'):
        self.kwargs = None
        self.response = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason, message=SimpleNamespace(content=raw))])
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.kwargs = kwargs; return self.response


class TargetAttemptTests(unittest.TestCase):
    def context(self):
        return {'observation_frame': {'id': 'f', 'width': 406, 'height': 720,
                                      'sha256': 'a' * 64},
                'target_viewport': {'id': 'pc', 'width': 1440, 'height': 900}}

    def test_dedicated_prompt_and_trusted_context_are_in_actual_request(self):
        client = FakeClient('{"page_meta":{},"elements":[]}')
        result = generate_target_layout_attempt('intent', {'canvas': {}, 'elements': []},
                                                self.context(), client=client)
        request = client.kwargs
        system = request['messages'][0]['content']
        payload = json.loads(request['messages'][1]['content'])
        self.assertIn('You own the page-global target placement of EVERY output element', system)
        self.assertIn('will NOT replace them with vision boxes', system)
        self.assertEqual(payload['trusted_coordinate_context']['target_viewport']['id'], 'pc')
        self.assertNotIn('sha256', payload['trusted_coordinate_context']['observation_frame'])
        self.assertEqual((request['max_tokens'], request['timeout']), (8192, 600))
        self.assertEqual(result['status'], 'parsed')

    def test_correction_feedback_is_sent_without_changing_context(self):
        client = FakeClient('{}'); feedback = {'failed_node': 'gate', 'failures': []}
        generate_target_layout_attempt('intent', {'elements': []}, self.context(),
                                       correction_feedback=feedback, client=client,
                                       attempt_id='architect-1')
        payload = json.loads(client.kwargs['messages'][1]['content'])
        self.assertEqual(payload['correction_feedback'], feedback)
        self.assertEqual(payload['trusted_coordinate_context']['target_viewport']['width'], 1440)

    def test_parse_failure_retains_raw_response(self):
        client = FakeClient('{bad json')
        result = generate_target_layout_attempt('intent', {'elements': []}, self.context(), client=client)
        self.assertEqual(result['status'], 'parse_error')
        self.assertEqual(result['raw_response'], '{bad json')
        self.assertEqual(result['parse_error']['type'], 'JSONDecodeError')


if __name__ == '__main__':
    unittest.main()
