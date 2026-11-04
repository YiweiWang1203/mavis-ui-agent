from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.agents.ui_architect import generate_ui_state
from src.utils.single_semantic_layout import compile_semantic_layout


def relation(kind, subject, frame, reference=None, *, source="vision", quote=None):
    return dict(id=f"{kind}:{subject}:{frame}", kind=kind, subject=subject,
                frame=frame, reference=reference, source_id=source, quote=quote)


def fixture():
    parents = {"lane": "page", "rail": "page", "a": "lane", "b": "lane", "c": "lane", "d": "rail"}
    return {
        "page_meta": {"viewport": {"width": 800, "height": 600}},
        "elements": [{"id": key, "type": "input" if key == "b" else "button", "origin": "vision"}
                     for key in "abcd"],
        "frames": [{"id": key, "flow": "horizontal" if key == "lane" else "vertical"}
                   for key in ("page", "lane", "rail")],
        "content_requirements": [],
        "actions": [],
        "relations": [relation("inside", key, parent) for key, parent in parents.items()],
    }


def compiled(plan):
    return compile_semantic_layout(plan, {"s1": {"text": "Place this on the lower left."}}, "Make the UI")


@pytest.mark.parametrize(("anchor", "relative", "expected"), [
    ("bottom_left", "left_of", ["a", "b", "c"]),
    ("bottom_right", "right_of", ["b", "c", "a"]),
])
def test_local_corner_and_direction_flip(anchor, relative, expected):
    plan = fixture()
    plan["relations"] += [
        relation(anchor, "a", "lane", source="s1", quote="Place this on the lower left."),
        relation(relative, "a", "lane", "b"), relation("at_bottom", "lane", "page"),
    ]
    result, provenance = compiled(plan)
    rail, lane = result["region_tree"]["children"]
    assert rail["id"] == "rail"
    assert lane["slot"] == "bottom"
    assert [child["id"] for child in lane["children"]] == expected
    a = next(child for child in lane["children"] if child["id"] == "a")
    assert a["cross_align"] == "end"
    assert "slot" not in a
    assert result["requirements"][0]["scope"] == "lane"
    paths = next(row["compiled_paths"] for row in provenance["relations"] if row["kind"] == anchor)
    assert f"/region_tree/children/1/children/{expected.index('a')}/cross_align" in paths
    reordered = deepcopy(plan)
    for field in ("elements", "frames", "relations"):
        reordered[field].reverse()
    assert compiled(reordered)[0]["region_tree"] == result["region_tree"]


def test_same_direction_can_be_relative_to_another_parent():
    plan = fixture()
    plan["frames"][2]["flow"] = "horizontal"
    for row in plan["relations"]:
        if row["subject"] in {"a", "b"}:
            row["frame"] = "rail"
    plan["relations"] += [relation("left_of", "a", "rail", "b")]
    state, _ = compiled(plan)
    lane, rail = state["region_tree"]["children"]
    assert [child["id"] for child in lane["children"]] == ["c"]
    assert [child["id"] for child in rail["children"]] == ["a", "b", "d"]


@pytest.mark.parametrize(("extra", "reason"), [
    ([relation("below", "lane", "page", "rail"), relation("at_bottom", "rail", "page")], "ORDER_CONFLICT"),
    ([relation("left_of", "a", "lane", "b"), relation("right_of", "a", "lane", "b")], "ORDER_CONFLICT"),
    ([relation("at_bottom", "a", "lane"), relation("at_top", "a", "lane")], "PLACEMENT_CONFLICT"),
    ([relation("below", "a", "lane", "b")], "DIRECTION_AXIS"),
    ([relation("left_of", "a", "b", "c")], "SUBJECT_OR_FRAME"),
    ([relation("left_of", "a", "lane", "d")], "REFERENCE"),
    ([relation("left_of", "a", "lane", "unknown")], "REFERENCE"),
    ([relation("at_bottom", "a", "lane", source="s1", quote="invented")], "SOURCE_QUOTE"),
])
def test_rejects_conflicts_and_unrepresentable_relations(extra, reason):
    plan = fixture()
    plan["relations"] += extra
    with pytest.raises(ValueError, match=reason):
        compiled(plan)


