from pathlib import Path
import unittest
from scripts.run_optimization_background import resolve_case


class OptimizationCaseSelectionTests(unittest.TestCase):
    def test_explicit_regression_case_does_not_fall_back_to_008(self):
        root=Path(__file__).resolve().parents[1]
        selected=root/'outputs/pilot_cases/002_chat_asr_v1'
        self.assertEqual(resolve_case(root,selected),selected.resolve())

    def test_default_remains_008(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(resolve_case(root).name,'008_asr_20261022T105518Z_946eac')

    def test_case_path_cannot_escape_pilot_cases(self):
        root=Path(__file__).resolve().parents[1]
        for selected in (root,root/'outputs/pilot_cases/../secrets',root/'outputs/pilot_cases'):
            with self.assertRaises(ValueError):resolve_case(root,selected)


if __name__=='__main__':unittest.main()
