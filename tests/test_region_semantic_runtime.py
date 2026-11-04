import json
from pathlib import Path
import tempfile
import unittest

from src.agents.region_review import review_region_plan
from src.service.main_model_runtime import MainModelRuntime, MODEL


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

    def test_invalid_review_stops(self):
        with self.assertRaises(ValueError):
            self.exercise(PLAN, [{"verdict": "pass"}])

    def test_unknown_does_not_pass(self):
        unresolved = {"verdict": "unresolved", "issues": [{
            "sources": [], "vision_ids": ["item"], "objects": ["item"],
            "expected": "unclear content", "actual": "ambiguous", "certainty": "unknown"}]}
        with self.assertRaisesRegex(ValueError, "SEMANTIC_AUDIT_UNRESOLVED"):
            self.exercise(PLAN, [unresolved])

    def test_failed_repair_is_not_retried(self):
        with self.assertRaises(ValueError):
            self.exercise("broken", [PASS, "still broken"])

    def test_baseline_rejects_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            with MainModelRuntime(Path(directory) / "run") as runtime:
                runtime.used = ["vision_initial", "architect"]
                with self.assertRaisesRegex(RuntimeError, "ORDER"):
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
