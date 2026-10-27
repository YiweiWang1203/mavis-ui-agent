import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agents import ui_architect
from src.utils.container_registry import compile_container_registry
from src.utils.relation_evidence import apply_relation_evidence


class ContainerRegistryTests(unittest.TestCase):
    quote = 'The card contains Send.'

    def state(self):
        return {'page_meta': {'viewport': {'width': 375, 'height': 812}},
                'elements': [{'id': 'send', 'vision_id': 'send', 'type': 'button', 'text': 'Send'}],
                'containers': [{'id': 'u_card', 'vision_id': None, 'origin': 'spoken',
                                'type': 'card', 'text': '', 'evidence_quote': self.quote,
                                'spatial_info': {'bbox': [0, 400, 375, 600]}}],
                'relationships': [{'parent_id': 'u_card', 'child_id': 'send', 'evidence_quote': self.quote}]}

    def vision(self):
        return {'elements': [{'id': 'send', 'type': 'button', 'text': 'Send',
                             'bbox': {'x_min': 0, 'y_min': .55, 'x_max': .3, 'y_max': .65}}]}

    def test_source_backed_declaration_materialized_without_mutating_input(self):
        state = self.state(); original = copy.deepcopy(state)
        compiled = compile_container_registry(state, self.vision(), self.quote)
        self.assertEqual(state, original)
        self.assertEqual(len(compiled['elements']), 2)
        self.assertEqual(compiled['page_meta']['container_registry']['declared_count'], 1)
        accepted = apply_relation_evidence(compiled, self.quote, isolate_source_errors=True)
        self.assertEqual(accepted['elements'][0]['parent_id'], 'u_card')

    def test_no_undeclared_node_created_from_dangling_reference(self):
        state = self.state(); state['containers'] = []
        with self.assertRaisesRegex(ValueError, 'Undeclared'):
            compile_container_registry(state, self.vision(), self.quote)

    def test_container_cannot_bypass_registry(self):
        state = self.state(); state['elements'].append(state['containers'].pop())
        with self.assertRaisesRegex(ValueError, 'must be declared'):
            compile_container_registry(state, self.vision(), self.quote)

    def test_missing_quote_and_unsupported_container_are_not_materialized(self):
        for value in ('fabricated', 'Send is here.'):
            state = self.state(); state['containers'][0]['evidence_quote'] = value
            with self.assertRaises(ValueError):
                compile_container_registry(state, self.vision(), self.quote + ' Send is here.')
        state = self.state(); state['containers'][0]['type'] = 'image'
        with self.assertRaisesRegex(ValueError, 'not a container'):
            compile_container_registry(state, self.vision(), self.quote)

    def test_duplicate_identity_or_visual_source_rejected(self):
        state = self.state(); state['containers'][0]['id'] = 'send'
        with self.assertRaisesRegex(ValueError, 'identity'):
            compile_container_registry(state, self.vision(), self.quote)
        state = self.state(); state['containers'][0]['vision_id'] = 'send'
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            compile_container_registry(state, self.vision(), self.quote)

    def test_visual_container_keeps_source_and_does_not_need_spoken_quote(self):
        state = self.state(); state['containers'][0].update(id='region', vision_id='region', origin='vision')
        state['relationships'][0]['parent_id'] = 'region'
        vision = self.vision(); vision['elements'].append({'id': 'region', 'type': 'card'})
        result = compile_container_registry(state, vision, '')
        self.assertEqual(result['elements'][1]['vision_id'], 'region')

    def test_bad_bounds_and_global_conflicts_remain_fatal(self):
        state = self.state(); state['containers'][0]['spatial_info']['bbox'] = [0, 400, 400, 600]
        with self.assertRaisesRegex(ValueError, 'outside'):
            compile_container_registry(state, self.vision(), self.quote)
        state = self.state(); state['relationships'] *= 2
        compiled = compile_container_registry(state, self.vision(), self.quote)
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            apply_relation_evidence(compiled, self.quote, isolate_source_errors=True)

    def test_actual_architect_path_compiles_before_relation_and_layout(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.state())))])
        create = lambda **kw: response
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=client):
            result = ui_architect.generate_ui_state(self.quote, self.vision())
        self.assertNotIn('error', result)
        self.assertEqual(result['elements'][0]['parent_id'], 'u_card')
        self.assertEqual(len(result['elements']), 2)
        self.assertEqual(result['page_meta']['container_registry']['declared_count'], 1)

    def single_table(self):
        state = self.state()
        state['elements'].extend(state.pop('containers'))
        return state

    def test_inline_moves_existing_nodes_once_and_keeps_input_unchanged(self):
        state = self.single_table(); original = copy.deepcopy(state)
        result = compile_container_registry(state, self.vision(), self.quote, inline=True)
        self.assertEqual(state, original)
        self.assertEqual([e['id'] for e in result['elements']], ['send', 'u_card'])
        self.assertEqual(result['page_meta']['container_registry']['representation'], 'single_node_table')
        accepted = apply_relation_evidence(result, self.quote, isolate_source_errors=True)
        self.assertEqual(accepted['elements'][0]['parent_id'], 'u_card')

    def test_inline_rejects_secondary_facts_and_undeclared_endpoints(self):
        state = self.single_table(); state['containers'] = [copy.deepcopy(state['elements'][1])]
        with self.assertRaisesRegex(ValueError, 'secondary'):
            compile_container_registry(state, self.vision(), self.quote, inline=True)
        state = self.single_table(); state['elements'].pop()
        with self.assertRaisesRegex(ValueError, 'Undeclared'):
            compile_container_registry(state, self.vision(), self.quote, inline=True)

    def test_inline_keeps_source_checks_and_duplicate_checks(self):
        state = self.single_table(); state['elements'][1]['evidence_quote'] = 'fabricated'
        with self.assertRaisesRegex(ValueError, 'source quote'):
            compile_container_registry(state, self.vision(), self.quote, inline=True)
        state = self.single_table(); state['elements'].append(copy.deepcopy(state['elements'][1]))
        with self.assertRaisesRegex(ValueError, 'identity'):
            compile_container_registry(state, self.vision(), self.quote, inline=True)

    def test_inline_visual_container_has_same_source_as_explicit_registry(self):
        state = self.state(); state['containers'][0].update(id='region', vision_id='region', origin='vision')
        state['relationships'][0]['parent_id'] = 'region'
        vision = self.vision(); vision['elements'].append({'id': 'region', 'type': 'card'})
        explicit = compile_container_registry(state, vision, self.quote)
        state['elements'].extend(state.pop('containers'))
        inline = compile_container_registry(state, vision, self.quote, inline=True)
        self.assertEqual(explicit['elements'], inline['elements'])

    def test_inline_real_architect_path_preserves_declared_parent_and_source(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.single_table())))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE': 'hierarchy_registry_inline_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=client):
            result = ui_architect.generate_ui_state(self.quote, self.vision())
        self.assertNotIn('error', result)
        self.assertEqual(result['elements'][0]['parent_id'], 'u_card')
        self.assertEqual(result['elements'][1]['source_refs'][0]['source'], 'spoken_intent')


if __name__ == '__main__':
    unittest.main()
