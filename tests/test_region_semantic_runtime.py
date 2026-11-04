import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agents.region_review import audit_region_plan, review_region_plan
from src.service.main_model_runtime import MainModelRuntime, MODEL
from src.utils.pipeline_trace import PipelineTrace
from src.utils.region_tree import compile_region_tree


PLAN = {
    "page_meta": {"viewport": {"width": 800, "height": 600}},
    "elements": [{"id": "item", "type": "text", "origin": "vision",
                  "items": [{"id": "detail", "text": "entry"}]}],
    "requirements": [],
    "actions": [],
    "region_tree": {"id": "page", "axis": "column", "children": [
        {"id": "item", "cross_align": "end", "grow": True}]},
}
PASS = {"verdict": "pass", "issues": []}


class SemanticRuntimeTests(unittest.TestCase):
    def exercise(self, plan, responses):
        def dispatch(request, **kwargs):
            return {"ok": True, "response": {"choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(responses.pop(0))}}]}}
        with tempfile.TemporaryDirectory() as directory:
            with MainModelRuntime(Path(directory) / "run", dispatch, profile="semantic7") as runtime:
                runtime.used = ["vision_initial", "architect"]
                output = review_region_plan(plan, {}, {"elements": [{"id": "item"}]},
                                            "request", MODEL, "schema", "input")
                return output, runtime.used

    def test_invalid_json_gets_one_repair_and_reaudit(self):
        output, slots = self.exercise("broken JSON", [PASS, PLAN, PASS])
        self.assertEqual(slots[-3:], ["semantic_audit", "architect_repair", "semantic_reaudit"])
        self.assertEqual(output["elements"][0]["items"], PLAN["elements"][0]["items"])

    def test_row_bottom_alias_is_opt_in_and_auditable(self):
        plan = deepcopy(PLAN)
        plan["region_tree"]["children"] = [
            {"id": "controls", "axis": "row", "slot": "bottom", "children": [
                {"id": "item", "slot": "bottom", "cross_align": "end", "grow": True}]}]
        original = deepcopy(plan)
        with patch.dict("os.environ", {"UI_REGION_PLAN_NORMALIZATION": ""}):
            with self.assertRaisesRegex(ValueError, "/children/0/children/0/slot"):
                compile_region_tree(plan, {}, schema_version=2)

        expected = deepcopy(plan)
        del expected["region_tree"]["children"][0]["children"][0]["slot"]
        with patch.dict("os.environ", {"UI_REGION_PLAN_NORMALIZATION": "row_bottom_alias_v1"}):
            with tempfile.TemporaryDirectory() as directory:
                trace = Path(directory) / "trace"
                with PipelineTrace(trace):
                    output = compile_region_tree(plan, {}, schema_version=2)
                event, = trace.glob("*region_plan_normalized.json")
                evidence = json.loads(event.read_text(encoding="utf-8"))
            self.assertEqual(evidence["raw_plan"], original)
            self.assertEqual(evidence["normalized_plan"], expected)
            self.assertEqual(evidence["changeset"], [{
                "path": "/region_tree/children/0/children/0/slot", "op": "remove", "original": "bottom",
                "reason": "row_bottom_slot_with_explicit_cross_align_end"}])
            self.assertEqual(output, compile_region_tree(expected, {}, schema_version=2))
            self.assertEqual(output["region_tree"]["children"][0]["slot"], "bottom")
            audited, slots = self.exercise(plan, [PASS])
            self.assertEqual(audited["region_tree"], output["region_tree"])
            self.assertEqual(slots[-1], "semantic_audit")
            for align in (None, "start", "center", "stretch"):
                with self.subTest(align=align):
                    conflict = deepcopy(plan)
                    conflict["region_tree"]["children"][0]["children"][0]["cross_align"] = align
                    with self.assertRaisesRegex(ValueError, "/children/0/children/0/slot"):
                        compile_region_tree(conflict, {}, schema_version=2)
        self.assertEqual(plan, original)

    @patch.dict("os.environ", {"UI_REGION_REPAIR_MODE": "local_subtree",
                               "UI_REGION_AUDIT_POLICY": "repair_on_revise"})
    def test_local_repair_uses_parent_scope_and_preserves_other_plan_values(self):
        plan = deepcopy(PLAN)
        plan["elements"].append({"id": "title", "type": "text", "origin": "vision"})
        scope = {"id": "group", "axis": "row", "children": plan["region_tree"]["children"]}
        plan["region_tree"]["children"] = [scope, {"id": "title"}]
        original = deepcopy(plan)
        issue = {"verdict": "revise", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "plan_ref": "tree:item", "expected_relation": "other side",
            "actual_structure": "item is at end", "certainty": "error"}]}
        replacement = deepcopy(scope)
        replacement["children"][0]["cross_align"] = "start"
        output, slots = self.exercise(plan, [issue, {"replacement_subtree": replacement}, PASS])
        self.assertTrue(output["page_meta"]["semantic_review_passed"])
        self.assertEqual(output["region_tree"]["children"][0]["children"], replacement["children"])
        self.assertEqual(output["region_tree"]["children"][1]["id"], "title")
        self.assertEqual(plan, original)
        self.assertEqual(slots[-3:], ["semantic_audit", "architect_repair", "semantic_reaudit"])

        for invalid, reason in (
            (scope, "SUBTREE_REPAIR_NO_CHANGE"),
            (replacement | {"id": "renamed"}, "SUBTREE_REPAIR_ROOT_ID_CHANGED"),
            (replacement | {"children": [{"id": "title"}]}, "SUBTREE_REPAIR_LEAF_IDS_CHANGED"),
            (replacement | {"children": [{"id": "item", "slot": "bottom"}]}, "REGION_CONTRACT_INVALID"),
        ):
            with self.subTest(reason=reason):
                output, slots = self.exercise(plan, [issue, {"replacement_subtree": invalid}])
                selection = output["page_meta"]["plan_selection"]
                self.assertTrue(selection["repair_failed"])
                self.assertEqual(selection["selected"], "initial")
                self.assertIn(reason, selection["diagnostic"])
                self.assertFalse(output["page_meta"]["semantic_review_passed"])
                self.assertEqual(slots[-1], "architect_repair")

    def test_invalid_review_is_reported_on_inspectable_candidate(self):
        output, slots = self.exercise(PLAN, [{"verdict": "pass"}])
        self.assertEqual(output["page_meta"]["semantic_review"]["verdict"], "invalid")
        self.assertFalse(output["page_meta"]["semantic_review_passed"])
        self.assertEqual(slots[-1], "semantic_audit")

    def test_unknown_does_not_pass(self):
        unresolved = {"verdict": "unresolved", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "plan_ref": "elements:item", "expected_relation": "unclear content",
            "actual_structure": "ambiguous", "certainty": "unknown"}]}
        output, slots = self.exercise(PLAN, [unresolved])
        self.assertFalse(output["page_meta"]["semantic_review_passed"])
        self.assertEqual(output["page_meta"]["semantic_review"]["verdict"], "unresolved")
        self.assertEqual(slots[-1], "semantic_audit")

    def test_failed_repair_is_not_retried(self):
        with self.assertRaises(ValueError):
            self.exercise("broken", [PASS, "still broken"])

    def test_repair_that_drops_inventory_leaf_keeps_valid_initial(self):
        plan = deepcopy(PLAN)
        plan["elements"].append({"id": "title", "type": "text", "origin": "vision"})
        plan["region_tree"]["children"].append({"id": "title"})
        repaired = deepcopy(plan)
        repaired["region_tree"]["children"].pop()
        issue = {"verdict": "revise", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "plan_ref": "tree:item", "expected_relation": "supported content",
            "actual_structure": "content differs", "certainty": "error"}]}
        output, slots = self.exercise(plan, [issue, repaired])
        self.assertEqual(slots[-1], "architect_repair")
        self.assertEqual(output["region_tree"]["children"][-1]["id"], "title")
        self.assertEqual(output["page_meta"]["plan_selection"]["selected"], "initial")
        self.assertIn("title", output["page_meta"]["plan_selection"]["diagnostic"])
        self.assertFalse(output["page_meta"]["semantic_review_passed"])

    def test_invalid_first_review_does_not_block_structural_repair(self):
        output, slots = self.exercise("broken", [{"verdict": "pass"}, PLAN, PASS])
        self.assertTrue(output["page_meta"]["semantic_review_passed"])
        self.assertEqual(slots[-1], "semantic_reaudit")

    def test_reaudit_error_remains_visible_on_structurally_valid_candidate(self):
        error = {"verdict": "revise", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "plan_ref": "tree:item", "expected_relation": "supported content",
            "actual_structure": "content differs", "certainty": "error"}]}
        output, slots = self.exercise(PLAN, [error, PLAN, error])
        self.assertFalse(output["page_meta"]["semantic_review_passed"])
        issue = output["page_meta"]["semantic_review"]["issues"][0]
        self.assertEqual(issue["plan_path"], "/region_tree/children/0")
        self.assertEqual(issue["resolved_actual"]["id"], "item")
        self.assertEqual(slots.count("architect_repair"), 1)

    def test_metadata_defects_still_trigger_repair_and_never_become_pass(self):
        plan = deepcopy(PLAN)
        plan["requirements"] = [{
            "sources": ["missing_source"], "intent": "request", "certainty": "explicit",
            "status": "bound", "scope": "missing_region", "targets": [],
            "references": ["nested_item"]}]
        original = deepcopy(plan)
        output, slots = self.exercise(plan, [PASS, plan, PASS])
        self.assertEqual(slots.count("architect_repair"), 1)
        self.assertFalse(output["page_meta"]["semantic_review_passed"])
        self.assertFalse(output["page_meta"]["semantic_contract_passed"])
        self.assertEqual(len(output["page_meta"]["semantic_contract_issues"]), 4)
        self.assertEqual(output["requirements"][0]["sources"], ["missing_source"])
        self.assertEqual(output["requirements"][0]["evidence"], [])
        self.assertEqual(output["requirements"][0]["targets"], [])
        self.assertEqual(output["requirements"][0]["status"], "bound")
        self.assertEqual(plan, original)

    def test_baseline_rejects_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            with MainModelRuntime(Path(directory) / "run") as runtime:
                runtime.used = ["vision_initial", "architect"]
                with self.assertRaisesRegex(RuntimeError, "ORDER"):
                    runtime.create("semantic_audit", model=MODEL)

    @patch.dict("os.environ", {"UI_REGION_AUDIT_POLICY": "shadow"})
    def test_shadow_preserves_executable_plan_with_audit_and_binding_defects(self):
        plan = deepcopy(PLAN)
        plan["requirements"] = [{"sources": ["s1"], "intent": "place item", "certainty": "explicit",
                                 "status": "bound", "scope": None, "targets": [], "references": []}]
        issue = {"verdict": "revise", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "plan_ref": "tree:item", "expected_relation": "alternate content",
            "actual_structure": "item", "certainty": "error"}]}
        output, slots = self.exercise(plan, [issue])
        self.assertEqual(slots, ["vision_initial", "architect", "semantic_audit"])
        self.assertEqual(output["region_tree"], PLAN["region_tree"] | {"grow": False})
        self.assertEqual(output["page_meta"]["plan_selection"], {"selected": "initial"})
        self.assertEqual(output["page_meta"]["semantic_review"]["verdict"], "revise")
        self.assertFalse(output["page_meta"]["semantic_review_passed"])
        self.assertFalse(output["page_meta"]["semantic_contract_passed"])

    @patch.dict("os.environ", {"UI_REGION_AUDIT_POLICY": "shadow"})
    def test_shadow_repairs_hard_failure_once_or_blocks(self):
        bad = deepcopy(PLAN)
        bad["region_tree"]["children"].append({"id": "ghost"})
        output, slots = self.exercise(bad, [PASS, PLAN, PASS])
        self.assertEqual(output["page_meta"]["plan_selection"], {"selected": "repair"})
        self.assertEqual(slots[-3:], ["semantic_audit", "architect_repair", "semantic_reaudit"])
        with self.assertRaisesRegex(ValueError, "ghost"):
            self.exercise(bad, [PASS, bad])

    @patch.dict("os.environ", {"UI_REGION_AUDIT_POLICY": "shadow"})
    def test_audit_only_profile_runs_the_same_auditor_once(self):
        packet = {"ok": True, "response": {"choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(PASS)}}]}}
        with tempfile.TemporaryDirectory() as directory:
            with MainModelRuntime(Path(directory) / "run", lambda *a, **k: packet, profile="audit1") as runtime:
                with self.assertRaisesRegex(RuntimeError, "ORDER"):
                    runtime.create("vision", model=MODEL)
                self.assertEqual(audit_region_plan(PLAN, {}, {}, "request", MODEL, "semantic_audit"), PASS)
                self.assertEqual(runtime.used, ["semantic_audit"])
                with self.assertRaisesRegex(RuntimeError, "ALREADY_CONSUMED"):
                    runtime.create("semantic_audit", model=MODEL)

    def test_failed_request_consumes_slot_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            dispatch = lambda *args, **kwargs: {"ok": False, "error_type": "test"}
            with MainModelRuntime(Path(directory) / "run", dispatch, profile="semantic7") as runtime:
                with self.assertRaises(RuntimeError):
                    runtime.create("vision", model=MODEL)
                self.assertEqual(runtime.used, ["vision_initial"])
                with self.assertRaisesRegex(RuntimeError, "PRIOR_REQUEST_FAILED"):
                    runtime.create("vision", model=MODEL)

    def test_all_seven_slots_and_cap(self):
        from src.service.main_model_runtime import note_vision_repair
        packet = {"ok": True, "response": {"choices": [{
            "finish_reason": "stop", "message": {"content": "{}"}}]}}
        with tempfile.TemporaryDirectory() as directory:
            with MainModelRuntime(Path(directory) / "run", lambda *a, **k: packet,
                                  profile="semantic7") as runtime:
                runtime.create("vision", model=MODEL)
                note_vision_repair({"reason": "invalid observation"})
                for stage in ("vision", "architect", "semantic_audit", "architect_repair",
                              "semantic_reaudit", "coder"):
                    runtime.create(stage, model=MODEL)
                self.assertEqual(len(runtime.used), 7)
                with self.assertRaises(RuntimeError):
                    runtime.create("coder", model=MODEL)


if __name__ == "__main__":
    unittest.main()
