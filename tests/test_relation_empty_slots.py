import copy
import os
import unittest
from unittest.mock import patch
from src.agents.relation_specialist import refine_relation_state
from src.utils.relation_aggregation import aggregate_relation_sources
from tests import test_relation_specialist as specialist_fixtures


class EmptySlotGuardTests(unittest.TestCase):
    def state(self):
        return {'page_meta':{},'elements':[{'id':'send','type':'button','text':'Send'}], 'relationships':[]}

    def test_no_legal_parent_skips_model_and_preserves_nodes(self):
        state=self.state(); original=copy.deepcopy(state)
        result=refine_relation_state(state,'Send','model',None,mode='container_slots_guard_v1')
        self.assertEqual(state,original)
        self.assertEqual(result['elements'],state['elements'])
        self.assertEqual(result['page_meta']['relation_specialist']['additional_calls'],0)
        self.assertEqual(result['page_meta']['relation_specialist']['status'],'skipped_no_eligible_container')
        self.assertEqual(result['relation_evidence_sources'][0]['relationships'],[])
        self.assertEqual(result['relationships'],[])

    def test_skip_does_not_hide_original_invalid_parent(self):
        state=self.state()
        state['elements'].append({'id':'child','type':'button','text':'Child'})
        state['relationships']=[{'parent_id':'send','child_id':'child','evidence_quote':'Send contains Child.'}]
        proposal=refine_relation_state(state,'Send contains Child.','model',None,mode='container_slots_guard_v1')
        with self.assertRaisesRegex(ValueError,'not a container'):
            aggregate_relation_sources(proposal,'Send contains Child.')

    def test_existing_container_still_calls_and_rejects_illegal_slots(self):
        fixture=specialist_fixtures.RelationSpecialistTests()
        client,seen=fixture.client([{'children_by_container':{'send':[]}}])
        state=self.state(); state['elements'].append({'id':'region','type':'card','text':'Card'})
        with self.assertRaisesRegex(ValueError,'undeclared'):
            refine_relation_state(state,'','model',client,mode='container_slots_guard_v1')
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0]['max_tokens'],8192)
        self.assertEqual(seen[0]['timeout'],600)

    def test_real_generation_guard_keeps_input_without_extra_request(self):
        from src.agents import ui_architect
        from tests.test_architect_visual_context import ArchitectVisualContextTests
        f=ArchitectVisualContextTests();state,vision=f.inputs()
        state['elements']=[e for e in state['elements'] if e['id']!='region']
        state['elements'][0]['parent_id']=None
        state['relationships']=[]
        vision['elements']=[e for e in vision['elements'] if e['id']!='region']
        client,seen=specialist_fixtures.RelationSpecialistTests().client([state])
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_registry_image_v1','UI_RELATION_SPECIALIST_MODE':'container_slots_guard_v1','UI_RELATION_AGGREGATION_MODE':'validated_union_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            result=ui_architect.generate_ui_state(f.quote,vision,image_data_url=f.image)
        self.assertEqual(len(seen),1)
        self.assertEqual(len(result['elements']),1)
        self.assertEqual(result['page_meta']['relation_specialist']['additional_calls'],0)


if __name__=='__main__':unittest.main()
