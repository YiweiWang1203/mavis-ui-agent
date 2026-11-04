import unittest
from src.utils.region_execution import attach_region_styles
from src.utils.region_tree import compile_region_tree


class RegionExecutionTests(unittest.TestCase):
    def test_actions_content_and_layout_survive_compilation_and_save_preparation(self):
        plan = {
            "page_meta": {"viewport": {"width": 800, "height": 600}},
            "requirements": [],
            "elements": [{"id": "x", "type": "button", "origin": "speech",
                          "asset_content": "a recognizable shape", "items": [{"text": "row"}]}],
            "actions": [{"sources": ["s1"], "target": "x", "trigger": "click",
                         "state_change": "open editor", "observable_result": "editable content"}],
            "region_tree": {"id": "page", "axis": "column", "children": [
                {"id": "x", "slot": "bottom", "cross_align": "end", "grow": False}]}}
        state = compile_region_tree(plan, {"s1": {"text": "open editor", "start": 0, "end": 11}},
                                    schema_version=2)
        self.assertEqual(state["actions"], plan["actions"])
        self.assertEqual(state["elements"][0]["asset_content"], "a recognizable shape")
        html = attach_region_styles("<html><head></head><body></body></html>", state["region_tree"])
        self.assertIn("align-self:flex-end !important", html)
        self.assertIn("margin-top:auto !important", html)
        self.assertLess(html.index("data-region-contract"), html.index("</head>"))
        plan["actions"][0]["target"] = "missing"
        with self.assertRaisesRegex(ValueError, "actions"):
            compile_region_tree(plan, {}, schema_version=2)

    def test_missing_head_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "ONE_HEAD"):
            attach_region_styles("<html></html>", {"id": "page"})
