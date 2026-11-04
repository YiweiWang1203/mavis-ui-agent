import copy
import json
from types import SimpleNamespace

from src.agents import ui_architect


def test_actual_planner_requests_separate_source_geometry(monkeypatch):
    def element(element_id, box, **fields):
        return dict(id=element_id, type="button", text=element_id,
                    bbox=dict(zip(("x_min", "y_min", "x_max", "y_max"), box)), **fields)
    vision = {"elements": [
        element("region", [0, 0, .6, .8]),
        element("inside", [.1, .1, .3, .3]),
        element("right", [.7, .1, .9, .3], parent_id="missing"),
    ], "reading_order": ["inside", "right"], "raw": {"bbox": [500, 600, 800, 900]}}
    original = copy.deepcopy(vision)
    requests = []

    def capture(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    monkeypatch.setattr(ui_architect, "_get_openai_client", lambda: client)
    monkeypatch.setattr(ui_architect, "finalize_ui_state", lambda state, intent, data, *_: data)
    monkeypatch.setenv("UI_FUSION_MODE", "target_layout_v1")
    intent = "ASR: keep original words. Target canvas 1440 by 900."
    for mode in ("full_v1", "relative_v1"):
        monkeypatch.setenv("UI_PLANNER_OBSERVATION_MODE", mode)
        assert ui_architect.generate_ui_state(intent, vision) == original

    full, relative = requests
    assert relative["messages"][0]["content"].startswith(full["messages"][0]["content"] + "\n")
    assert "own non-overlapping target box" in relative["messages"][0]["content"]
    assert all(full[k] == relative[k] for k in full if k != "messages")
    content = relative["messages"][1]["content"]
    assert intent in content
    payload = json.loads(content.split("[Vision Elements]\n", 1)[1].split("\n\nReturn", 1)[0])
    assert payload["elements"] == [
        {"id": e["id"], "type": e["type"], "text": e["text"],
         "observed_parent_id": None, "observed_children_ids": []} for e in vision["elements"]]
    assert {"object_id": "inside", "relation": "geometrically_inside", "other_id": "region"} in payload["spatial_observations"]
    assert {"object_id": "inside", "relation": "left_of", "other_id": "right"} in payload["spatial_observations"]
    assert '"bbox"' not in content and '"raw"' not in content
    assert vision == original


def test_relative_observation_handles_optional_lists_and_rejects_invalid_identity():
    import pytest
    from src.service.planner_observation import relative_vision_observations

    source = {"elements": [{"id": "e1", "children_ids": None},
                           {"id": "e2", "children_ids": "e1"}], "reading_order": None}
    before = copy.deepcopy(source)
    result = relative_vision_observations(source)
    assert result["observed_reading_order"] == []
    assert all(e["observed_children_ids"] == [] for e in result["elements"])
    assert source == before
    for elements, error in [([{}, {"id": "e1"}], "nonempty"),
                            ([{"id": "e1"}, {"id": "e1"}], "Duplicate")]:
        with pytest.raises(ValueError, match=error):
            relative_vision_observations({"elements": elements})

def test_conflict_trace_distinguishes_container_and_independent_controls(monkeypatch):
    from src.utils import layout_solver

    def element(element_id, kind, bbox, parent_id=None):
        return {"id": element_id, "type": kind, "parent_id": parent_id,
                "spatial_info": {"bbox": bbox}}

    state = {"page_meta": {"viewport": {"width": 200, "height": 120}}, "elements": [
        element("group", "container", [0, 0, 160, 90]),
        element("editor", "input", [10, 10, 120, 60], "group"),
        element("first", "button", [90, 40, 110, 55], "group"),
        element("second", "button", [95, 35, 115, 60], "first"),
        element("unlinked", "text", [100, 10, 110, 20]),
        element("touching", "button", [115, 45, 130, 55], "group"),
    ]}
    before = copy.deepcopy(state)
    events = {}

    def record(name, **event):
        events[name] = event

    monkeypatch.setattr(layout_solver, "trace_event", record)
    monkeypatch.setenv("UI_PLANNER_OBSERVATION_MODE", "full_v1")
    baseline = layout_solver.solve_ui_layout(state, "preserve_target", "target_px_xyxy")
    assert "architect.target_control_conflicts" not in events
    monkeypatch.setenv("UI_PLANNER_OBSERVATION_MODE", "relative_v1")
    result = layout_solver.solve_ui_layout(state, "preserve_target", "target_px_xyxy")
    assert state == before and result == baseline
    evidence = events["architect.target_control_conflicts"]
    assert evidence["geometry_changed"] is False
    kinds = {tuple(row["ids"]): row["classification"] for row in evidence["intersections"]}
    assert kinds["group", "editor"] == "declared_container_contains_child"
    assert kinds["editor", "first"] == kinds["first", "second"] == "independent_control_overlap"
    assert kinds["group", "unlinked"] == "observed_intersection_relation_unresolved"
    assert ("second", "touching") not in kinds
