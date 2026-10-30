import copy
import math
import os
from typing import Any
from src.utils.pipeline_trace import traced_stage, trace_event


INTERACTIVE_TYPES = {"button", "input", "select", "search_input", "switch", "tab"}
PRODUCT_ACTION_MARKERS = {
    "购物车", "立即购买", "立即下单", "购买", "下单",
    "add_to_cart", "buy_now", "place_order", "purchase",
}


def _valid_bbox(element: dict[str, Any]) -> list[int] | None:
    bbox = (element.get("spatial_info") or {}).get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(value))) for value in bbox]
    except (TypeError, ValueError):
        return None
    return [x1, y1, x2, y2] if x1 < x2 and y1 < y2 else None


def _line_count(text: str, width: int, font_size: int) -> int:
    if not text:
        return 1
    explicit_lines = max(1, text.count("\n") + 1)
    estimated_width = sum(font_size if ord(ch) > 127 else font_size * 0.58 for ch in text)
    return max(explicit_lines, int(math.ceil(estimated_width / max(1, width))))


def _same_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a = left["bbox"]
    b = right["bbox"]
    overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    min_height = min(a[3] - a[1], b[3] - b[1])
    center_delta = abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)
    return overlap >= min_height * 0.45 or center_delta <= max(8, min_height * 0.35)


def _build_rows(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: ((value["bbox"][1] + value["bbox"][3]) / 2, value["bbox"][0])):
        matching_row = next((row for row in rows if any(_same_row(item, member) for member in row)), None)
        if matching_row is None:
            rows.append([item])
        else:
            matching_row.append(item)
    for row in rows:
        row.sort(key=lambda value: value["bbox"][0])
    return rows


def _horizontal_transform(items: list[dict[str, Any]], viewport_width: int) -> tuple[float, float, bool]:
    x_min = min(item["bbox"][0] for item in items)
    x_max = max(item["bbox"][2] for item in items)
    content_width = max(1, x_max - x_min)
    margin = 16 if viewport_width <= 600 else 32
    available = max(1, viewport_width - margin * 2)
    should_expand = len(items) >= 3 and content_width < viewport_width * 0.78
    if not should_expand:
        return 1.0, 0.0, False
    scale = available / content_width
    return scale, margin - x_min * scale, True


