"""One independent semantic review, one bounded repair, and one re-review."""
import json
import os
from copy import deepcopy
from typing import Literal
from pydantic import Field, create_model

from src.schemas.region_plan import Contract, Region
from src.service.main_model_runtime import main_client, note_rejected_architect_repair
from src.utils.pipeline_trace import trace_event
from src.utils.region_tree import compile_region_tree, normalize_region_plan
from src.utils.region_audit_input import observation_content, audit_plan_view, plan_references, resolve_pointer
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


def request_region_review(model, stage, system, payload, original_content=None):
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


class SubtreeRepairFailed(ValueError):
    pass


class SubtreeEdit(Contract):
    replacement_subtree: Region


def repair_scope(plan, review):
    refs = plan_references(plan)
    paths = []
    for issue in (review or {}).get("issues", []):
        if issue["certainty"] != "error":
            continue
        ref = refs.get(issue["plan_ref"])
        if ref is None or not issue["plan_ref"].startswith("tree:"):
            raise ValueError("SUBTREE_REPAIR_REQUIRES_TREE_REFERENCE")
        path = ref["path"]
        if issue.get("plan_path", path) != path:
            raise ValueError("SUBTREE_REPAIR_REFERENCE_MISMATCH")
        if "children" not in ref["value"]:
            path = path.rsplit("/children/", 1)[0]
        paths.append(path)
    if not paths:
        raise ValueError("SUBTREE_REPAIR_REQUIRES_LOCATED_ERROR")
    scope = paths[0]
    for path in paths[1:]:
        while path != scope and not path.startswith(scope + "/"):
            scope = scope.rsplit("/children/", 1)[0]
    return scope


def leaf_ids(node):
    if "children" not in node:
        return {node["id"]}
    return set().union(*(leaf_ids(child) for child in node["children"]))


def repair_subtree(plan, model, planner_prompt, planner_content, payload, segments):
    try:
        path = repair_scope(plan, payload.get("review"))
        before = resolve_pointer(plan, path)
        trace_event("architect.subtree_repair_before", path=path, output=before)
        payload.update(
            target_path=path,
            target_subtree=before,
            instruction="Return only replacement_subtree for target_path. Correct the supported layout issues "
            "inside this region. Preserve the root ID, all leaf IDs and unrelated relationships.",
        )
        system = (planner_prompt + "\nThis is a local repair request. The following output schema "
                  "supersedes the complete-plan output instructions above:\n"
                  + json.dumps(SubtreeEdit.model_json_schema()))
        raw = request_region_review(model, "architect_repair", system, payload, original_content=planner_content)
        trace_event("architect.subtree_repair_raw_edit", path=path, output=raw)
        SubtreeEdit.model_validate(raw)
        replacement = raw["replacement_subtree"]
        if replacement["id"] != before["id"]:
            raise ValueError("SUBTREE_REPAIR_ROOT_ID_CHANGED")
        if leaf_ids(replacement) != leaf_ids(before):
            raise ValueError("SUBTREE_REPAIR_LEAF_IDS_CHANGED")
        if Region.model_validate(replacement) == Region.model_validate(before):
            raise ValueError("SUBTREE_REPAIR_NO_CHANGE")
        candidate = deepcopy(plan)
        parent_path, key = path.rsplit("/", 1)
        parent = resolve_pointer(candidate, parent_path)
        parent[int(key) if isinstance(parent, list) else key] = replacement
        trace_event("architect.subtree_repair_candidate", path=path, output=replacement)
        compile_region_tree(candidate, segments, schema_version=2)
        trace_event("architect.subtree_repair_applied", path=path, output=replacement)
        return candidate
    except Exception as error:
        diagnostic = str(error) if isinstance(error, ValueError) else type(error).__name__
        trace_event("architect.subtree_repair_failed", output={"error": diagnostic})
        raise SubtreeRepairFailed(diagnostic) from error


def repair_region_plan(plan, structural_errors, model, planner_prompt, planner_content, *, review=None,
                       segments=None, mode=None):
    mode = mode or os.getenv("UI_REGION_REPAIR_MODE", "full_plan")
    payload = {
        "previous_plan": plan,
        "structural_errors": structural_errors,
        "instruction": "Correct only the listed hard execution violations. Preserve unrelated decisions."
        if review is None else "Correct the supported issues and return the complete plan under the same schema.",
    }
    if review is not None:
        payload["review"] = review
    if mode == "local_subtree":
        return repair_subtree(plan, model, planner_prompt, planner_content, payload, segments)
    if mode != "full_plan":
        raise ValueError("UNSUPPORTED_REGION_REPAIR_MODE")
    return request_region_review(model, "architect_repair", planner_prompt, payload,
                                 original_content=planner_content)


