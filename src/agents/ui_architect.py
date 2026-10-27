import copy
import json
import os
from typing import Any

from src.priors import apply_ui_priors
from src.utils.layout_solver import solve_ui_layout
from src.utils.pipeline_trace import traced_stage, trace_event

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

DEFAULT_MOBILE_VIEWPORT = {"width": 375, "height": 812}
DEFAULT_PC_VIEWPORT = {"width": 1440, "height": 900}


def _get_openai_client():
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        max_retries=0, timeout=600,
    )


def read_ui_architect_prompt():
    """Read the UI Architect system prompt."""
    prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/ui_architect.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "You are a UI architect. Fuse user intent and validated vision elements "
            "into a UI-State JSON contract."
        )


def _infer_viewport(vision_elements: dict | None, ui_state: dict | None = None) -> dict[str, int]:
    existing = (ui_state or {}).get("page_meta", {}).get("viewport")
    if isinstance(existing, dict):
        width = existing.get("width")
        height = existing.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return {"width": width, "height": height}

    orientation = (vision_elements or {}).get("canvas", {}).get("orientation")
    if orientation == "landscape":
        return dict(DEFAULT_PC_VIEWPORT)
    return dict(DEFAULT_MOBILE_VIEWPORT)


def infer_locale_from_text(text: str | None) -> str:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in ("english", "英文", "英语", "overseas", "foreign users", "global users")):
        return "en"
    if any(marker in lowered for marker in ("中文", "chinese", "zh-cn", "zh_cn")):
        return "zh-CN"
    ascii_letters = sum(1 for ch in (text or "") if ("a" <= ch.lower() <= "z"))
    cjk_chars = sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")
    return "en" if ascii_letters >= 12 and ascii_letters > cjk_chars * 2 else "zh-CN"


def _pixel_bbox_from_normalized(bbox: dict[str, Any], viewport: dict[str, int]) -> list[int]:
    """Return UI-State bbox in [x_min, y_min, x_max, y_max] pixel order."""
    width = viewport["width"]
    height = viewport["height"]
    x_min = max(0.0, min(1.0, float(bbox["x_min"])))
    y_min = max(0.0, min(1.0, float(bbox["y_min"])))
    x_max = max(0.0, min(1.0, float(bbox["x_max"])))
    y_max = max(0.0, min(1.0, float(bbox["y_max"])))

    xmin_px = int(round(x_min * width))
    ymin_px = int(round(y_min * height))
    xmax_px = int(round(x_max * width))
    ymax_px = int(round(y_max * height))

    xmax_px = min(width, max(xmin_px + 1, xmax_px))
    ymax_px = min(height, max(ymin_px + 1, ymax_px))
    xmin_px = min(max(0, xmin_px), width - 1)
    ymin_px = min(max(0, ymin_px), height - 1)
    return [xmin_px, ymin_px, xmax_px, ymax_px]


def _clamp_pixel_bbox(raw_bbox: Any, viewport: dict[str, int]) -> list[int] | None:
    """Clamp a model-provided [x_min, y_min, x_max, y_max] bbox to the viewport."""
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        xmin, ymin, xmax, ymax = [int(round(float(v))) for v in raw_bbox]
    except Exception:
        return None

    width = viewport["width"]
    height = viewport["height"]
    xmin = min(max(0, xmin), width - 1)
    ymin = min(max(0, ymin), height - 1)
    xmax = min(width, max(xmin + 1, xmax))
    ymax = min(height, max(ymin + 1, ymax))
    return [xmin, ymin, xmax, ymax]


def _fallback_element_from_vision(element: dict[str, Any], viewport: dict[str, int]) -> dict[str, Any]:
    return {
        "id": element.get("id"),
        "type": element.get("type", "unknown"),
        "text": element.get("text") or element.get("description") or "",
        "spatial_info": {
            "bbox": _pixel_bbox_from_normalized(element["bbox"], viewport),
            "source": "vision_bbox",
        },
        "rpa_action": "",
    }


