from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PRIORS_PATH = Path(__file__).with_name("ui_priors.json")


@lru_cache(maxsize=1)
def load_ui_priors() -> dict[str, Any]:
    with PRIORS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def infer_page_kind(user_intent: str | None, ui_state: dict[str, Any] | None = None) -> str | None:
    text = " ".join(
        [
            user_intent or "",
            json.dumps((ui_state or {}).get("page_meta", {}), ensure_ascii=False),
        ]
    ).lower()
    for page_kind, spec in load_ui_priors().get("page_kinds", {}).items():
        markers = spec.get("intent_markers", [])
        if any(str(marker).lower() in text for marker in markers):
            return page_kind

    elements = (ui_state or {}).get("elements", [])
    if isinstance(elements, list):
        evidence = " ".join(
            " ".join(
                str(element.get(key) or "")
                for key in ("type", "text", "semantic_role", "rpa_action")
            ).lower()
            for element in elements
            if isinstance(element, dict)
        )
        commerce_markers = (
            "购物车", "立即购买", "立即下单", "价格", "商品", "尺码",
            "add_to_cart", "buy_now", "place_order", "product", "price",
        )
        score = sum(1 for marker in commerce_markers if marker in evidence)
        has_image = any(
            isinstance(element, dict) and str(element.get("type") or "").lower() == "image"
            for element in elements
        )
        has_action = any(
            marker in evidence for marker in ("购物车", "立即购买", "立即下单", "add_to_cart", "buy_now", "place_order")
        )
        if has_image and has_action and score >= 2:
            return "mobile_product_detail"
    return None


def _viewport(ui_state: dict[str, Any]) -> dict[str, int]:
    viewport = ui_state.get("page_meta", {}).get("viewport")
    if isinstance(viewport, dict):
        width = viewport.get("width")
        height = viewport.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return {"width": width, "height": height}
    return {"width": 375, "height": 812}


def _is_mobile(ui_state: dict[str, Any]) -> bool:
    meta = ui_state.get("page_meta", {})
    device = str(meta.get("inferred_device", "")).lower()
    return device == "mobile" or _viewport(ui_state)["width"] <= 600


def _looks_like_back_control(element: dict[str, Any]) -> bool:
    text = str(element.get("text") or "").strip().lower()
    role = str(element.get("semantic_role") or element.get("role") or "").lower()
    action = str(element.get("rpa_action") or "").lower()
    element_type = str(element.get("type") or "").lower()
    return (
        role in {"back", "navigate_back"}
        or action in {"go_back", "navigate_back", "back"}
        or text in {"<", "←", "back", "返回"}
        or ("back" in action and element_type in {"button", "icon_button", "icon"})
    )


def _bbox_from_ratio(ratio: list[float], viewport: dict[str, int]) -> list[int]:
    width = viewport["width"]
    height = viewport["height"]
    x1, y1, x2, y2 = ratio
    bbox = [
        int(round(max(0.0, min(1.0, x1)) * width)),
        int(round(max(0.0, min(1.0, y1)) * height)),
        int(round(max(0.0, min(1.0, x2)) * width)),
        int(round(max(0.0, min(1.0, y2)) * height)),
    ]
    bbox[2] = min(width, max(bbox[0] + 1, bbox[2]))
    bbox[3] = min(height, max(bbox[1] + 1, bbox[3]))
    return bbox


def _build_prior_element(slot_spec: dict[str, Any], viewport: dict[str, int]) -> dict[str, Any]:
    template = copy.deepcopy(slot_spec.get("element", {}))
    ratio = template.pop("bbox_ratio")
    return {
        **template,
        "spatial_info": {
            "bbox": _bbox_from_ratio(ratio, viewport),
            "source": "ui_prior",
        },
        "prior": {
            "slot": slot_spec.get("slot"),
            "severity": slot_spec.get("severity", "recommended"),
            "confidence": 0.72,
        },
    }


def apply_ui_priors(
    ui_state: dict[str, Any],
    user_intent: str | None = None,
    vision_elements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply conservative UI priors after vision geometry repair.

    The first supported prior recovers a mobile product-detail back affordance
    when no back/close/home control was detected by the vision and architect
    stages. The inserted element is explicitly marked as source=ui_prior.
    """
    if not isinstance(ui_state, dict) or ui_state.get("error"):
        return ui_state

    repaired = copy.deepcopy(ui_state)
    elements = repaired.setdefault("elements", [])
    if not isinstance(elements, list):
        repaired["elements"] = []
        elements = repaired["elements"]

    page_meta = repaired.setdefault("page_meta", {})
    page_kind = page_meta.get("page_kind") or infer_page_kind(user_intent, repaired)
    if page_kind:
        page_meta["page_kind"] = page_kind

    if not page_kind or not _is_mobile(repaired):
        return repaired

    prior_spec = load_ui_priors().get("page_kinds", {}).get(page_kind, {})
    warnings = repaired.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        repaired["warnings"] = warnings

    for slot_spec in prior_spec.get("required_slots", []):
        slot = slot_spec.get("slot")
        if slot != "top_navigation_back":
            continue
        if any(isinstance(element, dict) and _looks_like_back_control(element) for element in elements):
            continue
        prior_element = _build_prior_element(slot_spec, _viewport(repaired))
        elements.insert(0, prior_element)
        warnings.append(f"ui_prior_inserted:{slot}")

    return repaired
