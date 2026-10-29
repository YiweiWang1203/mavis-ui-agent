import copy,json,unittest
from scripts.run_s04_map import prepare_requests,MODEL,MARKER,MEDIA_MARKER

class TestRequests(unittest.TestCase):
    def fixtures(self):
        state={'elements':[{'id':'media','type':'image','rpa_action':'map_view'}]}
        behavior={'requirements':[{'case_id':'008'} for _ in range(8)]}
        req={'model':MODEL,'temperature':.2,'max_tokens':8192,'messages':[{'role':'system','content':'fixed'},{'role':'user','content':'Generate runnable frontend code from the following UI-State JSON.\n\n'+json.dumps(state)+MARKER+json.dumps(behavior)}]}
        media={'source_object':{'id':'media','type':'image','rpa_action':'map_view'},'source_quote':'a map'}
        return req,state,media
    def test_only_media_append(self):
        req,s,m=self.fixtures();old=copy.deepcopy(req);a,b=prepare_requests(req,s,m,'draw a map here')
        self.assertEqual(req,old);self.assertEqual(a,old);self.assertEqual(a['messages'][0],b['messages'][0]);self.assertTrue(b['messages'][1]['content'].startswith(a['messages'][1]['content']+MEDIA_MARKER))
    def test_missing_role_rejected(self):
        r,s,m=self.fixtures();s['elements'][0]['type']='text'
        with self.assertRaises(ValueError):prepare_requests(r,s,m,'a map')
    def test_wrong_quote_rejected(self):
        r,s,m=self.fixtures()
        with self.assertRaisesRegex(ValueError,'QUOTE'):prepare_requests(r,s,m,'nothing')
    def test_lost_behavior_rejected(self):
        r,s,m=self.fixtures();r['messages'][1]['content']=r['messages'][1]['content'].split(MARKER)[0]
        with self.assertRaisesRegex(ValueError,'BEHAVIOR'):prepare_requests(r,s,m,'a map')
if __name__=='__main__':unittest.main()
