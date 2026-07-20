from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from src.schemas.ui_element_ontology import UIElementOntologyPayload


VALID_TYPES = {"region", "text", "image", "icon", "divider"}
VALID_SHAPES = {"rectangle", "rounded_rectangle", "circle", "line", "unknown"}
INTERACTIVE_MARKERS = ("交互", "可交互")
TEXT_MARKERS = ("文本", "ID信息", "身份信息", "文字")
IMAGE_MARKERS = ("头像", "图片", "图像", "商品图")
ICON_MARKERS = ("图标", "icon")
DIVIDER_MARKERS = ("分割线", "divider", "separator")
REGION_MARKERS = ("区域", "内容展示", "框", "卡片", "顶部", "底部")
CANVAS_MARKERS = ("canvas", "画布", "屏幕")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_value(value: str | None) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _parse_value_tags(value: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for part in value.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip()
        if key:
            tags[key] = raw_value.strip()
    return tags


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in markers)


def _stroke_color(style: str) -> str | None:
    match = re.search(r"(?:^|;)strokeColor=([^;]+)", style or "", flags=re.IGNORECASE)
    return match.group(1).strip().lower() if match else None


def _style_has(style: str, token: str) -> bool:
    return token.lower() in (style or "").lower()


def _infer_type(value: str, style: str, tags: dict[str, str]) -> str:
    explicit = tags.get("type", "").strip().lower()
    if explicit in VALID_TYPES:
        return explicit
    if _contains_any(value, TEXT_MARKERS):
        return "text"
    if _contains_any(value, IMAGE_MARKERS):
        return "image"
    if _contains_any(value, ICON_MARKERS):
        return "icon"
    if _contains_any(value, DIVIDER_MARKERS):
        return "divider"
    if _contains_any(value, REGION_MARKERS):
        return "region"

    stroke = _stroke_color(style)
    if stroke == "#00cc00":
        return "text"
    if stroke == "#ff0000" and _style_has(style, "ellipse"):
        return "icon"
    if stroke == "#0000ff":
        return "image"
    return "region"


def _infer_interactive(value: str, style: str, element_type: str, tags: dict[str, str]) -> bool:
    if "interactive" in tags:
        return _truthy(tags.get("interactive"))
    if _contains_any(value, INTERACTIVE_MARKERS):
        return True
    return element_type == "icon" and _stroke_color(style) == "#ff0000" and _style_has(style, "ellipse")


def _infer_shape(value: str, style: str, element_type: str, tags: dict[str, str]) -> str:
    explicit = tags.get("shape", "").strip().lower()
    if explicit in VALID_SHAPES:
        return explicit
    if element_type == "divider":
        return "line"
    if _style_has(style, "ellipse"):
        return "circle"
    if _style_has(style, "rounded=1"):
        return "rounded_rectangle"
    return "rectangle"


def _text_content(value: str, element_type: str, tags: dict[str, str]) -> str | None:
    if "text_content" in tags:
        return tags["text_content"] or None
    return value if element_type == "text" and value else None


def _float_attr(element: ET.Element, name: str, default: float = 0.0) -> float:
    try:
        return float(element.get(name, default))
    except (TypeError, ValueError):
        return default


def _geometry_box(geometry: ET.Element) -> dict[str, float]:
    x = _float_attr(geometry, "x")
    y = _float_attr(geometry, "y")
    width = _float_attr(geometry, "width")
    height = _float_attr(geometry, "height")
    return {"x": x, "y": y, "width": width, "height": height, "x2": x + width, "y2": y + height}


def _center(box: dict[str, float]) -> tuple[float, float]:
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _contains_center(outer: dict[str, float], inner: dict[str, float]) -> bool:
    cx, cy = _center(inner)
    return outer["x"] <= cx <= outer["x2"] and outer["y"] <= cy <= outer["y2"]


def _iter_pages(root: ET.Element) -> list[ET.Element]:
    if root.tag == "mxfile":
        return list(root.findall("diagram"))
    if root.tag == "diagram":
        return [root]
    return [root]


def _page_root(page: ET.Element) -> ET.Element:
    graph_model = page.find("mxGraphModel")
    if graph_model is not None:
        root = graph_model.find("root")
        if root is not None:
            return root
    root = page.find("root")
    if root is not None:
        return root
    return page


def _select_page(root: ET.Element, page_name: str | None) -> ET.Element:
    pages = _iter_pages(root)
    if page_name:
        for page in pages:
            if page.get("name") == page_name:
                return page
        raise ValueError(f"drawio page not found: {page_name}")
    return pages[0]