@traced_stage('architect.geometry_merge')
def repair_ui_state_with_vision(ui_state: dict, vision_elements: dict, preferred_locale: str | None = None) -> dict:
    """Use validated vision bboxes as the authoritative UI-State geometry.

    The LLM may enrich semantic fields, but geometry must stay within the target
    viewport. UI-State uses pixel bboxes in [x_min, y_min, x_max, y_max] order.
    """
    if not isinstance(ui_state, dict):
        ui_state = {}
    if not isinstance(vision_elements, dict):
        return ui_state

    viewport = _infer_viewport(vision_elements, ui_state)
    repaired = copy.deepcopy(ui_state)
    page_meta = repaired.setdefault("page_meta", {})
    page_meta.setdefault("inferred_device", "mobile" if viewport["width"] <= 600 else "pc")
    page_meta.setdefault("confidence", "medium")
    page_meta["viewport"] = viewport
    page_meta["locale"] = preferred_locale or page_meta.get("locale") or "zh-CN"

    vision_by_id = {
        element.get("id"): element
        for element in vision_elements.get("elements", [])
        if isinstance(element, dict) and element.get("id") and isinstance(element.get("bbox"), dict)
    }

    model_elements = repaired.get("elements")
    if not isinstance(model_elements, list):
        model_elements = []

    fusion_mode = os.getenv('UI_FUSION_MODE', 'exact_id')
    if fusion_mode not in {'exact_id', 'source_alignment_v1'}:
        raise ValueError('Unsupported UI_FUSION_MODE')
    if fusion_mode == 'source_alignment_v1':
        from src.utils.source_alignment import align_source_ids
        model_elements, alignment = align_source_ids(model_elements, list(vision_by_id.values()), viewport)
        trace_event('architect.source_alignment', decisions=alignment,
                    policy='reciprocal_geometry_type_text_v1')
        page_meta['source_alignment'] = {'version': 'v1',
            'matched_count': sum(d['vision_id'] is not None for d in alignment),
            'unresolved_count': sum(d['vision_id'] is None for d in alignment)}

    used_ids: set[str] = set()
    decisions = []
    repaired_elements: list[dict[str, Any]] = []
    for index, model_element in enumerate(model_elements, start=1):
        if not isinstance(model_element, dict):
            decisions.append({'index':index,'decision':'drop','reason':'model_element_not_object'})
            continue
        element = copy.deepcopy(model_element)
        element_id = element.get("id") or f"e{index}"
        element["id"] = element_id
        vision_element = vision_by_id.get(element_id)

        if vision_element:
            element.setdefault("type", vision_element.get("type", "unknown"))
            if not element.get("text"):
                element["text"] = vision_element.get("text") or vision_element.get("description") or ""
            spatial_info = element.setdefault("spatial_info", {})
            spatial_info["bbox"] = _pixel_bbox_from_normalized(vision_element["bbox"], viewport)
            spatial_info["source"] = "vision_bbox"
            used_ids.add(element_id)
        else:
            spatial_info = element.get("spatial_info")
            if isinstance(spatial_info, dict):
                clamped = _clamp_pixel_bbox(spatial_info.get("bbox"), viewport)
                if clamped:
                    spatial_info["bbox"] = clamped
                else:
                    decisions.append({'id':element_id,'decision':'drop','reason':'unmatched_id_invalid_bbox'})
                    continue
            else:
                decisions.append({'id':element_id,'decision':'drop','reason':'unmatched_id_missing_spatial_info'})
                continue

        element.setdefault("rpa_action", "")
        repaired_elements.append(element)
        decisions.append({'id':element_id,'decision':'keep','reason':'matched_vision_id_geometry' if vision_element else 'unmatched_model_id_clamped_geometry'})

    for vision_id, vision_element in vision_by_id.items():
        if vision_id not in used_ids:
            fallback = _fallback_element_from_vision(vision_element, viewport)
            if fusion_mode == 'source_alignment_v1':
                fallback['source_refs'] = [{'source': 'vision', 'id': vision_id}]
            repaired_elements.append(fallback)
            decisions.append({'id':vision_id,'decision':'append_vision_fallback','reason':'vision_id_not_used_by_model'})

    repaired["elements"] = repaired_elements
    trace_event('architect.geometry_merge.decisions',decisions=decisions,
                matching_policy=fusion_mode)
    return repaired


