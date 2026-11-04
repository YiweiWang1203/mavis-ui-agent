"""Regression for nested observations lost before the planner request."""
import ast
from copy import deepcopy
from pathlib import Path
import unittest

from src.schemas.vision_schema import UIElement


class NestedVisionEvidenceTests(unittest.TestCase):
    def test_normalizer_preserves_nested_evidence_and_schema_accepts_it(self):
        # Exercise the real pure normalizer without importing ASR/model clients.
        source = Path("src/tools/vision_tool.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {"_normalize_element", "_parse_bbox_candidate", "_map_type"}
        selected = [node for node in tree.body if
                    isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = {"deepcopy": deepcopy, "TYPE_ALIAS": {}, "Optional": __import__("typing").Optional,
                     "Tuple": tuple, "Dict": dict}
        exec(compile(ast.Module(body=selected, type_ignores=[]), source, "exec"), namespace)
        child = {"id": "row", "type": "list_item", "text": "entry",
                 "bbox": {"x_min": .1, "y_min": .2, "x_max": .5, "y_max": .3},
                 "items": [{"id": "detail", "text": "detail"}]}
        raw = {"id": "list", "type": "list", "bbox": {
            "x_min": .1, "y_min": .1, "x_max": .6, "y_max": .8}, "items": [child]}
        normalized, error = namespace["_normalize_element"](raw, 400, 700, 0)
        self.assertIsNone(error)
        self.assertEqual(normalized["items"], raw["items"])
        UIElement.model_validate(normalized)
        raw["items"][0]["text"] = "mutated"
        self.assertEqual(normalized["items"][0]["text"], "entry")
        self.assertEqual(normalized["items_source"]["coordinate_space"], "original_vision_response")
        raw["items"] = "bad"
        self.assertEqual(namespace["_normalize_element"](raw, 400, 700, 0)[1], "invalid_nested_items")


if __name__ == "__main__":
    unittest.main()
