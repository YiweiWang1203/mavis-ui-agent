from copy import deepcopy

import pytest

from src.utils.single_semantic_layout import SemanticMembershipLayout, compile_semantic_membership


def fixture():
    return {
        "page_meta": {"viewport": {"width": 800, "height": 600}},
        "frames": [{"id": "page", "flow": "vertical", "parent": None},
                   {"id": "local", "flow": "horizontal", "parent": "page", "membership_source_id": "s1"}],
        "elements": [{"id": key, "type": "input", "origin": "vision", "parent": "local"} for key in ("a", "b")],
        "relations": [{"id": "r1", "kind": "left_of", "subject": "b", "reference": "a",
                       "frame": "local", "source_id": "s1"}],
        "actions": [], "content_requirements": [],
    }


SEGMENTS = {"s1": {"text": "Place it beside the other one.", "start": 8, "end": 38}}


def test_parent_is_required_and_layout_evidence_is_derived():
    plan = fixture()
    state, proof = compile_semantic_membership(plan, SEGMENTS, "Make a page")
    assert [row["id"] for row in state["region_tree"]["children"][0]["children"]] == ["b", "a"]
    assert all("parent" not in element for element in state["elements"])
    assert proof["relations"][-1]["quote"] is None
    assert proof["relations"][-1]["source_evidence"] == SEGMENTS["s1"]
    assert proof["relations"][-1]["compiled_paths"]
    plan["relations"][0].update(source_id="request", quote="Make")
    assert compile_semantic_membership(plan, SEGMENTS, "Make a page")[1]["relations"][-1]["quote"] == "Make"
    for field in ("frames", "elements"):
        missing = deepcopy(plan)
        del missing[field][-1]["parent"]
        with pytest.raises(ValueError, match="parent"):
            SemanticMembershipLayout.model_validate(missing)


@pytest.mark.parametrize(("edit", "error"), [
    ({"source_id": "s99"}, "SOURCE_QUOTE"),
    ({"quote": "invented"}, "SOURCE_QUOTE"),
    ({"quote": ""}, "SOURCE_QUOTE"),
    ({"frame": "a"}, "SUBJECT_OR_FRAME"),
    ({"reference": "page"}, "REFERENCE"),
    ({"kind": "above"}, "DIRECTION_AXIS"),
    ({"kind": "inside"}, "literal_error"),
])
def test_relation_errors_are_rejected(edit, error):
    plan = fixture()
    plan["relations"][0].update(edit)
    with pytest.raises(ValueError, match=error):
        compile_semantic_membership(plan, SEGMENTS, "Make a page")


def test_membership_does_not_get_inferred_from_relations():
    plan = fixture()
    plan["elements"][1]["parent"] = "page"
    with pytest.raises(ValueError, match="FRAME_MEMBERSHIP"):
        compile_semantic_membership(plan, SEGMENTS, "")
    plan["elements"][1]["parent"] = "unknown"
    with pytest.raises(ValueError, match="SUBJECT_OR_FRAME"):
        compile_semantic_membership(plan, SEGMENTS, "")
    plan["elements"][1]["parent"] = "local"
    plan["frames"][1]["parent"] = "local"
    with pytest.raises(ValueError, match="COVERAGE|PARENT_CYCLE"):
        compile_semantic_membership(plan, SEGMENTS, "")
