from __future__ import annotations

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


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_value_tags(value: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for part in unescape(value or "").replace("\n", ";").split(";"):
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


def _infer_type(value: str, tags: dict[str, str]) -> str:
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
    return "region"


def _infer_interactive(value: str, tags: dict[str, str]) -> bool:
    if "interactive" in tags:
        return _truthy(tags.get("interactive"))
    return _contains_any(value, INTERACTIVE_MARKERS)


def _infer_shape(value: str, style: str, element_type: str, tags: dict[str, str]) -> str:
    explicit = tags.get("shape", "").strip().lower()
    if explicit in VALID_SHAPES:
        return explicit
    lowered_style = (style or "").lower()
    if element_type == "divider":
        return "line"
    if "ellipse" in lowered_style:
        return "circle"
    if "rounded=1" in lowered_style:
        return "rounded_rectangle"
    if "头像" in value:
        return "circle"
    return "rectangle"


def _text_content(value: str, tags: dict[str, str]) -> str | None:
    if "text_content" in tags:
        return tags["text_content"] or None
    return None


def _float_attr(element: ET.Element, name: str, default: float = 0.0) -> float:
    try:
        return float(element.get(name, default))
    except (TypeError, ValueError):
        return default


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
        width = _float_attr(geometry, "width")
        height = _float_attr(geometry, "height")
        if width <= 0 or height <= 0:
            continue
        cells.append((cell, geometry))
    return cells


def _canvas_from_cells(cells: list[tuple[ET.Element, ET.Element]]) -> dict[str, float]:
    if not cells:
        raise ValueError("drawio file contains no vertex cells with geometry")
    candidates = []
    for cell, geometry in cells:
        value = unescape(cell.get("value") or "")
        style = cell.get("style") or ""
        width = _float_attr(geometry, "width")
        height = _float_attr(geometry, "height")
        area = width * height
        candidates.append((area, value, style, geometry))
    largest_area, largest_value, largest_style, largest_geometry = max(candidates, key=lambda item: item[0])
    if (
        _contains_any(largest_value, ("canvas", "画布", "屏幕"))
        or "swimlane" in largest_style.lower()
        or largest_area >= sum(item[0] for item in candidates) * 0.45
    ):
        return {
            "x": _float_attr(largest_geometry, "x"),
            "y": _float_attr(largest_geometry, "y"),
            "width": _float_attr(largest_geometry, "width"),
            "height": _float_attr(largest_geometry, "height"),
        }

    x_min = min(_float_attr(geometry, "x") for _, geometry in cells)
    y_min = min(_float_attr(geometry, "y") for _, geometry in cells)
    x_max = max(_float_attr(geometry, "x") + _float_attr(geometry, "width") for _, geometry in cells)
    y_max = max(_float_attr(geometry, "y") + _float_attr(geometry, "height") for _, geometry in cells)
    return {"x": x_min, "y": y_min, "width": x_max - x_min, "height": y_max - y_min}


def _normalized_bbox(geometry: ET.Element, canvas: dict[str, float]) -> dict[str, float]:
    x = _float_attr(geometry, "x")
    y = _float_attr(geometry, "y")
    width = _float_attr(geometry, "width")
    height = _float_attr(geometry, "height")
    canvas_x = canvas["x"]
    canvas_y = canvas["y"]
    canvas_width = canvas["width"]
    canvas_height = canvas["height"]
    x_min = max(0.0, min(1.0, (x - canvas_x) / canvas_width))
    y_min = max(0.0, min(1.0, (y - canvas_y) / canvas_height))
    x_max = max(0.0, min(1.0, (x + width - canvas_x) / canvas_width))
    y_max = max(0.0, min(1.0, (y + height - canvas_y) / canvas_height))
    return {
        "x_min": round(x_min, 6),
        "y_min": round(y_min, 6),
        "x_max": round(x_max, 6),
        "y_max": round(y_max, 6),
    }


def _is_canvas_cell(cell: ET.Element, geometry: ET.Element, canvas: dict[str, float]) -> bool:
    value = unescape(cell.get("value") or "")
    style = cell.get("style") or ""
    return (
        _contains_any(value, ("canvas", "画布", "屏幕"))
        or "swimlane" in style.lower()
    )


def _cell_to_element(cell: ET.Element, geometry: ET.Element, canvas: dict[str, float]) -> dict[str, Any]:
    value = unescape(cell.get("value") or "")
    style = cell.get("style") or ""
    tags = _parse_value_tags(value)
    element_type = _infer_type(value, tags)
    return {
        "id": str(cell.get("id") or ""),
        "type": element_type,
        "bbox": _normalized_bbox(geometry, canvas),
        "interactive": _infer_interactive(value, tags),
        "shape": _infer_shape(value, style, element_type, tags),
        "text_content": _text_content(value, tags),
        "parent_id": None,
        "children_ids": [],
    }


def parse_drawio_to_ontology(drawio_path: str, page_name: str | None = None) -> dict:
    root = ET.parse(Path(drawio_path)).getroot()
    page = _select_page(root, page_name)
    page_root = _page_root(page)
    cells = _vertex_cells(page_root)
    canvas = _canvas_from_cells(cells)
    elements = [
        _cell_to_element(cell, geometry, canvas)
        for cell, geometry in cells
        if not _is_canvas_cell(cell, geometry, canvas)
    ]
    payload = {
        "schema_version": "ui_element_ontology_v0.1",
        "canvas": {
            "width": canvas["width"],
            "height": canvas["height"],
        },
        "metadata": {
            "source": "drawio",
            "page_name": page.get("name"),
        },
        "elements": elements,
    }
    return UIElementOntologyPayload.model_validate(payload).model_dump()
