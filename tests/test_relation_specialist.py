import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.relation_specialist import refine_relation_state
from src.agents import ui_architect
from scripts.run_relation_specialist_comparison import CappedProvider, persist_arm
from tests import test_architect_visual_context as fixture_module


class RelationSpecialistTests(unittest.TestCase):
    def client(self, outputs):
        seen = []
        def create(**kwargs):
            seen.append(kwargs)
            item = outputs[len(seen)-1]
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(item)))])
        return SimpleNamespace(stage='ui_architect', chat=SimpleNamespace(completions=SimpleNamespace(create=create))), seen

    def test_shared_nodes_immutable_and_same_source_checks_apply(self):
        fixture = fixture_module.ArchitectVisualContextTests()
        state, vision = fixture.inputs()
        state['relationships'] = []
        original = copy.deepcopy(state)
        edge = dict(parent_id='region', child_id='send', evidence_quote=fixture.quote)
        client, seen = self.client([{'relationships':[edge]}])
        proposal = refine_relation_state(state, fixture.quote, 'model', client)
        result = ui_architect.finalize_ui_state(proposal, fixture.quote, vision, 'hierarchy_registry_image_v1')
        self.assertEqual(state, original)
        self.assertEqual(proposal['elements'], original['elements'])
        self.assertEqual(result['elements'][0]['parent_id'], 'region')
        self.assertEqual(client.stage, 'ui_architect')
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0]['max_tokens'], seen[0]['timeout']), (8192, 600))
        payload = json.loads(seen[0]['messages'][1]['content'])
        self.assertNotIn('relationships', payload)
        self.assertNotIn('parent_id', payload['immutable_nodes'][0])

    def test_fabricated_quote_cannot_bypass_existing_validator(self):
        fixture = fixture_module.ArchitectVisualContextTests()
        state, vision = fixture.inputs()
        client, _ = self.client([{'relationships':[dict(parent_id='region', child_id='send', evidence_quote='The card contains Send and Delete.')]}])
        proposal = refine_relation_state(state, fixture.quote, 'model', client)
        result = ui_architect.finalize_ui_state(proposal, fixture.quote, vision, 'hierarchy_registry_image_v1')
        self.assertEqual(result['page_meta']['relation_evidence']['unresolved_count'], 1)
        self.assertFalse(result['elements'][0].get('parent_id'))

    def test_node_edits_and_extra_fields_rejected(self):
        for extra in ('elements', 'page_meta'):
            client, seen = self.client([{'relationships':[], extra:[]}])
            with self.assertRaisesRegex(ValueError, 'only output'):
                refine_relation_state({'elements':[]}, '', 'model', client)
            self.assertEqual(len(seen), 1)

    def test_timeout_restores_stage_and_has_no_retry(self):
        client, seen = self.client([TimeoutError()])
        with self.assertRaises(TimeoutError):
            refine_relation_state({'elements':[]}, '', 'model', client)
        self.assertEqual(client.stage, 'ui_architect')
        self.assertEqual(len(seen), 1)

    def test_global_cap_includes_failed_requests(self):
        client, seen = self.client([TimeoutError(), {}, {}])
        provider = CappedProvider(client)
        with self.assertRaises(TimeoutError):
            provider.create()
        provider.create(); provider.create()
        with self.assertRaisesRegex(RuntimeError, 'cap reached'):
            provider.create()
        self.assertEqual(len(seen), 3)

    def test_opt_in_real_generator_invokes_specialist(self):
        fixture = fixture_module.ArchitectVisualContextTests()
        state, vision = fixture.inputs()
        edge = state['relationships'][0]
        state['relationships'] = []
        client, seen = self.client([state, {'relationships':[edge]}])
        with patch.dict(os.environ, {'UI_STRUCTURE_MODE':'hierarchy_registry_image_v1', 'UI_RELATION_SPECIALIST_MODE':'source_ledger_v1'}), patch.object(ui_architect, '_get_openai_client', return_value=client):
            result = ui_architect.generate_ui_state(fixture.quote, vision, image_data_url=fixture.image)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result['elements'][0]['parent_id'], 'region')

    def test_failure_summary_uses_actual_shared_calls(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'outputs/optimization_cycles') as folder:
            summary = persist_arm(Path(folder), {}, None, {'shared_call_count':1}, [])
        self.assertEqual(summary['effective_call_count'], 1)
        self.assertEqual(summary['shared_call_count'], 1)
        self.assertEqual(summary['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
