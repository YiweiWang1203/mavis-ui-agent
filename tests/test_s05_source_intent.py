import copy,json,unittest
from scripts.run_s05_source_intent import prepare_requests,MODEL,PREFIX,MARKER,ROLE
class TestSourceIntent(unittest.TestCase):
    def setUp(self):
        self.state={'elements':[{'id':'e1','type':'text','spatial_info':{'bbox':[1,2,3,4]}}]};self.system='fixed system';self.raw=' 不得改写的原文\n原始输入未明确。\n'
        self.request={'model':MODEL,'messages':[{'role':'system','content':self.system},{'role':'user','content':PREFIX+json.dumps(self.state,ensure_ascii=False,indent=2)}],'temperature':.2,'max_tokens':8192}
    def test_only_block_diff_and_raw_verbatim(self):
        a,b=prepare_requests(self.request,self.state,self.raw,self.system);self.assertEqual(a,self.request);self.assertEqual(b['messages'][1]['content'],a['messages'][1]['content']+MARKER+ROLE+self.raw);self.assertEqual(self.state['elements'][0]['spatial_info']['bbox'],[1,2,3,4])
    def test_changed_state_rejected(self):
        with self.assertRaises(ValueError):prepare_requests(self.request,{'elements':[]},self.raw,self.system)
    def test_changed_system_or_budget_rejected(self):
        r=copy.deepcopy(self.request);r['max_tokens']=4096
        with self.assertRaises(ValueError):prepare_requests(r,self.state,self.raw,self.system)
    def test_missing_source_rejected(self):
        with self.assertRaises(ValueError):prepare_requests(self.request,self.state,'',self.system)
if __name__=='__main__':unittest.main()
