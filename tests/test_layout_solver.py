from src.utils.layout_inspector import inspect_ui_contract
from src.utils.layout_solver import solve_ui_layout


def _element(element_id, element_type, text, bbox):
    return {
        "id": element_id,
        "type": element_type,
        "text": text,
        "spatial_info": {"bbox": bbox, "source": "vision_bbox"},
        "rpa_action": "",
    }


def test_solver_expands_narrow_content_and_preserves_all_elements():
    state = {
        "page_meta": {"viewport": {"width": 375, "height": 812}},
        "elements": [
            _element("e1", "image", "", [154, 398, 221, 503]),
            _element("e2", "text", "59.65", [139, 503, 176, 528]),
            _element("e3", "text", "7天无理由/运费险", [139, 528, 221, 552]),
            _element("e4", "button", "加入购物车", [139, 650, 199, 674]),
            _element("e5", "button", "立即下单", [199, 650, 259, 674]),
        ],
    }

    result = solve_ui_layout(state)

    assert [element["id"] for element in result["elements"]] == ["e1", "e2", "e3", "e4", "e5"]
    assert result["page_meta"]["layout_solver"]["horizontal_content_expanded"] is True
    assert result["elements"][0]["spatial_info"]["evidence_bbox"] == [154, 398, 221, 503]
    assert result["elements"][3]["spatial_info"]["bbox"][3] - result["elements"][3]["spatial_info"]["bbox"][1] >= 44
    assert inspect_ui_contract(result) == []


def test_solver_emits_shape_typography_and_row_relations():
    state = {
        "page_meta": {"viewport": {"width": 375, "height": 812}},
        "elements": [
            _element("cart", "button", "加入购物车", [120, 700, 220, 724]),
            _element("buy", "button", "立即购买", [220, 700, 300, 724]),
        ],
    }

    result = solve_ui_layout(state)
    cart = result["elements"][0]

    assert cart["spatial_info"]["aspect_ratio"] == 4.1667
    assert cart["typography"]["font_size_px"] >= 12
    assert cart["layout_relations"]["same_row_with"] == ["buy"]
    assert inspect_ui_contract(result) == []


def test_product_detail_solver_uses_sections_and_bottom_actions():
    state = {
        "page_meta": {
            "viewport": {"width": 375, "height": 812},
            "page_kind": "mobile_product_detail",
        },
        "elements": [
            {**_element("back", "icon_button", "", [12, 20, 44, 52]), "semantic_role": "back", "rpa_action": "go_back"},
            _element("title", "text", "item_name", [154, 379, 221, 399]),
            _element("hero", "image", "", [154, 399, 221, 486]),
            _element("price", "text", "59.65", [128, 486, 180, 506]),
            _element("service", "text", "7天无理由/运费险", [128, 506, 221, 526]),
            {**_element("cart", "button", "加入购物车", [128, 606, 221, 650]), "rpa_action": "add_to_cart"},
            {**_element("buy", "button", "立即下单", [221, 606, 278, 650]), "rpa_action": "place_order"},
        ],
    }

    result = solve_ui_layout(state)
    by_id = {element["id"]: element for element in result["elements"]}

    assert result["page_meta"]["layout_solver"]["version"] == "product-detail-v2"
    assert by_id["back"]["spatial_info"]["section"] == "navigation"
    assert by_id["hero"]["spatial_info"]["section"] == "hero"
    assert by_id["cart"]["spatial_info"]["bbox"] == [16, 740, 183, 796]
    assert by_id["buy"]["spatial_info"]["bbox"] == [191, 740, 359, 796]
    hero_box = by_id["hero"]["spatial_info"]["bbox"]
    assert abs((hero_box[2] - hero_box[0]) / (hero_box[3] - hero_box[1]) - 67 / 87) < 0.02
    assert inspect_ui_contract(result) == []
