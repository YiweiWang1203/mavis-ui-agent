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