def test_rejects_cyclic_membership():
    plan = fixture()
    plan["relations"][0]["frame"] = "rail"
    plan["relations"][1]["frame"] = "lane"
    plan["relations"].append(relation("inside", "aside", "page"))
    plan["elements"].append({"id": "aside", "type": "text", "origin": "vision"})
    with pytest.raises(ValueError, match="PARENT_CYCLE"):
        compiled(plan)


def test_pair_dispatches_real_planner_and_coder_entry_points(tmp_path, monkeypatch):
    import src.graph as graph
    from src.agents.coder import generate_frontend_code
    from src.service.main_model_runtime import MODEL, main_client, note_vision_repair
    from src.service.main_ui_workflow import run_semantic_layout_pair

    for key, value in {
        "UI_STRUCTURE_MODE": "region_tree_v1", "UI_REGION_REVIEW_MODE": "semantic7",
        "UI_REGION_PLAN_NORMALIZATION": "row_bottom_alias_v1", "UI_RENDERER_MODE": "region_bundle_v1",
        "UI_CODER_CONTRACT_MODE": "main_system_v1", "CODER_MODEL": MODEL, "CODER_PROD_MODEL": MODEL,
        "MAVIS_MAIN_RUN_ID": "offline",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("src.agents.coder.HTML_OUTPUT_DIR", tmp_path / "html")

    def vision_node(state):
        client = main_client("vision").chat.completions
        client.create(model=MODEL)
        note_vision_repair({"test": "bounded documented vision correction"})
        client.create(model=MODEL)
        with pytest.raises(RuntimeError, match="UNAUTHORIZED"):
            client.create(model=MODEL)
        return SimpleNamespace(update={"vision_elements": {"elements": []}, "vision_status": {"valid": True}})

    def architect_node(state):
        ui = generate_ui_state(state["original_user_request"], state["vision_elements"])
        return SimpleNamespace(update={"ui_state_json": ui})

    def code_node(state):
        result = generate_frontend_code(state["ui_state_json"])
        return SimpleNamespace(update={"final_code": result["code"], "final_code_path": result["file_path"],
                                       "html_validation": result["html_validation"]})

    ir = fixture()
    baseline, _ = compiled(ir)
    baseline = {key: baseline[key] for key in ("elements", "actions", "region_tree", "requirements")} | {
        "page_meta": ir["page_meta"],
    }
    bundle = {"css": "", "js": "", "panels": [], "components": [
        {"leaf_id": key, "tag": "input" if key == "b" else "button", "attrs": {}, "inner": ""}
        for key in "abcd"]}
    answers = iter([{}, {}, baseline, bundle, ir, bundle])

    def dispatch(request, *, deadline, diagnostics_directory):
        assert deadline == 600
        assert request["max_tokens"] == 8192
        return {"ok": True, "response": {"choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(next(answers))}}]}}

    monkeypatch.setattr(graph, "nodes", SimpleNamespace(
        vision_node=vision_node, ui_architect_node=architect_node, code_node=code_node), raising=False)
    result = run_semantic_layout_pair({"original_user_request": "Make the UI"}, tmp_path, "offline", dispatch)
    assert result["upstream"]["model_calls"] == ["vision_initial", "vision_repair"]
    assert all(result[arm]["model_calls"] == ["architect", "coder"] for arm in ("control", "candidate"))
    assert all(result[arm]["html_contract_passed"] for arm in ("control", "candidate"))

    def request(arm, stage):
        return json.loads((tmp_path / arm / "requests" / f"{stage}_request.json").read_text(encoding="utf-8"))

    control, candidate = (request(arm, "architect") for arm in ("control", "candidate"))
    assert control["messages"][1] == candidate["messages"][1]
    assert '"region_tree"' in control["messages"][0]["content"]
    assert '"region_tree"' not in candidate["messages"][0]["content"]
    assert '"relations"' in candidate["messages"][0]["content"]
    assert request("control", "coder") == request("candidate", "coder")
