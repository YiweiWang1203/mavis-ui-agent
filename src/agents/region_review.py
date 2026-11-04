"""One independent semantic review, one bounded repair, and one re-review."""
import json
from typing import Literal
from pydantic import Field, create_model

from src.schemas.region_plan import Contract, RegionPlan
from src.service.main_model_runtime import main_client
from src.utils.pipeline_trace import trace_event
from src.utils.region_tree import compile_region_tree
from src.utils.region_audit_input import observation_content, audit_plan_view, plan_references
from src.utils.region_diagnostics import region_diagnostics


class Issue(Contract):
    sources: list[str]
    vision_ids: list[str]
    objects: list[str]
    plan_ref: str = Field(description="Select an exact supplied plan_refs key. For missing content select its existing parent or collection.")
    expected_relation: str = Field(min_length=1)
    actual_structure: str = Field(min_length=1)
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
        plan_view = audit_plan_view(candidate)
        refs = plan_references(plan_view)
        indexed_issue = create_model("IndexedIssue", __base__=Issue,
                                     plan_ref=(Literal[tuple(refs)], ...))
        indexed_review = create_model("IndexedReview", __base__=Review,
                                      issues=(list[indexed_issue], ...))
        system = (
            "Independently compare original intent and ASR against the executable plan. "
            "Vision is content-only observation evidence, not target geometry. Judge target membership, "
            "directions and local positions only from the actual region_tree. Never use observation coordinates "
            "as final page positions. Original image recognition accuracy is not independently verified here. "
            "Check missing requirements, wrong objects, local reference frames, directions, content and actions. "
            "Evaluate meaning across the whole plan. A broad scope or omitted redundant reference is not an error "
            "when intent and targets/tree uniquely identify the reference. Do not require invented behavior, "
            "photographic assets or a backend. Style preferences are not errors. Unknown evidence is not a pass. "
            "Tree children arrays specify order: row is left-to-right, column top-to-bottom. "
            "cross_align start/end/center aligns a child across its parent axis using content-sized extent; "
            "Specifically, under a column it forces width:fit-content; under a row it forces height:fit-content, "
            "with a 100% maximum across that axis. stretch uses auto sizing. Thus a column panel under a root row "
            "with cross_align=start has content-sized height, not guaranteed full page height; its local bottom "
            "belongs to that height. These rules are important CSS declarations and override ordinary Coder sizing. "
            "grow fills available main-axis space. bottom anchors the last child of its column locally. "
            "Do not call these expressed relationships unspecified. Unrequested exact spacing is style freedom, "
            "not an unknown requirement or an error. Report error only for an explicit source contradiction. "
            "Return issues with existing source segment IDs and/or vision IDs, an exact supplied plan_ref key, "
            "expected_relation and actual_structure describing that plan value, "
            "and affected object IDs. Do not produce a replacement tree. Return pass only with no issues, "
            "revise for a supported error, unresolved when only uncertainty remains. JSON schema:\n"
            + json.dumps(indexed_review.model_json_schema()))
        value = indexed_review.model_validate(request(stage, system, {
            "original_intent": original_intent, "asr_segments": segments,
            "vision_content": observation_content(vision),
            "vision_role": "observation_content_only", "plan": plan_view,
            "plan_refs": {key: {"path": row["path"]} for key, row in refs.items()}})).model_dump()
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
            evidence = refs[issue["plan_ref"]]
            issue["plan_path"] = evidence["path"]
            issue["resolved_actual"] = evidence["value"]
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

    def audit_with_status(candidate, stage):
        try:
            return audit(candidate, stage)
        except ValueError as error:
            result = {"verdict": "invalid", "issues": [], "diagnostic": str(error)}
            trace_event("architect." + stage + "_invalid", output=result)
            return result

    structural_errors = region_diagnostics(plan, segments)
    if structural_errors:
        trace_event("architect.initial_contract_error", diagnostics=structural_errors, output=plan)
    first = audit_with_status(plan, "semantic_audit")
    final_review = first
    if first["verdict"] == "revise" or structural_errors:
        repaired = request("architect_repair", planner_prompt, {
            "previous_plan": plan,
            "review": first,
            "structural_errors": structural_errors,
            "instruction": "Correct the supported issues and return the complete plan under the same schema."},
            original_content=planner_content)
        trace_event("architect.repair_parsed", output=repaired, previous=plan)
        compile_region_tree(repaired, segments, schema_version=2)
        second = audit_with_status(repaired, "semantic_reaudit")
        plan = repaired
        final_review = second
    result = compile_region_tree(plan, segments, schema_version=2)
    result["page_meta"]["semantic_review"] = final_review
    result["page_meta"]["semantic_review_passed"] = final_review["verdict"] == "pass"
    return result