def audit_region_plan(candidate, segments, vision, original_intent, model, stage):
    shadow = os.getenv("UI_REGION_AUDIT_POLICY") == "shadow"
    plan_view = audit_plan_view(candidate)
    refs = plan_references(plan_view)
    indexed_issue = create_model("IndexedIssue", __base__=Issue,
                                 plan_ref=(Literal[tuple(refs)], ...))
    indexed_review = create_model("IndexedReview", __base__=Review,
                                  issues=(list[indexed_issue], ...))
    alignment = (
        "cross_align sets align-self without forcing dimensions. Omitted cross_align defaults to stretch. "
        "An explicit start/end/center overrides stretch; a non-stretched panel needs a suitable extent for "
        "its local bottom to reach the requested edge. Do not assume such a panel fills its parent. "
        if shadow else
        "cross_align start/end/center aligns a child across its parent axis using content-sized extent; "
        "under a column it forces width:fit-content and under a row it forces height:fit-content, "
        "with a 100% maximum across that axis. stretch uses auto sizing. A column panel under a root row "
        "with cross_align=start has content-sized height; its local bottom belongs to that height. "
    )
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
        + alignment +
        "grow fills available main-axis space. bottom anchors the last child of its column locally. "
        "Do not call these expressed relationships unspecified. Unrequested exact spacing is style freedom, "
        "not an unknown requirement or an error. Report error only for an explicit source contradiction. "
        "Return issues with existing source segment IDs and/or vision IDs, an exact supplied plan_ref key, "
        "expected_relation and actual_structure describing that plan value, "
        "and affected object IDs. Do not produce a replacement tree. Return pass only with no issues, "
        "revise for a supported error, unresolved when only uncertainty remains. JSON schema:\n"
        + json.dumps(indexed_review.model_json_schema()))
    value = indexed_review.model_validate(request_region_review(model, stage, system, {
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


def review_region_plan(plan, segments, vision, original_intent, model, planner_prompt, planner_content):
    shadow = os.getenv("UI_REGION_AUDIT_POLICY") == "shadow"
    plan = normalize_region_plan(plan)

    def audit_with_status(candidate, stage):
        try:
            return audit_region_plan(candidate, segments, vision, original_intent, model, stage)
        except ValueError as error:
            result = {"verdict": "invalid", "issues": [], "diagnostic": str(error)}
            trace_event("architect." + stage + "_invalid", output=result)
            return result

    structural_errors = region_diagnostics(plan, segments)
    if shadow:
        structural_errors = [issue for issue in structural_errors
                             if not issue["path"].startswith("/requirements/")]
    if structural_errors:
        trace_event("architect.initial_contract_error", diagnostics=structural_errors, output=plan)
    first = audit_with_status(plan, "semantic_audit")
    final_review = first
    selection = {"selected": "initial"}
    if structural_errors or (not shadow and first["verdict"] == "revise"):
        try:
            repaired = repair_region_plan(plan, structural_errors, model, planner_prompt, planner_content,
                                          review=None if shadow else first, segments=segments)
            trace_event("architect.repair_parsed", output=repaired, previous=plan)
            repaired = normalize_region_plan(repaired)
            result = compile_region_tree(repaired, segments, schema_version=2)
        except ValueError as error:
            selection.update(repair_rejected=True, diagnostic=str(error))
            if isinstance(error, SubtreeRepairFailed):
                selection["repair_failed"] = True
            trace_event("architect.repair_rejected", output=selection)
            if shadow:
                raise
            try:
                result = compile_region_tree(plan, segments, schema_version=2)
            except ValueError:
                raise error
            note_rejected_architect_repair(selection)
        else:
            final_review = audit_with_status(repaired, "semantic_reaudit")
            selection["selected"] = "repair"
    else:
        result = compile_region_tree(plan, segments, schema_version=2)
    result["page_meta"]["plan_selection"] = selection
    result["page_meta"]["semantic_audit_policy"] = "shadow" if shadow else "repair_on_revise"
    result["page_meta"]["semantic_review"] = final_review
    result["page_meta"]["semantic_review_passed"] = (
        not selection.get("repair_rejected") and final_review["verdict"] == "pass"
        and result["page_meta"]["semantic_contract_passed"])
    return result
