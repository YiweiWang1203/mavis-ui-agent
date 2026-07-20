from copy import deepcopy
from types import SimpleNamespace

from PIL import Image

from src.graph import nodes
from src.tools.vision_ontology_adapter import convert_vision_payload_to_ontology


def _payload():
    return {
        "schema_version": "1.0",
        "canvas": {"width": 400, "height": 800, "orientation": "portrait"},
        "elements": [
            {
                "id": "button",
                "type": "button",
                "text": "Submit",
                "bbox": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.4, "y_max": 0.2},
                "parent_id": "card",
                "children_ids": [],
            },
            {
                "id": "avatar",
                "type": "avatar",
                "bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.2, "y_max": 0.3},
            },
            {
                "id": "icon",
                "type": "icon_button",
                "bbox": {"x_min": 0.2, "y_min": 0.2, "x_max": 0.3, "y_max": 0.3},
            },
            {
                "id": "divider",
                "type": "divider",
                "bbox": {"x_min": 0.0, "y_min": 0.5, "x_max": 1.0, "y_max": 0.51},
            },
            {
                "id": "text",
                "type": "text",
                "text": "Hello",
                "bbox": {"x_min": 0.1, "y_min": 0.6, "x_max": 0.4, "y_max": 0.7},
            },
            {
                "id": "card",
                "type": "card",
                "bbox": {"x_min": 0.05, "y_min": 0.05, "x_max": 0.95, "y_max": 0.95},
                "children_ids": ["button"],
            },
            {
                "id": "search",
                "type": "search_input",
                "bbox": {"x_min": 0.1, "y_min": 0.8, "x_max": 0.9, "y_max": 0.9},
            },
        ],
        "reading_order": ["button", "avatar", "icon", "divider", "text", "card", "search"],
    }


def test_adapter_maps_legacy_types_and_fields():
    result = convert_vision_payload_to_ontology(_payload())
    by_id = {element["id"]: element for element in result["elements"]}

    assert result["schema_version"] == "ui_element_ontology_v0.1"
    assert result["metadata"]["source_schema_version"] == "1.0"
    assert by_id["button"]["type"] == "region"
    assert by_id["button"]["interactive"] is True
    assert by_id["button"]["shape"] == "rounded_rectangle"
    assert by_id["button"]["text_content"] == "Submit"
    assert by_id["button"]["parent_id"] == "card"
    assert by_id["card"]["children_ids"] == ["button"]
    assert by_id["avatar"]["type"] == "image"
    assert by_id["avatar"]["interactive"] is False
    assert by_id["avatar"]["shape"] == "circle"
    assert by_id["icon"]["type"] == "icon"
    assert by_id["icon"]["interactive"] is True
    assert by_id["divider"]["type"] == "divider"
    assert by_id["divider"]["shape"] == "line"
    assert by_id["text"]["type"] == "text"
    assert by_id["text"]["text_content"] == "Hello"
    assert by_id["card"]["type"] == "region"
    assert by_id["search"]["type"] == "region"
    assert by_id["search"]["interactive"] is True


def test_adapter_does_not_mutate_original_payload():
    original = _payload()
    snapshot = deepcopy(original)

    convert_vision_payload_to_ontology(original)

    assert original == snapshot


def test_adapter_rejects_invalid_bbox():
    payload = _payload()
    payload["elements"][0]["bbox"]["x_min"] = 0.9

    try:
        convert_vision_payload_to_ontology(payload)
    except Exception as exc:
        assert "bbox" in str(exc)
    else:
        raise AssertionError("invalid bbox should fail validation")


def test_vision_node_adds_v0_1_without_replacing_legacy(monkeypatch, tmp_path):
    img = tmp_path / "img.png"
    Image.new("RGB", (400, 800), "white").save(img)
    legacy = _payload()

    def fake_extract(image_path, user_context=None, audit_logger=None):
        return legacy

    monkeypatch.setattr(nodes.vision_tool, "extract_ui_layout", fake_extract)

    state = {"messages": [SimpleNamespace(content=f"[IMAGE]: {str(img)}")]}
    cmd = nodes.vision_node(state)

    assert cmd.update["vision_elements"] is not None
    assert cmd.update["vision_elements"]["schema_version"] == "1.0"
    assert cmd.update["vision_elements_v0_1"]["schema_version"] == "ui_element_ontology_v0.1"
    assert cmd.update["vision_elements_v0_1"]["elements"][0]["type"] == "region"
