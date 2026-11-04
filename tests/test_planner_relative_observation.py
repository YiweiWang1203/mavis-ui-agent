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
    assert full["messages"][0] == relative["messages"][0]
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