def _font_hint(element_type: str, box_height: int, line_count: int) -> int:
    if element_type == "button":
        return max(12, min(16, box_height // 3))
    if element_type in {"header", "text"}:
        return max(12, min(22, box_height // max(1, line_count) - 4))
    return max(12, min(16, box_height // max(1, line_count) - 3))


def _element_search_text(element: dict[str, Any]) -> str:
    return " ".join(
        str(element.get(key) or "").lower()
        for key in ("type", "text", "semantic_role", "rpa_action")
    )


def _is_product_action(element: dict[str, Any]) -> bool:
    search_text = _element_search_text(element)
    return str(element.get("type") or "").lower() == "button" and any(
        marker in search_text for marker in PRODUCT_ACTION_MARKERS
    )


def _set_product_geometry(
    element: dict[str, Any],
    bbox: list[int],
    evidence_bbox: list[int],
    section: str,
    font_size: int,
    viewport: dict[str, int],
    same_row_with: list[str] | None = None,
) -> None:
    width = viewport["width"]
    height = viewport["height"]
    spatial = element.setdefault("spatial_info", {})
    spatial["evidence_bbox"] = evidence_bbox
    spatial["bbox"] = bbox
    spatial["source"] = "product_detail_layout_solver"
    spatial["section"] = section
    spatial["center_ratio"] = [
        round((evidence_bbox[0] + evidence_bbox[2]) / (2 * width), 4),
        round((evidence_bbox[1] + evidence_bbox[3]) / (2 * height), 4),
    ]
    spatial["size_ratio"] = [
        round((evidence_bbox[2] - evidence_bbox[0]) / width, 4),
        round((evidence_bbox[3] - evidence_bbox[1]) / height, 4),
    ]
    spatial["aspect_ratio"] = round(
        (evidence_bbox[2] - evidence_bbox[0]) / max(1, evidence_bbox[3] - evidence_bbox[1]), 4
    )
    text = str(element.get("text") or "")
    lines = _line_count(text, bbox[2] - bbox[0], font_size)
    element["typography"] = {
        "line_count": lines,
        "font_size_px": font_size,
        "wrap": lines > 1,
        "fit": "shrink_or_wrap",
    }
    element["layout_relations"] = {"same_row_with": same_row_with or []}


def _solve_product_detail_layout(
    result: dict[str, Any], items: list[dict[str, Any]], viewport: dict[str, int]
) -> dict[str, Any]:
    width = viewport["width"]
    height = viewport["height"]
    margin = 16

    back_items = [
        item for item in items
        if str(item["element"].get("semantic_role") or "").lower() == "back"
        or str(item["element"].get("rpa_action") or "").lower() in {"back", "go_back", "navigate_back"}
    ]
    action_items = [item for item in items if _is_product_action(item["element"])]
    image_items = [
        item for item in items
        if str(item["element"].get("type") or "").lower() == "image" and item not in back_items
    ]
    main_image = max(
        image_items,
        key=lambda item: (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]),
        default=None,
    )

    excluded = set(id(item) for item in back_items + action_items + ([main_image] if main_image else []))
    content_items = [item for item in items if id(item) not in excluded]
    content_items.sort(key=lambda item: ((item["bbox"][1] + item["bbox"][3]) / 2, item["bbox"][0]))

    title_item = None
    if main_image:
        candidates = [
            item for item in content_items
            if str(item["element"].get("type") or "").lower() in {"text", "header"}
            and item["bbox"][1] <= main_image["bbox"][1]
        ]
        if candidates:
            title_item = candidates[-1]
            content_items.remove(title_item)

    for item in back_items:
        _set_product_geometry(item["element"], [12, 12, 56, 56], item["bbox"], "navigation", 20, viewport)

    cursor_y = 68
    if title_item:
        _set_product_geometry(
            title_item["element"], [margin, cursor_y, width - margin, cursor_y + 28],
            title_item["bbox"], "title", 20, viewport,
        )
        cursor_y += 36

    if main_image:
        evidence_width = main_image["bbox"][2] - main_image["bbox"][0]
        evidence_height = main_image["bbox"][3] - main_image["bbox"][1]
        aspect = evidence_width / max(1, evidence_height)
        max_width = width - margin * 2
        max_height = 248
        image_width = min(max_width, int(round(max_height * aspect)))
        image_height = min(max_height, int(round(image_width / max(0.1, aspect))))
        image_left = (width - image_width) // 2
        _set_product_geometry(
            main_image["element"],
            [image_left, cursor_y, image_left + image_width, cursor_y + image_height],
            main_image["bbox"], "hero", 14, viewport,
        )
        cursor_y += image_height + 12

    detail_rows = _build_rows(content_items)
    action_top = height - 72
    available_height = max(1, action_top - cursor_y - 8)
    row_height = max(28, min(40, available_height // max(1, len(detail_rows))))

    for row_index, row in enumerate(detail_rows):
        row_top = cursor_y + row_index * row_height
        row_bottom = min(action_top - 4, row_top + row_height - 4)
        if row_bottom <= row_top:
            row_bottom = row_top + 1
        row_ids = [str(item["element"].get("id")) for item in row if item["element"].get("id")]
        if len(row) == 1:
            item = row[0]
            text = _element_search_text(item["element"])
            is_price = any(marker in text for marker in ("price", "价格", "¥", "￥")) or any(
                ch.isdigit() for ch in str(item["element"].get("text") or "")
            ) and row_index == 0
            _set_product_geometry(
                item["element"], [margin, row_top, width - margin, row_bottom], item["bbox"],
                "price" if is_price else "details", 22 if is_price else 14, viewport,
            )
            continue

        label_width = min(112, max(88, int((width - margin * 2) * 0.32)))
        value_left = margin + label_width + 8
        for column, item in enumerate(row):
            if column == 0:
                bbox = [margin, row_top, margin + label_width, row_bottom]
                font_size = 14
            elif column == len(row) - 1:
                bbox = [value_left, row_top, width - margin, row_bottom]
                font_size = 14
            else:
                remaining = max(1, width - margin - value_left)
                column_width = remaining // max(1, len(row) - 1)
                left = value_left + (column - 1) * column_width
                bbox = [left, row_top, min(width - margin, left + column_width - 4), row_bottom]
                font_size = 14
            _set_product_geometry(
                item["element"], bbox, item["bbox"], "details", font_size, viewport,
                [element_id for element_id in row_ids if element_id != item["element"].get("id")],
            )

    if action_items:
        action_items.sort(key=lambda item: item["bbox"][0])
        gap = 8
        available_width = width - margin * 2 - gap * (len(action_items) - 1)
        button_width = available_width // len(action_items)
        for index, item in enumerate(action_items):
            left = margin + index * (button_width + gap)
            right = width - margin if index == len(action_items) - 1 else left + button_width
            peers = [
                str(peer["element"].get("id")) for peer in action_items
                if peer is not item and peer["element"].get("id")
            ]
            _set_product_geometry(
                item["element"], [left, action_top, right, height - 16], item["bbox"],
                "bottom_action_bar", 15, viewport, peers,
            )

    result.setdefault("page_meta", {})["layout_solver"] = {
        "version": "product-detail-v2",
        "strategy": "section_constraints",
        "element_count": len(items),
        "row_count": len(detail_rows),
        "sections": ["navigation", "title", "hero", "details", "bottom_action_bar"],
    }
    return result


class TargetGeometryRejected(ValueError):
    """The opt-in target geometry is not eligible for a Coder request."""


def _preserve_target_layout(ui_state: dict[str, Any], coordinate_space: str | None) -> dict[str, Any]:
    errors = []
    if coordinate_space != "target_px_xyxy":
        errors.append({"code": "unverified_coordinate_space", "coordinate_space": coordinate_space})
    if not isinstance(ui_state, dict):
        raise TargetGeometryRejected({"status": "rejected", "errors": [{"code": "state_not_object"}]})
    page_meta = ui_state.get("page_meta")
    viewport = page_meta.get("viewport") if isinstance(page_meta, dict) else None
    valid_number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    valid_viewport = isinstance(viewport, dict) and all(
        valid_number(viewport.get(key)) and viewport[key] > 0 for key in ("width", "height")
    )
    if not valid_viewport:
        errors.append({"code": "missing_or_invalid_target_viewport", "viewport": viewport})
    elements = ui_state.get("elements")
    if not isinstance(elements, list) or not elements:
        errors.append({"code": "missing_or_empty_elements"})
        elements = []
    seen = set()
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            errors.append({"code": "element_not_object", "index": index})
            continue
        element_id = element.get("id")
        if not isinstance(element_id, str) or not element_id.strip() or element_id in seen:
            errors.append({"code": "missing_or_duplicate_id", "index": index, "id": element_id})
        if isinstance(element_id, str):
            seen.add(element_id)
        spatial = element.get("spatial_info")
        box = spatial.get("bbox") if isinstance(spatial, dict) else None
        if not isinstance(box, list) or len(box) != 4 or not all(valid_number(v) for v in box):
            errors.append({"code": "invalid_bbox_numbers", "index": index, "id": element_id})
            continue
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            errors.append({"code": "invalid_bbox_order", "index": index, "id": element_id, "bbox": box})
            continue
        if valid_viewport and (x1 < 0 or y1 < 0 or x2 > viewport["width"] or y2 > viewport["height"]):
            errors.append({"code": "bbox_outside_target", "index": index, "id": element_id, "bbox": box})
        if str(element.get("type") or "").lower() not in {"line", "divider"} and (x2-x1 <= 1 or y2-y1 <= 1):
            errors.append({"code": "degenerate_source_control", "index": index, "id": element_id, "bbox": box})
    if errors:
        diagnostic = {"status": "rejected", "mode": "preserve_target", "errors": errors}
        trace_event("architect.preserve_target_admission", diagnostic=diagnostic)
        raise TargetGeometryRejected(diagnostic)
    result = copy.deepcopy(ui_state)
    intersections = []
    for index, element in enumerate(result["elements"]):
        box = element["spatial_info"]["bbox"]
        kind = str(element.get("type") or "unknown")
        font = 16 if kind in {"button", "header"} else 14
        text = str(element.get("text") or "")
        for _ in range(4):
            lines = _line_count(text, box[2]-box[0], font)
            hinted = _font_hint(kind, box[3]-box[1], lines)
            if hinted == font:
                break
            font = hinted
        lines = _line_count(text, box[2]-box[0], font)
        element["typography"] = {"line_count": lines,
            "font_size_px": font,
            "wrap": lines > 1, "fit": "shrink_or_wrap"}
        element["render_geometry"] = {
            "coordinate_space": "target_px_xyxy",
            "center_ratio": [(box[0]+box[2])/(2*viewport["width"]), (box[1]+box[3])/(2*viewport["height"])],
            "size_ratio": [(box[2]-box[0])/viewport["width"], (box[3]-box[1])/viewport["height"]],
            "aspect_ratio": (box[2]-box[0])/(box[3]-box[1]),
        }
        for peer in result["elements"][index+1:]:
            other = peer["spatial_info"]["bbox"]
            area = max(0, min(box[2], other[2])-max(box[0], other[0])) * max(0, min(box[3], other[3])-max(box[1], other[1]))
            if area:
                intersections.append({"ids": [element["id"], peer["id"]], "area": area,
                                      "classification": "observed_intersection_relation_unresolved"})
    result["page_meta"]["layout_solver"] = {"version": "preserve-target-v1", "status": "applied",
        "coordinate_space": coordinate_space, "element_count": len(elements)}
    # Geometry observations stay outside the Coder payload. They do not infer
    # a parent tree or claim every intersecting pair is an illegal collision.
    trace_event("architect.preserve_target_admission", diagnostic={"status": "applied",
                "bbox_changes": 0, "intersections": intersections})
    return result


@traced_stage('architect.layout')
def solve_ui_layout(ui_state: dict[str, Any], layout_mode: str = "legacy",
                    coordinate_space: str | None = None) -> dict[str, Any]:
    """Convert tight visual evidence boxes into a bounded relational render layout.

    Every detected element is retained. The original box is stored as evidence_bbox;
    only the render bbox is expanded, aligned, and collision-repaired.
    """
    if layout_mode == "preserve_target":
        return _preserve_target_layout(ui_state, coordinate_space)
    if layout_mode != "legacy":
        raise ValueError("Unsupported layout mode")
    if os.getenv("LAYOUT_SOLVER_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return ui_state
    if not isinstance(ui_state, dict):
        return ui_state

    result = copy.deepcopy(ui_state)
    viewport = result.get("page_meta", {}).get("viewport") or {"width": 375, "height": 812}
    width = int(viewport.get("width", 375))
    height = int(viewport.get("height", 812))
    elements = result.get("elements")
    if not isinstance(elements, list):
        return result

    items = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        bbox = _valid_bbox(element)
        if bbox:
            items.append({"index": index, "element": element, "bbox": bbox})
    if not items:
        return result

    page_kind = str(result.get("page_meta", {}).get("page_kind") or "")
    if page_kind == "mobile_product_detail" and width <= 600:
        return _solve_product_detail_layout(result, items, {"width": width, "height": height})

    scale_x, offset_x, expanded = _horizontal_transform(items, width)
    for item in items:
        x1, y1, x2, y2 = item["bbox"]
        mapped = [
            int(round(x1 * scale_x + offset_x)),
            y1,
            int(round(x2 * scale_x + offset_x)),
            y2,
        ]
        mapped[0] = max(0, min(width - 1, mapped[0]))
        mapped[2] = max(mapped[0] + 1, min(width, mapped[2]))
        item["mapped_bbox"] = mapped

    rows = _build_rows(items)
    previous_bottom = 0
    gap = 4
    for row_index, row in enumerate(rows):
        desired_top = min(item["mapped_bbox"][1] for item in row)
        row_top = max(desired_top, previous_bottom + (gap if row_index else 0))
        desired_height = max(item["mapped_bbox"][3] - item["mapped_bbox"][1] for item in row)
        if any(item["element"].get("type") in INTERACTIVE_TYPES for item in row):
            desired_height = max(44, desired_height)
        elif any(item["element"].get("type") == "text" for item in row):
            desired_height = max(24, desired_height)
        row_height = min(desired_height, max(1, height - row_top))

        cursor = 0
        for item in row:
            x1, _, x2, _ = item["mapped_bbox"]
            x1 = max(x1, cursor)
            x2 = max(x1 + 1, min(width, x2))
            item["render_bbox"] = [x1, row_top, x2, row_top + row_height]
            cursor = x2 + gap
        previous_bottom = row_top + row_height

    overflow = max(item["render_bbox"][3] for item in items) - height
    if overflow > 0:
        shift = min(overflow, min(item["render_bbox"][1] for item in items))
        for item in items:
            item["render_bbox"][1] -= shift
            item["render_bbox"][3] -= shift

    for row in rows:
        row_ids = [item["element"].get("id") for item in row if item["element"].get("id")]
        for item in row:
            element = item["element"]
            spatial = element.setdefault("spatial_info", {})
            evidence = item["bbox"]
            render = item["render_bbox"]
            spatial["evidence_bbox"] = evidence
            spatial["bbox"] = render
            spatial["source"] = "constraint_layout_solver"
            spatial["center_ratio"] = [
                round((evidence[0] + evidence[2]) / (2 * width), 4),
                round((evidence[1] + evidence[3]) / (2 * height), 4),
            ]
            spatial["size_ratio"] = [
                round((evidence[2] - evidence[0]) / width, 4),
                round((evidence[3] - evidence[1]) / height, 4),
            ]
            spatial["aspect_ratio"] = round((evidence[2] - evidence[0]) / max(1, evidence[3] - evidence[1]), 4)
            text = str(element.get("text") or "")
            provisional_font = 16 if element.get("type") in {"button", "header"} else 14
            lines = _line_count(text, render[2] - render[0], provisional_font)
            element["typography"] = {
                "line_count": lines,
                "font_size_px": _font_hint(str(element.get("type") or "unknown"), render[3] - render[1], lines),
                "wrap": lines > 1,
                "fit": "shrink_or_wrap",
            }
            element["layout_relations"] = {
                "same_row_with": [element_id for element_id in row_ids if element_id != element.get("id")],
                "reading_order_index": items.index(item),
            }

    page_meta = result.setdefault("page_meta", {})
    page_meta["layout_solver"] = {
        "version": "relation-v1",
        "horizontal_content_expanded": expanded,
        "element_count": len(items),
        "row_count": len(rows),
    }
    return result
