import json
import unittest
from types import SimpleNamespace
from src.agents.relation_specialist import compile_container_slots, refine_relation_state
from src.agents.ui_architect import finalize_ui_state
from tests import test_architect_visual_context as fixture_module


class ContainerSlotTests(unittest.TestCase):
    def run_proposal(self, output):
        fixture = fixture_module.ArchitectVisualContextTests()
        state, vision = fixture.inputs()
        seen = []
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output)))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        proposal = refine_relation_state(state, fixture.quote, 'model', client, mode='container_slots_v1')
        return proposal, seen, fixture, vision

    def test_typed_parent_slots_and_immutable_nodes(self):
        p, seen, f, v = self.run_proposal({'children_by_container':{'region':[{'child_id':'send','evidence_quote':'The card contains Send.'}]}})
        payload = json.loads(seen[0]['messages'][1]['content'])
        self.assertEqual(set(payload['container_slots']), {'region'})
        self.assertEqual(p['relationships'][0]['parent_id'], 'region')
        result = finalize_ui_state(p, f.quote, v, 'hierarchy_registry_image_v1')
        self.assertEqual(result['elements'][0]['parent_id'], 'region')

    def test_button_or_unknown_slot_cannot_be_used_as_parent(self):
        for key in ('send', 'invented'):
            with self.assertRaisesRegex(ValueError, 'undeclared'):
                self.run_proposal({'children_by_container':{'region':[], key:[]}})

    def test_no_parent_override_allowed_in_child(self):
        with self.assertRaisesRegex(ValueError, 'choose or edit parent'):
            compile_container_slots({'children_by_container':{'region':[{'child_id':'send','parent_id':'send','evidence_quote':'x'}]}}, {'region':{}})

    def test_missing_slot_and_extra_fields_are_fatal(self):
        for output in ({'children_by_container':{}}, {'children_by_container':{'region':[]}, 'elements':[]}):
            with self.assertRaises(ValueError):
                self.run_proposal(output)

    def test_empty_slots_do_not_invent_relationships(self):
        p, _, _, _ = self.run_proposal({'children_by_container':{'region':[]}})
        self.assertEqual(p['relationships'], [])

    def test_source_quote_and_reference_checks_remain(self):
        for child, quote in [('send','invented words'), ('missing','The card contains Send.')]:
            p, _, f, v = self.run_proposal({'children_by_container':{'region':[{'child_id':child,'evidence_quote':quote}]}})
            if child == 'missing':
                with self.assertRaisesRegex(ValueError, 'endpoint'):
                    finalize_ui_state(p,f.quote,v,'hierarchy_registry_image_v1')
            else:
                result=finalize_ui_state(p,f.quote,v,'hierarchy_registry_image_v1')
                self.assertEqual(result['page_meta']['relation_evidence']['unresolved_count'],1)
                self.assertFalse(result['elements'][0].get('parent_id'))


if __name__ == '__main__':
    unittest.main()
