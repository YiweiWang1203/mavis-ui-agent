import json
import unittest
from src.utils.coder_execution_input import coder_execution_state, coder_user_content


class CoderExecutionInputTests(unittest.TestCase):
    def test_business_fields_preserved_review_excluded_without_mutation(self):
        state = {
            "page_meta": {"viewport": {"width": 900, "height": 600}, "contract_version": 2,
                          "structure_mode": "region_tree_v1", "semantic_review_passed": False,
                          "semantic_review": {"verdict": "revise", "issues": [{"resolved_actual": "diagnostic"}]}},
            "region_tree": {"id": "page", "axis": "column", "children": [{"id": "x"}]},
            "elements": [{"id": "x", "items": [{"content": "row body", "value": 17}],
                          "asset_content": "requested subject"}],
            "requirements": [{"evidence": [{"text": "original source"}]}],
            "actions": [{"target": "x", "trigger": "click", "observable_result": "editor"}],
        }
        before = json.dumps(state, sort_keys=True)
        projected = coder_execution_state(state)
        for key in ("region_tree", "elements", "requirements", "actions"):
            self.assertEqual(projected[key], state[key])
        self.assertNotIn("semantic_review", projected["page_meta"])
        self.assertNotIn("semantic_review_passed", projected["page_meta"])
        request = coder_user_content(projected, "original request", "raw ASR")
        self.assertIn("[Original User Request]\noriginal request", request)
        self.assertIn("[Fresh ASR Transcript]\nraw ASR", request)
        self.assertIn('"observable_result": "editor"', request)
        self.assertNotIn("resolved_actual", request)
        self.assertEqual(json.dumps(state, sort_keys=True), before)
        self.assertFalse(state["page_meta"]["semantic_review_passed"])
        projected["elements"][0]["items"][0]["content"] = "changed"
        self.assertEqual(state["elements"][0]["items"][0]["content"], "row body")
