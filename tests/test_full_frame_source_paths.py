import json
import tempfile
import unittest
from pathlib import Path
from src.utils.full_frame_input import historical_package_path


class FullFrameSourcePathTests(unittest.TestCase):
    def test_project_record_is_resolved_without_reading_unrelated_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case=root/'outputs/pilot_cases/case';case.mkdir(parents=True)
            record=root/'outputs/preprocess/run/metadata/package.json';record.parent.mkdir(parents=True);record.write_text('{}')
            (case/'case.json').write_text(json.dumps({'preprocess_package':'outputs/preprocess/run/metadata/package.json'}))
            self.assertEqual(historical_package_path(case),record.resolve())
            (case/'case.json').write_text(json.dumps({'preprocess_package':str(root/'outside/metadata/package.json')}))
            with self.assertRaises(ValueError):historical_package_path(case)

    def test_local_case_record_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            case=Path(tmp)/'case';record=case/'preprocess/metadata/package.json';record.parent.mkdir(parents=True);record.write_text('{}')
            self.assertEqual(historical_package_path(case),record.resolve())


if __name__=='__main__':unittest.main()
