import json
from pathlib import Path
import tempfile
import unittest
from scripts.check_optimization_run import snapshot


class ProbeSnapshotTests(unittest.TestCase):
    def test_flat_detector_archive_and_terminal_state_are_read(self):
        parent = Path(__file__).resolve().parents[1]/'outputs/test_tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            state = Path(temporary)
            root = state/'results'
            arm = root/'full_photo__opencv_lsd'
            arm.mkdir(parents=True)
            (state/'run.json').write_text(json.dumps({'status': 'finished_pending_review',
                                                     'result_root': str(root)}))
            (root/'batch.json').write_text(json.dumps({'status': 'pending_review',
                'runs': [{'view': 'full_photo', 'method': 'opencv_lsd'}]}))
            (arm/'run_summary.json').write_text(json.dumps({'status': 'detected_pending_boundary_review'}))
            root.with_suffix('.zip').write_bytes(b'archive-evidence')
            weight = state/'vendor/deeplsd_md.tar'
            weight.parent.mkdir()
            weight.write_bytes(b'partial-model')
            result = snapshot(state)
            self.assertEqual(result['status'], 'finished_pending_review')
            self.assertEqual(len(result['archives']), 1)
            self.assertEqual(len(result['runs']), 1)
            self.assertEqual(result['runs'][0]['call_count'], None)
            self.assertFalse(result['runs'][0]['html_exists'])
            self.assertEqual(result['weight_progress']['bytes'], 13)


if __name__ == '__main__':
    unittest.main()