def _vertex_cells(page_root: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    cells = []
    for cell in page_root.findall(".//mxCell"):
        if cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        box = _geometry_box(geometry)
        if box["width"] <= 0 or box["height"] <= 0:
            continue
        cells.append((cell, geometry))
    return cells


def _is_group_cell(cell: ET.Element) -> bool:
    return (cell.get("style") or "").strip().lower() == "group"


def _is_simple_rectangle(style: str) -> bool:
    lowered = (style or "").lower()
    blocked_tokens = ("ellipse", "shape=line", "group", "image;", "shape=image")
    return not any(token in lowered for token in blocked_tokens)


def _is_explicit_canvas_cell(cell: ET.Element) -> bool:
    value = _clean_value(cell.get("value"))
    style = cell.get("style") or ""
    return _contains_any(value, CANVAS_MARKERS) or "swimlane" in style.lower()


def _canvas_from_cells(cells: list[tuple[ET.Element, ET.Element]]) -> tuple[dict[str, float], str | None]:
    if not cells:
        raise ValueError("drawio file contains no vertex cells with geometry")

    for cell, geometry in cells:
        if _is_explicit_canvas_cell(cell):
            return _geometry_box(geometry), cell.get("id")

    candidates = []
    boxes = [(cell, geometry, _geometry_box(geometry)) for cell, geometry in cells]
    total_cells = max(1, len(boxes))
    for cell, geometry, box in boxes:
        if _is_group_cell(cell):
            continue
        value = _clean_value(cell.get("value"))
        style = cell.get("style") or ""
        area = box["width"] * box["height"]
        contained = sum(
            1
            for other_cell, _, other_box in boxes
            if other_cell is not cell and _contains_center(box, other_box)
        )
        empty_bonus = 1 if not value else 0
        simple_bonus = 1 if _is_simple_rectangle(style) else 0
        if contained >= max(3, int(total_cells * 0.25)) and (empty_bonus or simple_bonus):
            candidates.append((contained, area, empty_bonus, simple_bonus, box, cell.get("id")))

    if candidates:
        contained, area, _, _, box, cell_id = max(candidates, key=lambda item: (item[0], item[1]))
        return box, cell_id

    x_min = min(box["x"] for _, _, box in boxes)
    y_min = min(box["y"] for _, _, box in boxes)
    x_max = max(box["x2"] for _, _, box in boxes)
    y_max = max(box["y2"] for _, _, box in boxes)
    return {"x": x_min, "y": y_min, "width": x_max - x_min, "height": y_max - y_min, "x2": x_max, "y2": y_max}, None


def _normalized_bbox(geometry: ET.Element, canvas: dict[str, float]) -> dict[str, float]:
    box = _geometry_box(geometry)
    canvas_width = canvas["width"]
    canvas_height = canvas["height"]
    x_min = max(0.0, min(1.0, (box["x"] - canvas["x"]) / canvas_width))
    y_min = max(0.0, min(1.0, (box["y"] - canvas["y"]) / canvas_height))
    x_max = max(0.0, min(1.0, (box["x2"] - canvas["x"]) / canvas_width))
    y_max = max(0.0, min(1.0, (box["y2"] - canvas["y"]) / canvas_height))
    return {
        "x_min": round(x_min, 6),
        "y_min": round(y_min, 6),
        "x_max": round(x_max, 6),
        "y_max": round(y_max, 6),
    }


def _cell_to_element(cell: ET.Element, geometry: ET.Element, canvas: dict[str, float]) -> dict[str, Any]:
    value = _clean_value(cell.get("value"))
    style = cell.get("style") or ""
    tags = _parse_value_tags(value)
    element_type = _infer_type(value, style, tags)
    return {
        "id": str(cell.get("id") or ""),
        "type": element_type,
        "bbox": _normalized_bbox(geometry, canvas),
        "interactive": _infer_interactive(value, style, element_type, tags),
        "shape": _infer_shape(value, style, element_type, tags),
        "text_content": _text_content(value, element_type, tags),
        "parent_id": None,
        "children_ids": [],
    }


def parse_drawio_to_ontology(drawio_path: str, page_name: str | None = None) -> dict:
    root = ET.parse(Path(drawio_path)).getroot()
    page = _select_page(root, page_name)
    page_root = _page_root(page)
    cells = _vertex_cells(page_root)
    canvas, canvas_cell_id = _canvas_from_cells(cells)
    elements = []
    for cell, geometry in cells:
        if cell.get("id") == canvas_cell_id or _is_group_cell(cell):
            continue
        if not _contains_center(canvas, _geometry_box(geometry)):
            continue
        elements.append(_cell_to_element(cell, geometry, canvas))

    payload = {
        "schema_version": "ui_element_ontology_v0.1",
        "canvas": {
            "width": canvas["width"],
            "height": canvas["height"],
        },
        "metadata": {
            "source": "drawio",
            "page_name": page.get("name"),
            "canvas_cell_id": canvas_cell_id,
        },
        "elements": elements,
    }
    return UIElementOntologyPayload.model_validate(payload).model_dump()
