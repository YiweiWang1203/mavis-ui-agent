import unittest
from src.utils.region_audit_input import observation_content, audit_plan_view, resolve_pointer, plan_references
from src.utils.region_diagnostics import region_diagnostics


class AuditInputTests(unittest.TestCase):
    def test_nested_geometry_removed_without_mutating_original(self):
        original = {"elements": [{"id": "list", "bbox": {"x_min": .36, "y_min": .1, "x_max": .6, "y_max": .9},
                    "items": [{"id": "row", "text": "entry", "bbox": [0.08, .1, .2, .3]}],
                    "items_source": {"source": "vision_response", "canvas": {"width": 400, "height": 700}}}]}
        projected = observation_content(original)
        self.assertNotIn("bbox", str(projected))
        self.assertNotIn("canvas", str(projected))
        self.assertEqual(projected["elements"][0]["items"][0]["id"], "row")
        self.assertIn("bbox", original["elements"][0])
        plan_view = audit_plan_view(original)
        self.assertNotIn("bbox", plan_view["elements"][0]["items"][0])

    def test_business_fields_survive_both_views(self):
        item = {"id": "row", "title": "Case", "content": "Message",
                "value": 17, "role": "user", "x_min": "business label",
                "bbox": "a business term", "canvas": "fabric"}
        for project in (observation_content, audit_plan_view):
            self.assertEqual(project({"items": [item]}), {"items": [item]})

    def test_pointer_paths_and_missing_parent_location(self):
        plan = {"region_tree": {"children": []}, "a/b": {"~key": 3}}
        self.assertEqual(resolve_pointer(plan, "/region_tree/children"), [])
        self.assertEqual(resolve_pointer(plan, "/a~1b/~0key"), 3)
        for path in ("/region_tree/children/0", "/missing", "/a~2b", "wrong"):
            with self.assertRaises(ValueError):
                resolve_pointer(plan, path)

    def test_reference_ids_bind_to_program_generated_paths(self):
        plan = {"region_tree": {"id": "page", "children": [
            {"id": "panel", "children": [{"id": "field"}]}]}, "requirements": [{"intent": "request"}]}
        refs = plan_references(plan)
        self.assertEqual(refs["tree:field"]["path"], "/region_tree/children/0/children/0")
        self.assertEqual(refs["requirements:1"]["path"], "/requirements/0")
        self.assertEqual(refs["requirements"]["value"], plan["requirements"])

    def test_independent_errors_collected_together(self):
        plan = {
            "page_meta": {"viewport": {"width": 800, "height": 600}},
            "elements": [{"id": "field", "type": "input", "origin": "speech"},
                         {"id": "omitted", "type": "image", "origin": "vision"}],
            "region_tree": {"id": "page", "axis": "row", "children": [
                {"id": "field", "slot": "bottom"}]},
            "requirements": [{"sources": ["s1"], "intent": "a supported requirement",
                              "certainty": "explicit", "status": "bound",
                              "scope": "region", "targets": [], "references": []}],
            "actions": [{"sources": ["s1"], "target": "nested_row",
                         "trigger": "select", "state_change": "open", "observable_result": "details"}]}
        errors = region_diagnostics(plan, {"s1": {"text": "source"}})
        paths = {error["path"] for error in errors}
        self.assertEqual(paths, {"/region_tree/children/0/slot", "/region_tree",
                                 "/requirements/0/scope", "/requirements/0/targets",
                                 "/actions/0/target"})
        self.assertEqual(plan["region_tree"]["axis"], "row")
