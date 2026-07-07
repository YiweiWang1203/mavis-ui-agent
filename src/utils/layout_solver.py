import copy
import math
import os
from typing import Any


INTERACTIVE_TYPES = {"button", "input", "select", "search_input", "switch", "tab"}


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


def solve_ui_layout(ui_state: dict[str, Any]) -> dict[str, Any]:
    """Convert tight visual evidence boxes into a bounded relational render layout.

    Every detected element is retained. The original box is stored as evidence_bbox;
    only the render bbox is expanded, aligned, and collision-repaired.
    """
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
