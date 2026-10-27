"""Result polling must not confuse terminal failures or stale records with running jobs."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts.check_optimization_run import snapshot


class OptimizationProbeTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).resolve().parents[1]/'outputs/optimization/probe_test_tmp'
        folder.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = self.root/'results'; self.result.mkdir()
        self.write(self.root/'run.json', {'status':'running','result_root':str(self.result)})

    def write(self, path, data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data),encoding='utf-8')

    def test_pending_has_no_false_completion(self):
        result=snapshot(self.root)
        self.assertEqual(result['status'],'running');self.assertEqual(result['archives'],[])

    def test_terminal_archive_detected_despite_stale_worker_record(self):
        self.write(self.result/'batch/batch.json', {'status':'generation_finished_pending_browser_validation','runs':[]})
        (self.result/'batch.zip').write_bytes(b'evidence')
        result=snapshot(self.root)
        self.assertEqual(result['status'],'completed_artifacts_worker_state_stale')

    def test_api_error_is_not_hidden_by_an_existing_html_file(self):
        arm=self.result/'batch/case/candidate';arm.mkdir(parents=True)
        self.write(self.root/'run.json', {'status':'failed','exit_code':1,'result_root':str(self.result)})
        self.write(self.result/'batch/batch.json', {'status':'generation_finished_with_failures','runs':[{'folder':str(arm)}]})
        self.write(arm/'run_summary.json', {'status':'incomplete_html','call_count':3})
        self.write(arm/'call_03.json', {'stage':'coder','status':'failed','http_status':500,'error_type':'InternalServerError'})
        (arm/'final_code.html').write_text('generation error')
        (self.result/'batch.zip').write_bytes(b'evidence')
        result=snapshot(self.root)
        self.assertEqual(result['status'],'finished_with_failures')
        self.assertEqual(result['runs'][0]['call_failures'][0]['http_status'],500)

    def test_terminal_without_archive_is_reported(self):
        self.write(self.root/'run.json', {'status':'finished','result_root':str(self.result)})
        self.assertIn('terminal_state_without_archive',snapshot(self.root)['issues'])

    def test_result_root_cannot_escape_recorded_round(self):
        self.write(self.root/'run.json', {'status':'running','result_root':str(self.root.parent)})
        with self.assertRaises(ValueError):snapshot(self.root)


if __name__=='__main__':
    unittest.main()
