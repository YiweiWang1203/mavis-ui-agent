"""B02 only: columns, capacity and input immutability (no model calls)."""
import copy
import pytest
from src.utils.layout_solver import solve_ui_layout


def state(columns, width=375):
    return {"page_meta": {"page_kind": "mobile_product_detail",
                          "viewport": {"width": width, "height": 812}},
            "elements": [{"id": f"column_{i}", "type": "text", "text": f"value_{i}",
                          "rpa_action": f"display_{i}",
                          "spatial_info": {"bbox": [i * 20, 100, i * 20 + 16, 120]}}
                         for i in range(columns)]}


@pytest.mark.parametrize("columns", [2, 3, 4])
def test_columns_monotonic_disjoint_and_preserve_objects(columns):
    original = state(columns)
    frozen = copy.deepcopy(original)
    result = solve_ui_layout(original)
    boxes = [e["spatial_info"]["bbox"] for e in result["elements"]]
    assert original == frozen
    assert all(0 <= b[0] < b[2] <= 375 for b in boxes)
    assert all(a[2] <= b[0] for a, b in zip(boxes, boxes[1:]))
    for before, after in zip(original["elements"], result["elements"]):
        assert {k: v for k, v in before.items() if k != "spatial_info"} == {
            k: after[k] for k in before if k != "spatial_info"}


def test_capacity_failure_has_diagnostic_and_no_success_or_input_mutation():
    original = state(4, width=150)
    frozen = copy.deepcopy(original)
    with pytest.raises(ValueError) as caught:
        solve_ui_layout(original)
    assert caught.value.args[0]["code"] == "product_detail_columns_insufficient_capacity"
    assert original == frozen


def test_exact_minimum_slot_boundary():
    # width 182: value space 54, three slots of 18, historical gap 4 ->14.
    result = solve_ui_layout(state(4, width=182))
    assert all(e["spatial_info"]["bbox"][2] - e["spatial_info"]["bbox"][0] >= 14
               for e in result["elements"])
    with pytest.raises(ValueError):
        solve_ui_layout(state(4, width=181))
