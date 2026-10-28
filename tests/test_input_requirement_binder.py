import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.agents.input_requirement_binder import input_requirement_slots, compile_requirement_bindings, bind_input_requirements
from src.utils.spoken_input_evidence import compile_spoken_inputs


class RequirementBindingTests(unittest.TestCase):
    quote = '输入框是可以输入文字的。'

    def fixture(self, kind='text'):
        vision = {'elements': [{'id': 'entry', 'text': '输入框', 'type': kind,
                  'bbox': {'x_min': .1, 'y_min': .7, 'x_max': .8, 'y_max': .8}}]}
        state = {'page_meta': {'viewport': {'width': 1440, 'height': 900}}, 'relationships': [],
                 'elements': [{'id': 'entry', 'vision_id': 'entry', 'text': '输入框', 'type': kind,
                               'parent_id': None, 'rpa_action': None}]}
        return state, vision

    def declaration(self, vid='entry'):
        return {'bindings': [{'requirement_id': 'r1', 'vision_id': vid}]}

    def test_slots_are_exact_and_keep_negative_and_overlong_unresolved(self):
        intent = '标题。\n' + self.quote + '输入框不能输入文字。' + 'a' * 401 + self.quote
        slots, unresolved = input_requirement_slots(intent)
        self.assertEqual(len(slots), 1)
        for row in slots + unresolved:
            self.assertEqual(intent[row['start']:row['end']], row['quote'])
        self.assertEqual({x['reason'] for x in unresolved}, {'negative_or_readonly_source', 'source_span_exceeds_limit'})

    def test_code_selects_quote_only_and_existing_compiler_changes_type(self):
        state, vision = self.fixture(); before = copy.deepcopy(state)
        out = compile_requirement_bindings(state, vision, self.quote, self.declaration())
        self.assertEqual(state, before)
        self.assertEqual(out['elements'], before['elements'])
        self.assertEqual(out['semantic_input_overrides'][0]['evidence_quote'], self.quote)
        self.assertEqual(compile_spoken_inputs(out, vision, self.quote)['elements'][0]['type'], 'input')

    def test_already_native_is_binding_confirmation_not_a_type_change(self):
        state, vision = self.fixture('input')
        out = compile_requirement_bindings(state, vision, self.quote, self.declaration())
        meta = out['page_meta']['input_requirement_binding']
        self.assertEqual(meta['bound_count'], 1)
        self.assertEqual(meta['type_change_proposals'], 0)
        self.assertEqual(len(meta['already_native']), 1)

    def test_missing_duplicate_unknown_and_free_quotes_are_rejected(self):
        state, vision = self.fixture()
        bad = [{'bindings': []}, {'bindings': self.declaration()['bindings'] * 2},
               self.declaration('other'), {'bindings': [{'requirement_id': 'fake', 'vision_id': 'entry'}]},
               {'bindings': [dict(self.declaration()['bindings'][0], evidence_quote='fabricated')]}]
        for declaration in bad:
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                compile_requirement_bindings(state, vision, self.quote, declaration)

    def test_unbound_and_literal_ambiguity_reported_without_inventing_nodes(self):
        state, vision = self.fixture()
        out = compile_requirement_bindings(state, vision, self.quote, self.declaration(None))
        self.assertEqual(out['page_meta']['input_requirement_binding']['unresolved_count'], 1)
        other = copy.deepcopy(vision['elements'][0]); other['id'] = 'second'; vision['elements'].append(other)
        out = compile_requirement_bindings(state, vision, self.quote, self.declaration())
        self.assertEqual(out['page_meta']['input_requirement_binding']['unresolved'][0]['reason'], 'ambiguous_literal_label')

    def test_skip_no_explicit_source_without_a_model_call(self):
        state, vision = self.fixture()
        out = bind_input_requirements(state, vision, '这里是消息展示。', 'model', None)
        self.assertEqual(out['page_meta']['input_requirement_binding']['eligible_count'], 0)

    def test_one_bounded_model_call_and_production_hook(self):
        from src.agents import ui_architect
        state, vision = self.fixture(); seen = []
        def create(**kwargs):
            seen.append(kwargs)
            value = state if len(seen) == 1 else self.declaration()
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content=json.dumps(value)))])
        client = SimpleNamespace(stage='ui_architect', chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(ui_architect, '_get_openai_client', return_value=client), patch.dict(os.environ, {
            'UI_INPUT_SEMANTIC_AUDIT_MODE': 'requirement_slots_v1', 'UI_SEMANTIC_TYPE_MODE': 'spoken_input_v1',
            'UI_RELATION_SPECIALIST_MODE': 'off', 'UI_RELATION_AGGREGATION_MODE': 'off',
            'UI_STRUCTURE_MODE': 'hierarchy_registry_inline_v1'}):
            out = ui_architect.generate_ui_state(self.quote, vision)
        self.assertEqual(len(seen), 2)
        self.assertEqual((seen[1]['max_tokens'], seen[1]['timeout']), (8192, 600))
        self.assertEqual(out['elements'][0]['type'], 'input')
        self.assertEqual(client.stage, 'ui_architect')

    def test_truncation_does_not_retry(self):
        state, vision = self.fixture(); seen = []
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='length')])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertRaisesRegex(ValueError, 'truncated'):
            bind_input_requirements(state, vision, self.quote, 'model', client)
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
