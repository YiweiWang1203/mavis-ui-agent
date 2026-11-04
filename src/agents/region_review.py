"""One independent semantic review, one bounded repair, and one re-review."""
import json
from typing import Literal
from pydantic import Field

from src.schemas.region_plan import Contract, RegionPlan
from src.service.main_model_runtime import main_client
from src.utils.pipeline_trace import trace_event
from src.utils.region_tree import compile_region_tree


class Issue(Contract):
    sources: list[str]
    vision_ids: list[str]
    objects: list[str]
    expected: str = Field(min_length=1)
    actual: str = Field(min_length=1)
    certainty: Literal["error", "unknown"]


class Review(Contract):
    verdict: Literal["pass", "revise", "unresolved"]
    issues: list[Issue]


def review_region_plan(plan, segments, vision, original_intent, model, planner_prompt, planner_content):
    def request(stage, system, payload, original_content=None):
        client = main_client(stage)
        if client is None:
            raise RuntimeError("REGION_REVIEW_REQUIRES_PRODUCTION_RUNTIME")
        text = json.dumps(payload, ensure_ascii=False)
        content = text
        if original_content is not None:
            blocks = original_content if isinstance(original_content, list) else [
                {"type": "text", "text": original_content}]
            content = [*blocks, {"type": "text", "text": text}]
        response = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system},
                                   {"role": "user", "content": content}],
            temperature=0, response_format={"type": "json_object"})
        return json.loads(response.choices[0].message.content)

    def audit(candidate, stage):
        system = (
            "Independently compare the original request and ASR, vision observations and actual UI plan. "
            "Check missing requirements, wrong objects, local reference frames, directions, content and actions. "
            "Evaluate meaning across the whole plan. A broad scope or omitted redundant reference is not an error "
            "when intent and targets/tree uniquely identify the reference. Do not require invented behavior, "
            "photographic assets or a backend. Style preferences are not errors. Unknown evidence is not a pass. "
            "Return issues with existing source segment IDs and/or vision IDs, expected and actual behavior, "
            "and affected object IDs. Do not produce a replacement tree. Return pass only with no issues, "
            "revise for a supported error, unresolved when only uncertainty remains. JSON schema:\n"
            + json.dumps(Review.model_json_schema()))
        value = Review.model_validate(request(stage, system, {
            "original_intent": original_intent, "asr_segments": segments,
            "vision": vision, "plan": candidate})).model_dump()
        def collect_ids(value):
            if isinstance(value, list):
                return set().union(*(collect_ids(item) for item in value))
            if isinstance(value, dict):
                result = {value["id"]} if isinstance(value.get("id"), str) else set()
                for key in ("elements", "items", "children", "region_tree"):
                    result.update(collect_ids(value.get(key)))
                return result
            return set()

        vision_ids = collect_ids(vision)
        object_ids = collect_ids(candidate)
        for issue in value["issues"]:
            if not (issue["sources"] or issue["vision_ids"]):
                raise ValueError("REVIEW_ISSUE_WITHOUT_SOURCE")
            if not set(issue["sources"]) <= segments.keys() or not set(issue["vision_ids"]) <= vision_ids:
                raise ValueError("REVIEW_UNKNOWN_SOURCE")
            if not set(issue["objects"]) <= object_ids:
                raise ValueError("REVIEW_UNKNOWN_OBJECT")
        errors = any(issue["certainty"] == "error" for issue in value["issues"])
        if ((value["verdict"] == "pass" and value["issues"])
                or (value["verdict"] == "revise" and not errors)
                or (value["verdict"] == "unresolved" and (errors or not value["issues"]))):
            raise ValueError("REVIEW_INCONSISTENT_VERDICT")
        trace_event("architect." + stage, output=value)
        return value

    structural_error = None
    try:
        compile_region_tree(plan, segments, schema_version=2)
    except ValueError as error:
        structural_error = str(error)
        trace_event("architect.initial_contract_error", reason=structural_error, output=plan)
    first = audit(plan, "semantic_audit")
    if first["verdict"] == "unresolved" and structural_error is None:
        raise ValueError("SEMANTIC_AUDIT_UNRESOLVED")
    if first["verdict"] == "revise" or structural_error is not None:
        repaired = request("architect_repair", planner_prompt, {
            "previous_plan": plan,
            "review": first,
            "structural_error": structural_error,
            "instruction": "Correct the supported issues and return the complete plan under the same schema."},
            original_content=planner_content)
        trace_event("architect.repair_parsed", output=repaired, previous=plan)
        compile_region_tree(repaired, segments, schema_version=2)
        second = audit(repaired, "semantic_reaudit")
        if second["verdict"] != "pass":
            raise ValueError("SEMANTIC_REAUDIT_UNRESOLVED")
        plan = repaired
    return compile_region_tree(plan, segments, schema_version=2)
