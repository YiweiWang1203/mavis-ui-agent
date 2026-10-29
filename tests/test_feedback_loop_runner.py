import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class FeedbackRunnerTests(unittest.TestCase):
    def test_dry_run_creates_terminal_state_and_archive_without_model_calls(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder); case = root / 'case'; case.mkdir(); state = root / 'state'
            (case / 'prompt.txt').write_text('PC target 1440x900', encoding='utf-8')
            (case / 'transcript.txt').write_text('需要一个发送按钮。', encoding='utf-8')
            Image.new('RGB', (40, 60), 'white').save(case / 'image.jpg')
            (case / 'case.json').write_text(json.dumps({
                'prompt':'prompt.txt','image':'image.jpg','transcript':'transcript.txt',
                'transcript_source':'funasr'}), encoding='utf-8')
            subprocess.run([sys.executable, str(ROOT/'scripts/run_feedback_loop_comparison.py'),
                            '--case', str(case), '--state', str(state), '--dry-run'],
                           cwd=ROOT, check=True, capture_output=True, text=True)
            run = json.loads((state/'run.json').read_text(encoding='utf-8'))
            self.assertEqual(run['status'], 'dry_run_validated')
            self.assertEqual(run['call_limit'], 3)
            self.assertEqual(run['actual_model_calls'], 0)
            self.assertTrue(run['python_executable'])
            self.assertTrue(run['started_utc'])
            self.assertEqual(len(run['archive_sha256']), 64)
            effective = (Path(run['actual_batch'])/'effective_request.txt').read_text(encoding='utf-8')
            self.assertIn('目标设备：电脑网页；目标画布1440×900。', effective)
            self.assertIn('[Spoken transcript]', effective)
            self.assertEqual(len(run['effective_request_sha256']), 64)
            self.assertFalse(run['effect_round_counted'])
            self.assertEqual(Path(run['expected_archive']), state/'results.zip')
            with zipfile.ZipFile(state/'results.zip') as archive:
                names = archive.namelist()
            self.assertTrue(any(name.endswith('input_manifest.json') for name in names))
            self.assertTrue(any(name.endswith('artifact_manifest.json') for name in names))


if __name__ == '__main__':
    unittest.main()