@traced_stage('architect.generate')
def generate_ui_state(user_intent: str, vision_elements: dict, preferred_locale: str | None = None, image_data_url: str | None = None) -> dict:
    """Fuse user intent and validated vision data into a UI-State JSON contract."""
    structure_mode = os.getenv('UI_STRUCTURE_MODE', 'baseline')
    if structure_mode not in {'baseline','hierarchy_v1','hierarchy_evidence_v1','hierarchy_partial_evidence_v1','hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
        raise ValueError('Unsupported structure mode')
    if structure_mode in {'hierarchy_v1','hierarchy_evidence_v1','hierarchy_partial_evidence_v1','hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
        from pathlib import Path
        system_prompt = (Path(__file__).resolve().parents[1]/'prompts/ui_architect_hierarchy.md').read_text(encoding='utf-8')
        if structure_mode in {'hierarchy_evidence_v1','hierarchy_partial_evidence_v1','hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1'}:
            system_prompt += '\n' + (Path(__file__).resolve().parents[1]/'prompts/ui_architect_relation_evidence.md').read_text(encoding='utf-8')
        if structure_mode == 'hierarchy_registry_v1':
            system_prompt += '\n' + (Path(__file__).resolve().parents[1]/'prompts/ui_architect_container_registry.md').read_text(encoding='utf-8')
        if structure_mode in {'hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
            system_prompt += '\n' + (Path(__file__).resolve().parents[1]/'prompts/ui_architect_container_inline.md').read_text(encoding='utf-8')
        if structure_mode == 'hierarchy_node_evidence_v1':
            system_prompt += '\n' + (Path(__file__).resolve().parents[1]/'prompts/ui_architect_node_evidence.md').read_text(encoding='utf-8')
    else:
        system_prompt = read_ui_architect_prompt()
    user_content = f"""
[User Intent]
{user_intent}

[Preferred Locale]
{preferred_locale or infer_locale_from_text(user_intent)}

[Vision Elements]
{json.dumps(vision_elements, ensure_ascii=False, indent=2)}

Return the final fused UI-State JSON.
"""

    request_content = user_content
    if structure_mode in {'hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
        if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/') or ';base64,' not in image_data_url:
            raise ValueError('Image-grounded architect requires the existing image data URL')
        request_content = [{'type':'text','text':user_content},
                           {'type':'image_url','image_url':{'url':image_data_url}}]
        import hashlib
        trace_event('architect.image_context', provided=True,
                    data_url_sha256=hashlib.sha256(image_data_url.encode('utf-8')).hexdigest(),
                    policy='same_image_as_vision; no_extra_model_call')
    try:
        print("UI Architect is fusing business intent with validated vision geometry...")
        planner_model = os.getenv("CODER_PROD_MODEL", os.getenv("CODER_MODEL", "deepseek-ai/DeepSeek-V3"))

        response = _get_openai_client().chat.completions.create(
            model=planner_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request_content},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        raw_json_str = response.choices[0].message.content
        ui_state = json.loads(raw_json_str)
        trace_event('architect.model_parsed',output=ui_state)
        specialist_mode = os.getenv('UI_RELATION_SPECIALIST_MODE', 'off')
        if specialist_mode in {'source_ledger_v1', 'container_slots_v1'}:
            from src.agents.relation_specialist import refine_relation_state
            ui_state = refine_relation_state(ui_state, user_intent, planner_model, _get_openai_client(), mode=specialist_mode)
        return finalize_ui_state(ui_state, user_intent, vision_elements, structure_mode, preferred_locale)

    except json.JSONDecodeError as exc:
        print(f"UI Architect JSON parse failed: {exc}")
        return {"error": "JSON_PARSE_ERROR"}
    except Exception as exc:
        print(f"UI Architect failed: {exc}")
        return {"error": str(exc)}


@traced_stage('architect.finalize')
def finalize_ui_state(ui_state, user_intent, vision_elements, structure_mode, preferred_locale=None):
    if structure_mode in {'hierarchy_v1','hierarchy_evidence_v1','hierarchy_partial_evidence_v1','hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
        from src.utils.hierarchy_contract import build_structure, solve_hierarchy
        if structure_mode in {'hierarchy_evidence_v1','hierarchy_partial_evidence_v1','hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
            from src.utils.relation_evidence import apply_relation_evidence
            if structure_mode in {'hierarchy_registry_v1','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'}:
                from src.utils.container_registry import compile_container_registry
                ui_state = compile_container_registry(ui_state, vision_elements, user_intent,
                    inline=structure_mode in {'hierarchy_registry_inline_v1','hierarchy_registry_image_v1','hierarchy_node_evidence_v1'})
            if structure_mode == 'hierarchy_node_evidence_v1':
                from src.utils.node_relation_evidence import compile_node_relations
                ui_state = compile_node_relations(ui_state)
            if os.getenv('UI_RELATION_AGGREGATION_MODE','off') == 'validated_union_v1':
                from src.utils.relation_aggregation import aggregate_relation_sources
                ui_state = aggregate_relation_sources(ui_state,user_intent)
            else:
                ui_state = apply_relation_evidence(ui_state, user_intent,
                    isolate_source_errors=structure_mode in {"hierarchy_partial_evidence_v1", "hierarchy_registry_v1", "hierarchy_registry_inline_v1", "hierarchy_registry_image_v1", "hierarchy_node_evidence_v1"})
        return solve_hierarchy(build_structure(ui_state, vision_elements))
    repaired = repair_ui_state_with_vision(
        ui_state,
        vision_elements,
        preferred_locale or infer_locale_from_text(user_intent),
    )
    priorized = apply_ui_priors(repaired, user_intent=user_intent, vision_elements=vision_elements)
    return solve_ui_layout(priorized)


if __name__ == "__main__":
    mock_user_intent = "Create a simple approval form."
    mock_vision_data = {
        "canvas": {"width": 390, "height": 844, "orientation": "portrait"},
        "elements": [
            {"id": "e1", "type": "input", "text": "Name", "bbox": {"x_min": 0.1, "y_min": 0.1, "x_max": 0.9, "y_max": 0.16}},
            {"id": "e2", "type": "button", "text": "Submit", "bbox": {"x_min": 0.3, "y_min": 0.8, "x_max": 0.7, "y_max": 0.9}},
        ],
    }
    result = generate_ui_state(mock_user_intent, mock_vision_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
