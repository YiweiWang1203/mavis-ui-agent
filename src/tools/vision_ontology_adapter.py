from copy import deepcopy
from typing import Any

from src.schemas.ui_element_ontology import UIElementOntologyPayload


TEXT_TYPES = {"text", "label", "header", "footer"}
IMAGE_TYPES = {"image", "avatar"}
ICON_TYPES = {"icon", "icon_button"}
DIVIDER_TYPES = {"divider", "separator"}

INTERACTIVE_TYPES = {
    "button",
    "input",
    "search_input",
    "tab",
    "switch",
    "checkbox",
    "radio",
    "select",
    "icon_button",
}

ROUNDED_RECTANGLE_TYPES = {"button", "badge", "input", "search_input"}
RECTANGLE_TYPES = {
    "image",
    "card",
    "container",
    "page",
    "list",
    "list_item",
    "navigation",
    "modal",
    "toolbar",
}


def _normalize_type(raw_type: Any) -> str:
    return str(raw_type or "").strip().lower()


def _map_type(old_type: str) -> str:
    if old_type in TEXT_TYPES:
        return "text"
    if old_type in IMAGE_TYPES:
        return "image"
    if old_type in ICON_TYPES:
        return "icon"
    if old_type in DIVIDER_TYPES:
        return "divider"
    return "region"


def _infer_shape(old_type: str) -> str:
    if old_type in DIVIDER_TYPES:
        return "line"
    if old_type == "avatar":
        return "circle"
    if old_type in ROUNDED_RECTANGLE_TYPES:
        return "rounded_rectangle"
    if old_type in RECTANGLE_TYPES:
        return "rectangle"
    return "unknown"


def convert_vision_payload_to_ontology(payload: dict) -> dict:
    """Convert legacy VisionLayoutPayload v1.0 into UI Element Ontology v0.1."""
    source = deepcopy(payload or {})
    elements = []

    for raw_element in source.get("elements") or []:
        if not isinstance(raw_element, dict):
            continue
        old_type = _normalize_type(raw_element.get("type"))
        text = raw_element.get("text")
        element = {
            "id": str(raw_element.get("id") or ""),
            "type": _map_type(old_type),
            "bbox": deepcopy(raw_element.get("bbox")),
            "interactive": old_type in INTERACTIVE_TYPES,
            "shape": _infer_shape(old_type),
            "text_content": text if text else None,
            "parent_id": raw_element.get("parent_id"),
            "children_ids": list(raw_element.get("children_ids") or []),
        }
        elements.append(element)

    ontology_payload = {
        "schema_version": "ui_element_ontology_v0.1",
        "metadata": {
            "source_schema_version": source.get("schema_version"),
        },
        "elements": elements,
    }
    return UIElementOntologyPayload.model_validate(ontology_payload).model_dump()
