from src.renderers import render_ui_state_html, supports_deterministic_rendering


def test_product_detail_renderer_preserves_text_and_geometry():
    state = {
        "page_meta": {
            "page_kind": "mobile_product_detail",
            "locale": "zh-CN",
            "viewport": {"width": 375, "height": 812},
        },
        "elements": [
            {
                "id": "cart",
                "type": "button",
                "text": "加入购物车",
                "rpa_action": "add_to_cart",
                "spatial_info": {"bbox": [16, 740, 184, 796], "section": "bottom_action_bar"},
                "typography": {"font_size_px": 15, "wrap": False},
            }
        ],
    }

    assert supports_deterministic_rendering(state) is True
    code = render_ui_state_html(state)
    assert '<html lang="zh-CN">' in code
    assert "加入购物车" in code
    assert "left:16px" in code
    assert "top:740px" in code
    assert "handleRPA(&quot;add_to_cart&quot;)" in code
