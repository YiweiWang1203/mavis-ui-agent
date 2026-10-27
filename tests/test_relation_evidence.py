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
if __name__=='__main__':unittest.main()
