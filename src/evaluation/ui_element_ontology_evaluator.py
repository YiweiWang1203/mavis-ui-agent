"""Evaluation metrics for UI Element Ontology v0.1 predictions."""

from __future__ import annotations

from typing import Any

ONTOLOGY_TYPES = ("region", "text", "image", "icon", "divider")


def _bbox_value(bbox: dict[str, Any], key: str) -> float | None:
    try:
        value = float(bbox[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value


def _valid_bbox(bbox: dict[str, Any] | None) -> bool:
    if not isinstance(bbox, dict):
        return False
    x_min = _bbox_value(bbox, "x_min")
    y_min = _bbox_value(bbox, "y_min")
    x_max = _bbox_value(bbox, "x_max")
    y_max = _bbox_value(bbox, "y_max")
    if None in (x_min, y_min, x_max, y_max):
        return False
    return bool(x_min < x_max and y_min < y_max)


def bbox_iou(gt_bbox: dict[str, Any], pred_bbox: dict[str, Any]) -> float:
    """Return bbox IoU, treating malformed boxes as non-overlapping."""

    if not _valid_bbox(gt_bbox) or not _valid_bbox(pred_bbox):
        return 0.0

    gt_x_min = float(gt_bbox["x_min"])
    gt_y_min = float(gt_bbox["y_min"])
    gt_x_max = float(gt_bbox["x_max"])
    gt_y_max = float(gt_bbox["y_max"])
    pred_x_min = float(pred_bbox["x_min"])
    pred_y_min = float(pred_bbox["y_min"])
    pred_x_max = float(pred_bbox["x_max"])
    pred_y_max = float(pred_bbox["y_max"])

    inter_x_min = max(gt_x_min, pred_x_min)
    inter_y_min = max(gt_y_min, pred_y_min)
    inter_x_max = min(gt_x_max, pred_x_max)
    inter_y_max = min(gt_y_max, pred_y_max)
    inter_width = max(0.0, inter_x_max - inter_x_min)
    inter_height = max(0.0, inter_y_max - inter_y_min)
    intersection = inter_width * inter_height
    if intersection <= 0:
        return 0.0

    gt_area = (gt_x_max - gt_x_min) * (gt_y_max - gt_y_min)
    pred_area = (pred_x_max - pred_x_min) * (pred_y_max - pred_y_min)
    union = gt_area + pred_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    return [element for element in elements if isinstance(element, dict)]


def _element_id(element: dict[str, Any], fallback_prefix: str, index: int) -> str:
    value = element.get("id")
    return str(value) if value is not None else f"{fallback_prefix}_{index}"


def _match_elements(
    gt_elements: list[dict[str, Any]],
    pred_elements: list[dict[str, Any]],
    iou_threshold: float,
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, int, int]] = []
    for gt_index, gt in enumerate(gt_elements):
        for pred_index, pred in enumerate(pred_elements):
            iou = bbox_iou(gt.get("bbox"), pred.get("bbox"))
            if iou >= iou_threshold:
                candidates.append((iou, gt_index, pred_index))

    candidates.sort(key=lambda item: item[0], reverse=True)
    used_gt: set[int] = set()
    used_pred: set[int] = set()
    matches: list[dict[str, Any]] = []
    for iou, gt_index, pred_index in candidates:
        if gt_index in used_gt or pred_index in used_pred:
            continue
        gt = gt_elements[gt_index]
        pred = pred_elements[pred_index]
        type_correct = gt.get("type") == pred.get("type")
        interactive_correct = gt.get("interactive") == pred.get("interactive")
        shape_correct = gt.get("shape") == pred.get("shape")
        matches.append(
            {
                "gt_index": gt_index,
                "pred_index": pred_index,
                "gt_id": _element_id(gt, "gt", gt_index),
                "pred_id": _element_id(pred, "pred", pred_index),
                "iou": iou,
                "type_correct": type_correct,
                "interactive_correct": interactive_correct,
                "shape_correct": shape_correct,
                "gt_type": gt.get("type"),
                "pred_type": pred.get("type"),
                "gt_interactive": gt.get("interactive"),
                "pred_interactive": pred.get("interactive"),
                "gt_shape": gt.get("shape"),
                "pred_shape": pred.get("shape"),
            }
        )
        used_gt.add(gt_index)
        used_pred.add(pred_index)
    return matches


def _pair_error(match: dict[str, Any], gt_elements: list[dict[str, Any]], pred_elements: list[dict[str, Any]]) -> dict[str, Any]:
    gt = gt_elements[match["gt_index"]]
    pred = pred_elements[match["pred_index"]]
    return {
        "gt_id": match["gt_id"],
        "pred_id": match["pred_id"],
        "iou": match["iou"],
        "gt": gt,
        "prediction": pred,
    }


def evaluate_ontology_prediction(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    """Evaluate predicted UI Element Ontology payload against ground truth."""

    gt_elements = _elements(ground_truth)
    pred_elements = _elements(prediction)
    matches = _match_elements(gt_elements, pred_elements, iou_threshold)

    matched_gt_indexes = {match["gt_index"] for match in matches}
    matched_pred_indexes = {match["pred_index"] for match in matches}
    matched_count = len(matches)
    gt_count = len(gt_elements)
    pred_count = len(pred_elements)

    precision = _safe_div(matched_count, pred_count)
    recall = _safe_div(matched_count, gt_count)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    mean_iou = _safe_div(sum(match["iou"] for match in matches), matched_count)
    type_accuracy = _safe_div(sum(1 for match in matches if match["type_correct"]), matched_count)
    interactive_accuracy = _safe_div(sum(1 for match in matches if match["interactive_correct"]), matched_count)
    shape_accuracy = _safe_div(sum(1 for match in matches if match["shape_correct"]), matched_count)

    per_type: dict[str, dict[str, float | int]] = {}
    for element_type in ONTOLOGY_TYPES:
        gt_type_count = sum(1 for element in gt_elements if element.get("type") == element_type)
        pred_type_count = sum(1 for element in pred_elements if element.get("type") == element_type)
        matched_gt_count = sum(1 for match in matches if gt_elements[match["gt_index"]].get("type") == element_type)
        matched_pred_count = sum(1 for match in matches if pred_elements[match["pred_index"]].get("type") == element_type)
        per_type[element_type] = {
            "gt_count": gt_type_count,
            "pred_count": pred_type_count,
            "matched_gt_count": matched_gt_count,
            "precision": _safe_div(matched_pred_count, pred_type_count),
            "recall": _safe_div(matched_gt_count, gt_type_count),
        }

    missed_ground_truth = [element for index, element in enumerate(gt_elements) if index not in matched_gt_indexes]
    extra_predictions = [element for index, element in enumerate(pred_elements) if index not in matched_pred_indexes]
    wrong_type = [_pair_error(match, gt_elements, pred_elements) for match in matches if not match["type_correct"]]
    wrong_interactive = [_pair_error(match, gt_elements, pred_elements) for match in matches if not match["interactive_correct"]]
    wrong_shape = [_pair_error(match, gt_elements, pred_elements) for match in matches if not match["shape_correct"]]

    return {
        "summary": {
            "gt_count": gt_count,
            "pred_count": pred_count,
            "matched_count": matched_count,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "mean_iou": mean_iou,
            "type_accuracy": type_accuracy,
            "interactive_accuracy": interactive_accuracy,
            "shape_accuracy": shape_accuracy,
        },
        "per_type": per_type,
        "matches": matches,
        "missed_ground_truth": missed_ground_truth,
        "extra_predictions": extra_predictions,
        "wrong_type": wrong_type,
        "wrong_interactive": wrong_interactive,
        "wrong_shape": wrong_shape,
    }


def _format_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _element_label(element: dict[str, Any]) -> str:
    element_id = element.get("id", "<missing-id>")
    element_type = element.get("type", "<missing-type>")
    return f"{element_id} ({element_type})"


def format_evaluation_report(result: dict[str, Any]) -> str:
    """Format an evaluation result as Markdown."""

    lines = ["# UI Element Ontology Evaluation Report", "", "## Summary", "", "|metric|value|", "|-|-|"]
    for key, value in result.get("summary", {}).items():
        lines.append(f"|{key}|{_format_number(value)}|")

    lines.extend(["", "## Per-Type", "", "|type|gt|pred|matched|precision|recall|", "|-|-:|-:|-:|-:|-:|"])
    for element_type in ONTOLOGY_TYPES:
        metrics = result.get("per_type", {}).get(element_type, {})
        lines.append(
            "|{type}|{gt}|{pred}|{matched}|{precision}|{recall}|".format(
                type=element_type,
                gt=metrics.get("gt_count", 0),
                pred=metrics.get("pred_count", 0),
                matched=metrics.get("matched_gt_count", 0),
                precision=_format_number(metrics.get("precision", 0.0)),
                recall=_format_number(metrics.get("recall", 0.0)),
            )
        )

    lines.extend(["", "## Error Analysis"])
    sections = (
        ("Missed Ground Truth", "missed_ground_truth"),
        ("Extra Predictions", "extra_predictions"),
        ("Wrong Type", "wrong_type"),
        ("Wrong Interactive", "wrong_interactive"),
        ("Wrong Shape", "wrong_shape"),
    )
    for title, key in sections:
        items = result.get(key, [])
        lines.extend(["", f"### {title}", ""])
        if not items:
            lines.append("None")
            continue
        for item in items[:20]:
            if key.startswith("wrong_"):
                gt = item.get("gt", {})
                pred = item.get("prediction", {})
                lines.append(
                    f"- {_element_label(gt)} -> {_element_label(pred)}, IoU {_format_number(item.get('iou', 0.0))}"
                )
            else:
                lines.append(f"- {_element_label(item)}")
        if len(items) > 20:
            lines.append(f"- ... {len(items) - 20} more")

    return "\n".join(lines) + "\n"
