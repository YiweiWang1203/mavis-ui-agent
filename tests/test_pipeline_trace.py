"""Trace invariants and deterministic pipeline integration, zero API calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.utils.pipeline_trace import PipelineTrace, traced_stage, trace_event, state_changes, html_contract_summary
from src.agents import ui_architect


class PipelineTraceTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'outputs/optimization/trace_test_tmp'
        root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def events(self,folder):
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        for e in manifest['events']:
            self.assertEqual(hashlib.sha256((folder/e['file']).read_bytes()).hexdigest(),e['sha256'])
        return [json.loads((folder/e['file']).read_text(encoding='utf-8')) for e in manifest['events']]

    def test_snapshot_before_mutation_and_return_identity(self):
        @traced_stage('mutate')
        def operation(ui_state):
            ui_state['elements'][0]['text']='new'
            return ui_state
        value={'elements':[{'id':'e1','text':'old'}]}
        folder=self.root/'trace'
        with PipelineTrace(folder): result=operation(value)
        self.assertIs(result,value)
        events=self.events(folder)
        self.assertEqual(events[0]['inputs']['ui_state']['elements'][0]['text'],'old')
        self.assertEqual(events[1]['changes']['changed_elements'][0]['fields']['text']['after'],'new')

    def test_nested_context_restores_and_disabled_records_nothing(self):
        outer,inner=self.root/'outer',self.root/'inner'
        with PipelineTrace(outer):
            trace_event('a',value=1)
            with PipelineTrace(inner): trace_event('b',value=2)
            trace_event('c',value=3)
        trace_event('ignored',value=4)
        self.assertEqual([e['stage'] for e in self.events(outer)],['a','c'])
        self.assertEqual([e['stage'] for e in self.events(inner)],['b'])

    def test_error_type_only_and_explicit_credentials_redacted(self):
        @traced_stage('failure')
        def failure(value): raise RuntimeError('PRIVATE_EXCEPTION_SECRET')
        folder=self.root/'failure'
        with self.assertRaises(RuntimeError),PipelineTrace(folder): failure({'api_key':'PRIVATE_KEY'})
        text=''.join(p.read_text(encoding='utf-8') for p in folder.glob('*.json'))
        self.assertNotIn('PRIVATE_KEY',text)
        self.assertNotIn('PRIVATE_EXCEPTION_SECRET',text)
        self.assertEqual(self.events(folder)[-1]['error_type'],'RuntimeError')

    def test_real_architect_same_response_same_result_trace_on_and_off(self):
        vision={'canvas':{'width':375,'height':812,'orientation':'portrait'},'elements':[
            {'id':'e1','type':'input','text':'','bbox':{'x_min':0.1,'y_min':0.1,'x_max':0.8,'y_max':0.2}}]}
        state={'page_meta':{'viewport':{'width':375,'height':812}},'elements':[
            {'id':'renamed','type':'input','spatial_info':{'bbox':[30,70,280,140]}}]}
        raw=json.dumps(state); requests=[]
        def create(**kw):
            requests.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
        fake=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        folder=self.root/'architect'; original=copy.deepcopy(vision)
        with patch.object(ui_architect,'_get_openai_client',return_value=fake):
            off=ui_architect.generate_ui_state('simple form',vision)
            with PipelineTrace(folder): on=ui_architect.generate_ui_state('simple form',vision)
        self.assertEqual(on,off); self.assertEqual(vision,original); self.assertEqual(requests[0],requests[1])
        events=self.events(folder)
        merge=next(e for e in events if e['stage']=='architect.geometry_merge.output')
        self.assertEqual(merge['changes']['count_delta'],1)
        decisions=next(e for e in events if e['stage']=='architect.geometry_merge.decisions')['decisions']
        self.assertEqual(decisions[-1]['reason'],'vision_id_not_used_by_model')
        self.assertTrue(any(e['stage']=='architect.priors.output' for e in events))
        self.assertTrue(any(e['stage']=='architect.layout.output' for e in events))

    def test_duplicate_ids_not_silently_collapsed(self):
        state={'elements':[{'id':'x','text':'a'},{'id':'x','text':'b'}]}
        report=state_changes(state,state)
        self.assertEqual(report['before']['element_count'],2)
        self.assertEqual(report['before']['duplicate_ids'],{'x':2})
        self.assertEqual(report['field_comparison'],'ambiguous_duplicate_ids')

    def test_static_dom_missing_identity_separate_from_native_count(self):
        report=html_contract_summary('<input id="username">',{'elements':[{'id':'e3','type':'input'}]})
        self.assertEqual(report['declared_inputs'][0]['dom_matches'],[])
        self.assertEqual(len(report['native_controls']),1)

    def test_trace_directory_cannot_overwrite_prior_run(self):
        folder=self.root/'existing'; PipelineTrace(folder)
        with self.assertRaises(FileExistsError): PipelineTrace(folder)


if __name__=='__main__': unittest.main()
