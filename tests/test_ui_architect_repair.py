from src.agents.ui_architect import repair_ui_state_with_vision


def test_repair_ui_state_uses_vision_bbox_and_clamps_to_viewport():
    vision = {
        "canvas": {"width": 390, "height": 844, "orientation": "portrait"},
        "elements": [
            {
                "id": "e1",
                "type": "button",
                "text": "Buy",
                "bbox": {"x_min": 0.2, "y_min": 0.1, "x_max": 0.8, "y_max": 0.2},
            }
        ],
    }
    model_state = {
        "page_meta": {"viewport": {"width": 375, "height": 812}},
        "elements": [
            {
                "id": "e1",
                "type": "button",
                "text": "Buy now",
                "spatial_info": {"bbox": [56, 568, 244, 609]},
                "rpa_action": "purchase_now",
            }
        ],
    }

    repaired = repair_ui_state_with_vision(model_state, vision)

    assert repaired["page_meta"]["viewport"] == {"width": 375, "height": 812}
    element = repaired["elements"][0]
    assert element["text"] == "Buy now"
    assert element["rpa_action"] == "purchase_now"
    assert element["spatial_info"]["bbox"] == [81, 75, 162, 300]
    assert element["spatial_info"]["source"] == "vision_bbox"


def test_repair_ui_state_adds_missing_vision_elements():
    vision = {
        "canvas": {"width": 390, "height": 844, "orientation": "portrait"},
        "elements": [
            {
                "id": "e1",
                "type": "text",
                "text": "Price",
                "bbox": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.4, "y_max": 0.2},
            },
            {
                "id": "e2",
                "type": "button",
                "text": "Cart",
                "bbox": {"x_min": 0.5, "y_min": 0.8, "x_max": 0.9, "y_max": 0.9},
            },
        ],
    }

    repaired = repair_ui_state_with_vision({"elements": []}, vision)

    assert [e["id"] for e in repaired["elements"]] == ["e1", "e2"]
    assert repaired["elements"][1]["spatial_info"]["bbox"] == [650, 188, 731, 338]
    assert repaired["elements"][1]["text"] == "Cart"
