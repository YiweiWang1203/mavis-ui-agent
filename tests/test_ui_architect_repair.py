from src.agents.ui_architect import repair_ui_state_with_vision
from src.priors import apply_ui_priors, infer_page_kind


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

    repaired = repair_ui_state_with_vision(model_state, vision, preferred_locale="en")

    assert repaired["page_meta"]["viewport"] == {"width": 375, "height": 812}
    assert repaired["page_meta"]["locale"] == "en"
    element = repaired["elements"][0]
    assert element["text"] == "Buy now"
    assert element["rpa_action"] == "purchase_now"
    assert element["spatial_info"]["bbox"] == [75, 81, 300, 162]
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

    assert repaired["page_meta"]["locale"] == "zh-CN"
    assert [e["id"] for e in repaired["elements"]] == ["e1", "e2"]
    assert repaired["elements"][1]["spatial_info"]["bbox"] == [188, 650, 338, 731]
    assert repaired["elements"][1]["text"] == "Cart"


def test_ui_prior_adds_mobile_product_detail_back_button():
    ui_state = {
        "page_meta": {
            "inferred_device": "mobile",
            "viewport": {"width": 375, "height": 812},
            "locale": "zh-CN",
        },
        "elements": [
            {
                "id": "e1",
                "type": "image",
                "text": "",
                "spatial_info": {"bbox": [56, 122, 319, 365]},
                "rpa_action": "",
            }
        ],
    }

    result = apply_ui_priors(ui_state, user_intent="请生成淘宝商品详情页")

    assert result["page_meta"]["page_kind"] == "mobile_product_detail"
    assert result["elements"][0]["id"] == "nav_back_prior"
    assert result["elements"][0]["semantic_role"] == "back"
    assert result["elements"][0]["spatial_info"]["source"] == "ui_prior"
    assert "ui_prior_inserted:top_navigation_back" in result["warnings"]


def test_ui_prior_does_not_duplicate_existing_back_button():
    ui_state = {
        "page_meta": {"inferred_device": "mobile", "viewport": {"width": 375, "height": 812}},
        "elements": [
            {
                "id": "back",
                "type": "icon_button",
                "semantic_role": "back",
                "spatial_info": {"bbox": [12, 24, 44, 56]},
                "rpa_action": "go_back",
            }
        ],
    }

    result = apply_ui_priors(ui_state, user_intent="mobile product detail page")

    assert [element["id"] for element in result["elements"]] == ["back"]
    assert result.get("warnings") in (None, [])


def test_ui_prior_does_not_force_back_on_mobile_home_page():
    ui_state = {
        "page_meta": {"inferred_device": "mobile", "viewport": {"width": 375, "height": 812}},
        "elements": [],
    }

    assert infer_page_kind("移动端首页") is None
    result = apply_ui_priors(ui_state, user_intent="移动端首页")

    assert result["elements"] == []
