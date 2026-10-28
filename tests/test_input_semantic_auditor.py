import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.agents.input_semantic_auditor import compile_input_audit, audit_input_semantics
from src.utils.spoken_input_evidence import compile_spoken_inputs
from tests.test_spoken_input_evidence import SpokenInputTests


class InputAuditTests(unittest.TestCase):
    def fixture(self):
        state, vision = SpokenInputTests().fixture()
        state.pop('semantic_input_overrides')
        return state, vision

    def row(self, verdict='editable', quote='输入框是可以输入文字的'):
        return {'vision_id': 'entry', 'verdict': verdict, 'evidence_quote': quote}

    def test_source_supported_editability_reaches_existing_compiler(self):
        state, vision = self.fixture(); old = copy.deepcopy(state)
        out = compile_input_audit(state, vision, SpokenInputTests.quote,
                                 {'input_audit': [self.row()]})
        self.assertEqual(state, old)
        self.assertEqual(out['elements'], old['elements'])
        self.assertEqual(compile_spoken_inputs(out, vision, SpokenInputTests.quote)['elements'][0]['type'], 'input')

    def test_omission_unknown_duplicate_and_node_edit_are_rejected(self):
        state, vision = self.fixture()
        for rows in [[], [dict(self.row(), vision_id='unknown')], [self.row(), self.row()],
                     [dict(self.row(), bbox=[0, 0, 1, 1])]]:
            with self.assertRaises(ValueError):
                compile_input_audit(state, vision, SpokenInputTests.quote, {'input_audit': rows})

    def test_fabricated_and_negative_evidence_cannot_enable_input(self):
        state, vision = self.fixture()
        with self.assertRaisesRegex(ValueError, 'absent'):
            compile_input_audit(state, vision, SpokenInputTests.quote,
                                {'input_audit': [self.row(quote='fabricated')]})
        quote = '输入框不能输入文字'
        out = compile_input_audit(state, vision, quote, {'input_audit': [self.row(quote=quote)]})
        self.assertEqual(compile_spoken_inputs(out, vision, quote)['elements'][0]['type'], 'text')

    def test_uncertain_is_reported_not_silently_accepted(self):
        state, vision = self.fixture()
        out = compile_input_audit(state, vision, '', {'input_audit': [self.row('uncertain', '')]})
        self.assertEqual(out['page_meta']['input_semantic_audit']['uncertain_count'], 1)
        self.assertEqual(out['semantic_input_overrides'], [])

    def test_one_call_budget_stage_and_no_retry_on_truncation(self):
        state, vision = self.fixture(); seen = []
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='length',
                   message=SimpleNamespace(content='{}'))])
        client = SimpleNamespace(stage='ui_architect', chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertRaisesRegex(ValueError, 'truncated'):
            audit_input_semantics(state, vision, SpokenInputTests.quote, 'model', client)
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0]['max_tokens'], seen[0]['timeout']), (8192, 600))
        self.assertEqual(client.stage, 'ui_architect')

    def test_production_hook_runs_audit_before_finalization(self):
        from src.agents import ui_architect
        state, vision = self.fixture(); seen = []
        responses = [state, {'input_audit': [self.row()]}]
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                content=json.dumps(responses[len(seen)-1])))])
        client = SimpleNamespace(stage='ui_architect', chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(ui_architect, '_get_openai_client', return_value=client), patch.dict(os.environ, {
            'UI_INPUT_SEMANTIC_AUDIT_MODE': 'input_audit_v1', 'UI_SEMANTIC_TYPE_MODE': 'spoken_input_v1',
            'UI_RELATION_SPECIALIST_MODE': 'off', 'UI_RELATION_AGGREGATION_MODE': 'validated_union_v1',
            'UI_STRUCTURE_MODE': 'hierarchy_registry_inline_v1'}):
            out = ui_architect.generate_ui_state(SpokenInputTests.quote, vision)
        self.assertEqual(len(seen), 2)
        self.assertEqual(out['elements'][0]['type'], 'input')


if __name__ == '__main__':
    unittest.main()
