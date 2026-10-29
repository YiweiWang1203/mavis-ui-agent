import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from scripts.s01_transport import Guard,Transport,terminal,counts,safe_error,freeze_clock

class Failure(Exception):
    status_code=402
    body={'error':{'code':'insufficient_balance','type':'billing_error','message':'Authorization: Bearer sk-private https://example.test?token=private'},'headers':{'authorization':'private'}}

class Tests(unittest.TestCase):
    def test_real_first_and_later_prompt_only_clock(self):
        root=Path(__file__).resolve().parents[2]/'sprint_S01_20261029_v1/retrieved/S01_20261029T122227Z_ecd4953/results'
        a=json.loads((root/'001_R/call_01.json').read_text(encoding='utf-8'))['request']
        b=json.loads((root/'001_S/call_01.json').read_text(encoding='utf-8'))['request']
        self.assertNotEqual(a['messages'][0],b['messages'][0])
        self.assertEqual(freeze_clock(a['messages'],'frozen'),freeze_clock(b['messages'],'frozen'))
        g=Guard('frozen')
        self.assertEqual(g.check('001','R','vision',a)['messages'],g.check('001','S','vision',b)['messages'])
        b['messages'][0]['content']+='real semantic mutation'
        with self.assertRaises(ValueError):g.check('001','S','vision',b)
    def test_terminal_counts(self):
        self.assertEqual(terminal([{'status':'failed'}]*9),'completed_all_failed')
        self.assertEqual(terminal([{'status':'html_generated_pending_browser'}]*9),'completed_generation')
        self.assertEqual(terminal([{'status':'html_generated_pending_browser'}]+[{'status':'failed'}]*8),'completed_with_failures')
        self.assertEqual(terminal([]),'interrupted_incomplete')
        self.assertEqual(counts([{'status':'failed'}]+[{'status':'NOT_EXECUTED_SERVICE_BLOCKED'}]*8)['not_executed'],8)
    def test_request_visible_and_402_circuit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            p=Path(d);g=Guard('frozen');run={};physical=[]
            def api(**kwargs):
                physical.append(1)
                self.assertEqual(json.loads((p/'call_01.json').read_text())['status'],'request_started')
                self.assertEqual(json.loads((p/'run.json').read_text())['current_stage'],'direct')
                raise Failure()
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=api)))
            t=Transport(client,p,{'direct':'mock'},1,g,run,p,'001','D',lambda x:x);t.stage='direct'
            for _ in range(2):
                with self.assertRaises(RuntimeError):t.create(messages=[{'role':'user','content':'test'}],temperature=.2)
            self.assertEqual(len(physical),1)
            c=json.loads((p/'call_01.json').read_text());self.assertEqual(c['http_status'],402)
            self.assertEqual(c['error']['code'],'insufficient_balance')
            self.assertNotIn('private',json.dumps(c));self.assertNotIn('headers',c['error'])
            self.assertIn('finished_utc',c)
    def test_input_and_parameters_guard(self):
        g=Guard('clock');g.bind_inputs('001',{'image':'a','transcript':'b'})
        with self.assertRaises(ValueError):g.bind_inputs('001',{'image':'a','transcript':'changed'})
        with self.assertRaises(ValueError):g.check('001','R','vision',{'messages':[],'temperature':.2,'max_tokens':8192})
    def test_sensitive_error_fields(self):
        e=Failure();e.body={'error':{'message':'ordinary billing restriction','code':'https://a/?key=secret','headers':'secret'}}
        v=safe_error(e);self.assertEqual(v['message'],'ordinary billing restriction');self.assertEqual(v['code'],'[REDACTED_SENSITIVE_FIELD]')
if __name__=='__main__':unittest.main()
