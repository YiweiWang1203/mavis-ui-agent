from src.evaluation.ui_element_ontology_evaluator import (
    bbox_iou,
    evaluate_ontology_prediction,
    format_evaluation_report,
)


def _bbox(x_min, y_min, x_max, y_max):
    return {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max}


def _element(element_id, element_type="region", bbox=None, interactive=False, shape="rectangle"):
    return {
        "id": element_id,
        "type": element_type,
        "bbox": bbox or _bbox(0.0, 0.0, 0.2, 0.2),
        "interactive": interactive,
        "shape": shape,
        "text_content": None,
        "parent_id": None,
        "children_ids": [],
    }


def _payload(elements):
    return {"schema_version": "ui_element_ontology_v0.1", "elements": elements}


def test_bbox_iou_full_overlap_is_one():
    box = _bbox(0.1, 0.1, 0.4, 0.4)
    assert bbox_iou(box, box) == 1.0


def test_bbox_iou_partial_overlap_between_zero_and_one():
    value = bbox_iou(_bbox(0.0, 0.0, 0.5, 0.5), _bbox(0.25, 0.25, 0.75, 0.75))
    assert 0.0 < value < 1.0


def test_bbox_iou_no_overlap_is_zero():
    assert bbox_iou(_bbox(0.0, 0.0, 0.1, 0.1), _bbox(0.2, 0.2, 0.3, 0.3)) == 0.0


def test_greedy_matching_disallows_one_prediction_matching_multiple_ground_truth():
    gt = _payload([
        _element("gt-1", bbox=_bbox(0.0, 0.0, 0.4, 0.4)),
        _element("gt-2", bbox=_bbox(0.02, 0.02, 0.42, 0.42)),
    ])
    pred = _payload([_element("pred-1", bbox=_bbox(0.0, 0.0, 0.4, 0.4))])

    result = evaluate_ontology_prediction(gt, pred, iou_threshold=0.5)

    assert result["summary"]["matched_count"] == 1
    assert len(result["missed_ground_truth"]) == 1


def test_position_match_with_wrong_type_is_reported():
    gt = _payload([_element("gt", element_type="text")])
    pred = _payload([_element("pred", element_type="region")])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["type_accuracy"] == 0.0
    assert result["wrong_type"][0]["gt_id"] == "gt"


def test_interactive_mismatch_is_reported():
    gt = _payload([_element("gt", interactive=True)])
    pred = _payload([_element("pred", interactive=False)])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["summary"]["interactive_accuracy"] == 0.0
    assert result["wrong_interactive"][0]["pred_id"] == "pred"


def test_shape_mismatch_is_reported():
    gt = _payload([_element("gt", shape="circle")])
    pred = _payload([_element("pred", shape="rectangle")])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["summary"]["shape_accuracy"] == 0.0
    assert result["wrong_shape"][0]["gt_id"] == "gt"


def test_missed_ground_truth_and_extra_prediction_are_reported():
    gt = _payload([_element("gt", bbox=_bbox(0.0, 0.0, 0.1, 0.1))])
    pred = _payload([_element("pred", bbox=_bbox(0.8, 0.8, 0.9, 0.9))])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["summary"]["matched_count"] == 0
    assert result["missed_ground_truth"][0]["id"] == "gt"
    assert result["extra_predictions"][0]["id"] == "pred"


def test_precision_recall_and_f1_are_computed():
    gt = _payload([
        _element("gt-1", bbox=_bbox(0.0, 0.0, 0.2, 0.2)),
        _element("gt-2", bbox=_bbox(0.3, 0.3, 0.5, 0.5)),
    ])
    pred = _payload([
        _element("pred-1", bbox=_bbox(0.0, 0.0, 0.2, 0.2)),
        _element("pred-extra", bbox=_bbox(0.8, 0.8, 0.9, 0.9)),
    ])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["summary"]["precision"] == 0.5
    assert result["summary"]["recall"] == 0.5
    assert result["summary"]["f1"] == 0.5


def test_per_type_metrics_are_computed():
    gt = _payload([
        _element("gt-text", element_type="text", bbox=_bbox(0.0, 0.0, 0.2, 0.2)),
        _element("gt-icon", element_type="icon", bbox=_bbox(0.3, 0.3, 0.4, 0.4)),
    ])
    pred = _payload([
        _element("pred-text", element_type="text", bbox=_bbox(0.0, 0.0, 0.2, 0.2)),
        _element("pred-region", element_type="region", bbox=_bbox(0.3, 0.3, 0.4, 0.4)),
    ])

    result = evaluate_ontology_prediction(gt, pred)

    assert result["per_type"]["text"]["gt_count"] == 1
    assert result["per_type"]["text"]["pred_count"] == 1
    assert result["per_type"]["text"]["matched_gt_count"] == 1
    assert result["per_type"]["text"]["precision"] == 1.0
    assert result["per_type"]["icon"]["recall"] == 1.0
    assert result["per_type"]["region"]["precision"] == 1.0


def test_markdown_report_contains_summary_per_type_and_errors():
    result = evaluate_ontology_prediction(
        _payload([_element("gt", element_type="text")]),
        _payload([_element("pred", element_type="region")]),
    )

    report = format_evaluation_report(result)

    assert "# UI Element Ontology Evaluation Report" in report
    assert "|precision|" in report
    assert "|region|" in report
    assert "### Wrong Type" in report
