import copy
import unittest
from scripts.run_s03_behavior import prepare_requests,MODEL,MARKER

class TestRequests(unittest.TestCase):
    def fixture(self):
        req={'model':MODEL,'temperature':.2,'max_tokens':8192,'messages':[{'role':'system','content':'fixed'},{'role':'user','content':'state'}]}
        contract={'version':'v2','requirements':[{'case_id':'008','requirement_id':str(i)} for i in range(8)]+[{'case_id':'001','requirement_id':'exclude'}]}
        return req,contract
    def test_only_append_case_block(self):
        r,c=self.fixture();old=copy.deepcopy(r);a,b,block=prepare_requests(r,c)
        self.assertEqual(a,old);self.assertEqual(r,old);self.assertEqual(a['messages'][0],b['messages'][0]);self.assertEqual(len(block['requirements']),8)
        self.assertTrue(b['messages'][1]['content'].startswith(a['messages'][1]['content']+MARKER));self.assertNotIn('exclude',str(block))
    def test_wrong_model_rejected(self):
        r,c=self.fixture();r['model']='other'
        with self.assertRaises(ValueError):prepare_requests(r,c)
    def test_scope_rejected(self):
        r,c=self.fixture();c['requirements']=c['requirements'][:7]
        with self.assertRaises(ValueError):prepare_requests(r,c)
if __name__=='__main__':unittest.main()
