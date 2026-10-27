import copy
import unittest
import os
import json
from types import SimpleNamespace
from unittest.mock import patch
from src.utils.relation_aggregation import aggregate_relation_sources


class RelationAggregationTests(unittest.TestCase):
    quote='The card contains Send and Cancel.'
    def state(self,first,second):
        return {'page_meta':{},'elements':[{'id':'card','type':'card','text':''},
            {'id':'send','type':'button','text':'Send'}, {'id':'cancel','type':'button','text':'Cancel'}],
            'relation_evidence_sources':[{'source':'architect','relationships':first}, {'source':'specialist','relationships':second}]}
    def edge(self,child='send',quote=None,parent='card'):
        return {'parent_id':parent,'child_id':child,'evidence_quote':quote or self.quote}

    def test_later_omission_does_not_remove_valid_original_edge(self):
        state=self.state([self.edge(),self.edge('cancel')],[self.edge()]);original=copy.deepcopy(state)
        result=aggregate_relation_sources(state,self.quote)
        self.assertEqual(result['page_meta']['relation_evidence']['accepted_count'],2)
        self.assertEqual(len(result['relationships']),2)
        self.assertEqual(state,original)
        self.assertEqual(result['page_meta']['relation_aggregation']['source_reports'][1]['accepted_count'],1)

    def test_matching_sources_are_not_duplicate_relationships(self):
        result=aggregate_relation_sources(self.state([self.edge()],[self.edge()]),self.quote)
        self.assertEqual(len(result['relationships']),1)
        self.assertEqual(len(result['page_meta']['relation_aggregation']['support'][0]['sources']),2)

    def test_fabricated_source_is_unresolved_not_accepted(self):
        result=aggregate_relation_sources(self.state([self.edge('cancel','fake quotation')],[self.edge()]),self.quote)
        self.assertEqual(result['page_meta']['relation_evidence']['accepted_count'],1)
        self.assertEqual(result['page_meta']['relation_evidence']['unresolved_count'],1)

    def test_invalid_parent_source_cannot_be_ignored(self):
        with self.assertRaisesRegex(ValueError,'not a container'):
            aggregate_relation_sources(self.state([self.edge('cancel',parent='send')],[self.edge()]),self.quote)

    def test_conflicting_sources_fail_instead_of_choosing_winner(self):
        state=self.state([self.edge()],[self.edge(parent='other')])
        state['elements'].append({'id':'other','type':'card','text':''})
        with self.assertRaisesRegex(ValueError,'Conflicting parent'):
            aggregate_relation_sources(state,self.quote)

    def test_cross_source_cycle_is_rejected(self):
        state={'page_meta':{},'elements':[{'id':'a','type':'card','text':'A'},{'id':'b','type':'card','text':'B'}],
            'relation_evidence_sources':[{'source':'architect','relationships':[self.edge('b',parent='a',quote='A contains B')]},
                {'source':'specialist','relationships':[self.edge('a',parent='b',quote='B contains A')]}]}
        with self.assertRaisesRegex(ValueError,'cycle'):
            aggregate_relation_sources(state,'A contains B; B contains A')

    def test_real_generation_path_retains_relation_when_specialist_is_empty(self):
        from src.agents import ui_architect
        from tests import test_architect_visual_context as fixtures
        f=fixtures.ArchitectVisualContextTests();state,vision=f.inputs()
        outputs=[state,{'children_by_container':{'region':[]}}];seen=[]
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(outputs[len(seen)-1])))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_registry_image_v1','UI_RELATION_SPECIALIST_MODE':'container_slots_v1','UI_RELATION_AGGREGATION_MODE':'validated_union_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            result=ui_architect.generate_ui_state(f.quote,vision,image_data_url=f.image)
        self.assertEqual(len(seen),2)
        self.assertEqual(result['page_meta']['relation_evidence']['accepted_count'],1)
        self.assertEqual(result['elements'][0]['parent_id'],'region')


if __name__=='__main__':unittest.main()
