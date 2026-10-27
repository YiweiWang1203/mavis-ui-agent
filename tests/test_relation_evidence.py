import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.utils.relation_evidence import apply_relation_evidence
from src.agents import ui_architect

class RelationEvidenceTests(unittest.TestCase):
    quote='The card contains Send.'
    def state(self):
        return {'page_meta':{'viewport':{'width':375,'height':812}},'elements':[
            {'id':'region','vision_id':'region','type':'card','text':'','spatial_info':{'bbox':[0,400,375,600]}},
            {'id':'send','vision_id':'send','type':'button','text':'Send','spatial_info':{'bbox':[0,650,120,700]}}],
            'relationships':[{'parent_id':'region','child_id':'send','evidence_quote':self.quote}]}
    def test_valid_source_quote_sets_parent_and_preserves_original(self):
        state=self.state();old=copy.deepcopy(state);r=apply_relation_evidence(state,self.quote)
        self.assertEqual(r['elements'][1]['parent_id'],'region')
        self.assertEqual(r['page_meta']['relation_evidence']['accepted_count'],1)
        self.assertEqual(state,old)
    def test_fabricated_source_missing_label_and_noncontainer_are_rejected(self):
        for quote in ['The card contains Next.','Send is below the panel.']:
            s=self.state();s['relationships'][0]['evidence_quote']=quote
            with self.assertRaises(ValueError):apply_relation_evidence(s,self.quote)
        s=self.state();s['relationships'][0]['evidence_quote']='The card has a control.'
        with self.assertRaisesRegex(ValueError,'child label'):apply_relation_evidence(s,'The card has a control.')
        s=self.state();s['elements'][0]['type']='image'
        with self.assertRaisesRegex(ValueError,'container'):apply_relation_evidence(s,self.quote)
    def test_missing_unknown_duplicate_endpoints_fail_closed(self):
        s=self.state();s.pop('relationships')
        with self.assertRaises(ValueError):apply_relation_evidence(s,self.quote)
        s=self.state();s['relationships'][0]['child_id']='missing'
        with self.assertRaises(ValueError):apply_relation_evidence(s,self.quote)
        s=self.state();s['relationships']*=2
        with self.assertRaises(ValueError):apply_relation_evidence(s,self.quote)
    def test_unquoted_parent_not_retained_and_nav_alias_normalized(self):
        s=self.state();s['relationships']=[];s['elements'][1]['parent_id']='region';s['elements'][0]['type']='nav_bar'
        r=apply_relation_evidence(s,'No relationship specified.')
        self.assertIsNone(r['elements'][1]['parent_id'])
        self.assertEqual(r['elements'][0]['type'],'navigation_bar')
    def test_relation_cycles_rejected(self):
        s=self.state();s['elements'][0]['text']='Alpha';s['elements'][1].update(type='card',text='Beta')
        quote='The Alpha card contains Beta, and the Beta card contains Alpha.'
        s['relationships']=[{'parent_id':'region','child_id':'send','evidence_quote':quote},{'parent_id':'send','child_id':'region','evidence_quote':quote}]
        with self.assertRaisesRegex(ValueError,'cycle'):apply_relation_evidence(s,quote)
    def test_real_architect_path_applies_ledger_before_geometry(self):
        state=self.state();seen=[]
        def create(**kw):
            seen.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(state)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        vision={'elements':[
            {'id':'region','type':'card','bbox':{'x_min':0,'y_min':.5,'x_max':1,'y_max':.7}},
            {'id':'send','type':'button','text':'Send','bbox':{'x_min':0,'y_min':.8,'x_max':.3,'y_max':.9}}]}
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_evidence_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            result=ui_architect.generate_ui_state(self.quote,vision)
        self.assertNotIn('error',result)
        self.assertEqual(result['elements'][1]['parent_id'],'region')
        self.assertLessEqual(result['elements'][1]['spatial_info']['bbox'][3],result['elements'][0]['spatial_info']['bbox'][3])
        self.assertIn('relationships',seen[0]['messages'][0]['content'])
    def test_partial_policy_retains_valid_edge_without_accepting_asr_alias(self):
        state=self.state();state['elements'].append({'id':'next','type':'button','text':'Next'})
        quote='The card contains Nxt.'
        state['relationships'].append({'parent_id':'region','child_id':'next','evidence_quote':quote})
        original=copy.deepcopy(state);intent=self.quote+' '+quote
        with self.assertRaisesRegex(ValueError,'child label'):apply_relation_evidence(state,intent)
        result=apply_relation_evidence(state,intent,isolate_source_errors=True)
        self.assertEqual(result['elements'][1]['parent_id'],'region')
        self.assertIsNone(result['elements'][2]['parent_id'])
        meta=result['page_meta']['relation_evidence']
        self.assertEqual(meta['accepted_count'],1);self.assertEqual(meta['unresolved_count'],1)
        self.assertEqual(meta['unresolved_edges'][0]['reason'],'child_label_not_anchored')
        self.assertEqual(state,original)
    def test_fabricated_quote_is_unresolved_never_accepted(self):
        state=self.state();result=apply_relation_evidence(state,'No such quote exists.',isolate_source_errors=True)
        self.assertIsNone(result['elements'][1]['parent_id'])
        self.assertEqual(result['page_meta']['relation_evidence']['accepted_count'],0)
        self.assertEqual(result['page_meta']['relation_evidence']['unresolved_count'],1)
    def test_partial_policy_never_masks_global_conflict_or_cycle(self):
        state=self.state();state['relationships'].append({'parent_id':'region','child_id':'send','evidence_quote':'fabricated'})
        with self.assertRaisesRegex(ValueError,'conflicting'):apply_relation_evidence(state,self.quote,isolate_source_errors=True)
        state=self.state();state['elements'][1]['type']='card'
        state['relationships'].append({'parent_id':'send','child_id':'region','evidence_quote':'fabricated'})
        with self.assertRaisesRegex(ValueError,'cycle'):apply_relation_evidence(state,self.quote,isolate_source_errors=True)
    def test_partial_policy_never_masks_invalid_identity(self):
        state=self.state();state['relationships'][0]['child_id']='missing'
        with self.assertRaisesRegex(ValueError,'endpoint'):apply_relation_evidence(state,self.quote,isolate_source_errors=True)
    def test_partial_architect_mode_uses_same_prompt_and_reports_unresolved(self):
        state=self.state();state['relationships'][0]['evidence_quote']='fabricated';seen=[]
        def create(**kw):
            seen.append(kw);return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(state)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        vision={'elements':[{'id':'region','type':'card','bbox':{'x_min':0,'y_min':.5,'x_max':1,'y_max':.7}},{'id':'send','type':'button','text':'Send','bbox':{'x_min':0,'y_min':.8,'x_max':.3,'y_max':.9}}]}
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_evidence_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            strict=ui_architect.generate_ui_state(self.quote,vision)
        with patch.dict(os.environ,{'UI_STRUCTURE_MODE':'hierarchy_partial_evidence_v1'}),patch.object(ui_architect,'_get_openai_client',return_value=client):
            partial=ui_architect.generate_ui_state(self.quote,vision)
        self.assertIn('error',strict);self.assertNotIn('error',partial)
        self.assertEqual(seen[0]['messages'],seen[1]['messages'])
        self.assertEqual(partial['page_meta']['relation_evidence']['unresolved_count'],1)
if __name__=='__main__':unittest.main()
