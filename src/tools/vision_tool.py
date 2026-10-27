import os
import io
import json
import time
import base64
from typing import Tuple, Optional, List, Dict, Any
from PIL import Image, ImageFilter
from pydantic import ValidationError
from dotenv import load_dotenv

from src.schemas.vision_schema import VisionLayoutPayload, VisionLayoutResult, VisionValidation, CanvasInfo, UIElement
from src.prompts.template import get_prompt_template
from langchain_core.prompts import PromptTemplate
from openai import OpenAI
from src.utils.pipeline_trace import traced_stage, trace_event

load_dotenv()


TYPE_ALIAS = {
    'label': 'text',
    'input_text': 'input',
    'text_input': 'input',
    'textbox': 'input',
    'nav': 'navigation',
    'listitem': 'list_item',
    'search': 'search_input',
    'img': 'image',
    'separator': 'divider'
}


def _extract_json_object(s: str) -> Optional[str]:
    start = s.find('{')
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                return s[start:i+1]
    return None


def _encode_image_to_data_url(image: Image.Image, max_side: int = 1024) -> Tuple[str, int, int]:
    w, h = image.size
    scale = 1.0
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f"data:image/jpeg;base64,{b64}", int(w), int(h)


def _parse_bbox_candidate(elem: dict) -> Optional[Dict[str, float]]:
    # Support bbox formats per spec
    if 'bbox' in elem:
        b = elem['bbox']
    elif 'spatial_info' in elem and isinstance(elem['spatial_info'], dict) and 'bbox' in elem['spatial_info']:
        b = elem['spatial_info']['bbox']
    elif 'pixel_bbox' in elem:
        # pixel_bbox is handled by caller when canvas size available
        b = {'pixel_bbox': elem['pixel_bbox']}
    else:
        return None

    if isinstance(b, dict) and all(k in b for k in ('x_min', 'y_min', 'x_max', 'y_max')):
        return {'x_min': float(b['x_min']), 'y_min': float(b['y_min']), 'x_max': float(b['x_max']), 'y_max': float(b['y_max'])}
    if isinstance(b, list) and len(b) == 4:
        return {'x_min': float(b[0]), 'y_min': float(b[1]), 'x_max': float(b[2]), 'y_max': float(b[3])}
    if isinstance(b, dict) and 'pixel_bbox' in b:
        return {'pixel_bbox': b['pixel_bbox']}
    return None


def _map_type(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    lt = t.lower()
    return TYPE_ALIAS.get(lt, lt)


def _normalize_element(raw: dict, canvas_w: int, canvas_h: int, idx: int) -> Tuple[Optional[dict], Optional[str]]:
    # Build a strict whitelist element dict; return (element_dict, error_key)
    el = {}
    eid = raw.get('id')
    # id may be None -> caller will fill stable ids
    if eid:
        el['id'] = str(eid)

    el_type = _map_type(raw.get('type'))
    if el_type:
        el['type'] = el_type
    else:
        el['type'] = 'unknown'

    # text mapping
    if 'text' in raw:
        el['text'] = raw['text']
    elif 'label' in raw:
        el['text'] = raw['label']

    if 'description' in raw:
        el['description'] = raw['description']

    # confidence
    try:
        el['confidence'] = float(raw.get('confidence', 0.5))
    except Exception:
        el['confidence'] = 0.5

    el['visible'] = bool(raw.get('visible', True))
    el['parent_id'] = raw.get('parent_id')
    el['children_ids'] = list(dict.fromkeys(raw.get('children_ids') or []))
    el['source'] = raw.get('source', 'vision') if raw.get('source') in ('vision', 'inferred') else 'vision'

    bbox_candidate = _parse_bbox_candidate(raw)
    if bbox_candidate is None:
        return None, 'missing_bbox'

    # Handle pixel_bbox explicitly
    if 'pixel_bbox' in bbox_candidate:
        px = bbox_candidate['pixel_bbox']
        if not (isinstance(px, list) and len(px) == 4):
            return None, 'invalid_pixel_bbox_format'
        # normalize using canvas
        x_min = px[0] / canvas_w
        y_min = px[1] / canvas_h
        x_max = px[2] / canvas_w
        y_max = px[3] / canvas_h
    else:
        x_min = float(bbox_candidate['x_min'])
        y_min = float(bbox_candidate['y_min'])
        x_max = float(bbox_candidate['x_max'])
        y_max = float(bbox_candidate['y_max'])
        # If any coordinate >1.0 and not pixel_bbox -> ambiguous
        if any(v > 1.0 for v in (x_min, y_min, x_max, y_max)):
            return None, 'ambiguous_non_normalized_bbox'

    # Strict ordering
    if not (0.0 <= x_min < x_max <= 1.0 and 0.0 <= y_min < y_max <= 1.0):
        return None, 'invalid_bbox_order'

    el['bbox'] = {'x_min': round(x_min, 6), 'y_min': round(y_min, 6), 'x_max': round(x_max, 6), 'y_max': round(y_max, 6)}

    return el, None


def analyze_image_complexity(image_path: str) -> Dict[str, Any]:
    # Lightweight complexity metrics using PIL
    try:
        img = Image.open(image_path).convert('L')
        w, h = img.size
        arr = img
        # edge density via simple Laplacian-ish filter: use FIND_EDGES
        edges = img.filter(ImageFilter.FIND_EDGES)
        edge_pixels = sum(1 for p in edges.getdata() if p > 10)
        total = w * h
        edge_density = edge_pixels / max(1, total)

        # foreground estimation: threshold by mean
        mean = sum(img.getdata()) / total
        fg_pixels = sum(1 for p in img.getdata() if abs(p - mean) > 20)
        foreground_ratio = fg_pixels / max(1, total)

        # connected regions approximation: count blobs via simple downsampled threshold
        down = img.resize((max(32, w//16), max(32, h//16))).point(lambda p: 255 if abs(p - mean) > 20 else 0)
        # crude connected regions: count non-empty boxes
        pixels = down.load()
        dw, dh = down.size
        regions = 0
        for y in range(dh):
            for x in range(dw):
                if pixels[x, y] == 255:
                    regions += 1
        connected_region_count = regions

        return {
            'foreground_ratio': round(foreground_ratio, 4),
            'edge_density': round(edge_density, 4),
            'connected_region_count': int(connected_region_count),
        }
    except Exception:
        return {'foreground_ratio': 0.0, 'edge_density': 0.0, 'connected_region_count': 0}


def _stable_sort_and_id(elements: List[dict]) -> Tuple[List[dict], List[str]]:
    # compute centers and sort top-to-bottom then left-to-right
    def center(e):
        b = e['bbox']
        cx = (b['x_min'] + b['x_max']) / 2.0
        cy = (b['y_min'] + b['y_max']) / 2.0
        return (round(cy, 6), round(cx, 6))

    elems = list(elements)
    elems.sort(key=lambda e: (center(e)[0], center(e)[1]))
    ids = []
    for i, e in enumerate(elems, start=1):
        if 'id' not in e or not e['id']:
            e['id'] = f'e{i:03d}'
        ids.append(e['id'])
    return elems, ids


def _build_reading_order(provided_ro: Optional[List[str]], ids: List[str]) -> Tuple[List[str], bool]:
    # returns (reading_order, repaired_flag)
    if provided_ro:
        ro = []
        repaired = False
        seen = set()
        for rid in provided_ro:
            if rid in ids and rid not in seen:
                ro.append(rid)
                seen.add(rid)
        # append any missing ids
        missing = [i for i in ids if i not in seen]
        if missing:
            ro.extend(missing)
            repaired = True
        return ro, repaired
    else:
        # stable order equals ids order
        return list(ids), False


@traced_stage('vision.extract')
def extract_ui_layout(image_path: str,
                      user_context: Optional[str] = None,
                      previous_layout: Optional[dict] = None,
                      repair_feedback: Optional[dict] = None,
                      audit_logger=None) -> dict:
    """Call the vision model and return a normalized VisionLayoutPayload dict.

    This function will NOT return a 'validation' field from the model; any incoming
    'validation' will be ignored.
    """
    start_ts = time.time()
    if not os.path.exists(image_path):
        return {'error': {'code': 'image_path_not_found', 'message': 'Image path does not exist.'}}

    try:
        img = Image.open(image_path).convert('RGB')
    except Exception as e:
        return {'error': {'code': 'image_read_error', 'message': str(e)}}

    data_url, width, height = _encode_image_to_data_url(img)

    # system prompt
    try:
        raw_template = get_prompt_template('vision_agent')
        system_prompt = PromptTemplate(input_variables=['CURRENT_TIME'], template=raw_template).format(CURRENT_TIME=time.strftime('%c'))
    except Exception:
        system_prompt = 'Please output VisionLayout JSON as specified.'

    # prepare messages
    api_key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('VL_API_KEY') or os.getenv('OPENAI_API_KEY')
    model = os.getenv('VISION_MODEL') or os.getenv('DEFAULT_VISION_MODEL')
    client = None
    if api_key and model:
        try:
            client = OpenAI(api_key=api_key, base_url=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL'))
        except Exception:
            client = None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_context or "请完整解析这张 UI 草图。"},
            {"type": "image_url", "image_url": {"url": data_url}}
        ]}
    ]

    model_out = None
    if client is None:
        # No remote client — return empty payload
        model_out = {'schema_version': '1.0', 'canvas': {'width': width, 'height': height, 'orientation': 'portrait' if height>width else ('landscape' if width>height else 'square')}, 'elements': [], 'reading_order': []}
    else:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            choice = resp.choices[0].message.content
            if isinstance(choice, dict):
                model_out = choice
            else:
                j = _extract_json_object(str(choice))
                if not j:
                    return {'error': {'code': 'no_json_in_model_output', 'message': 'Model returned no JSON.'}, 'raw': str(choice)}
                model_out = json.loads(j)
        except Exception as e:
            return {'error': {'code': 'vision_invoke_failed', 'message': str(e)}}

    exec_time = time.time() - start_ts
    if audit_logger:
        try:
            audit_logger.log_vision_call('extract_ui_layout', image_path, system_prompt[:2000], None if not isinstance(model_out, dict) else json.dumps({'elements_count': len(model_out.get('elements', []))}), {'exec_time': exec_time, 'model': model})
        except Exception:
            pass

    # model_out should be a payload; ignore any model-provided validation
    if isinstance(model_out, dict) and 'validation' in model_out:
        del model_out['validation']

    canvas = {'width': width, 'height': height, 'orientation': 'portrait' if height>width else ('landscape' if width>height else 'square')}

    raw_elements = model_out.get('elements') or model_out.get('items') or []
    trace_event('vision.model_parsed',output=model_out)
    normalized_elements = []
    errors = []
    for i, relem in enumerate(raw_elements):
        el, err = _normalize_element(relem, width, height, i)
        if el:
            normalized_elements.append(el)
        else:
            errors.append(err or 'normalize_failed')

    # ensure stable ids and reading order
    trace_event('vision.normalized_before_ids',output={'elements':normalized_elements},errors=errors)
    elems_sorted, ids = _stable_sort_and_id(normalized_elements)
    ro_provided = model_out.get('reading_order') if isinstance(model_out.get('reading_order'), list) else None
    reading_order, repaired = _build_reading_order(ro_provided, ids)

    payload = {
        'schema_version': '1.0',
        'canvas': canvas,
        'elements': elems_sorted,
        'reading_order': reading_order
    }

    # attach some diagnostic info (not part of payload) for auditing
    diagnostics = {
        'raw_element_count': len(raw_elements),
        'normalized_element_count': len(elems_sorted),
        'reading_order_repaired': repaired,
        'normalize_errors': errors,
    }

    # return payload and diagnostics (caller may run local validation)
    return {'payload': payload, 'diagnostics': diagnostics}


@traced_stage('vision.validate')
def validate_vision_layout(layout_dict: dict, image_path: Optional[str] = None) -> Tuple[dict, VisionValidation]:
    errors: List[str] = []
    warnings: List[str] = []

    if image_path and not os.path.exists(image_path):
        errors.append('image_path_not_found')

    if not isinstance(layout_dict, dict):
        errors.append('layout_not_dict')
        return layout_dict, VisionValidation(valid=False, completeness_score=0.0, element_count=0, errors=errors, warnings=warnings)

    # layout_dict may be either the extract payload wrapper or a raw payload
    payload = layout_dict.get('payload') if 'payload' in layout_dict else layout_dict

    # canvas checks
    canvas = payload.get('canvas')
    if not canvas or not isinstance(canvas.get('width'), int) or not isinstance(canvas.get('height'), int) or canvas.get('width', 0) <= 0 or canvas.get('height', 0) <= 0:
        errors.append('invalid_canvas')
        return payload, VisionValidation(valid=False, completeness_score=0.0, element_count=0, errors=errors, warnings=warnings)

    # enforce reconstructed orientation
    w = canvas['width']; h = canvas['height']
    orientation = 'portrait' if h > w else ('landscape' if w > h else 'square')
    payload['canvas']['orientation'] = orientation

    elements = payload.get('elements') or []
    # element-level checks
    ids = []
    id_map = {}
    for el in elements:
        eid = el.get('id')
        if not eid or not isinstance(eid, str):
            errors.append('empty_id')
            continue
        if eid in id_map:
            errors.append('duplicate_ids')
        ids.append(eid)
        id_map[eid] = el

    # parent/children checks
    for el in elements:
        eid = el.get('id')
        pid = el.get('parent_id')
        if pid:
            if pid == eid:
                errors.append(f'self_parent:{eid}')
            if pid not in id_map:
                errors.append(f'missing_parent:{eid}->{pid}')
            else:
                # ensure bidirectional
                parent = id_map[pid]
                if eid not in parent.get('children_ids', []):
                    warnings.append(f'parent_missing_child_ref:{pid}->{eid}')
        for cid in el.get('children_ids', []):
            if cid == eid:
                errors.append(f'self_child:{eid}')
            if cid not in id_map:
                errors.append(f'missing_child:{eid}->{cid}')

    # detect simple cycles using DFS
    def has_cycle():
        graph = {eid: set(el.get('children_ids', [])) for eid, el in id_map.items()}
        visited = set()
        rec = set()
        def dfs(u):
            visited.add(u); rec.add(u)
            for v in graph.get(u, []):
                if v not in visited:
                    if dfs(v):
                        return True
                elif v in rec:
                    return True
            rec.remove(u)
            return False
        for node in graph:
            if node not in visited:
                if dfs(node):
                    return True
        return False

    if has_cycle():
        errors.append('parent_child_cycle')

    # bbox checks
    invalid_bbox_count = 0
    for el in elements:
        b = el.get('bbox')
        if not b or not all(k in b for k in ('x_min','y_min','x_max','y_max')):
            errors.append(f'missing_bbox:{el.get("id")}')
            invalid_bbox_count += 1
            continue
        x_min = float(b['x_min']); y_min = float(b['y_min']); x_max = float(b['x_max']); y_max = float(b['y_max'])
        if not (0.0 <= x_min < x_max <= 1.0 and 0.0 <= y_min < y_max <= 1.0):
            if x_min >= x_max or y_min >= y_max:
                errors.append(f'invalid_bbox_order:{el.get("id")}')
            else:
                errors.append(f'invalid_bbox:{el.get("id")}')
            invalid_bbox_count += 1

    # reading order
    ro = payload.get('reading_order') or []
    if ro:
        seen = set()
        for rid in ro:
            if rid not in id_map:
                errors.append(f'reading_order_missing_id:{rid}')
            if rid in seen:
                errors.append(f'reading_order_duplicate_id:{rid}')
            seen.add(rid)
        # must cover all visible elements
        missing = [i for i in ids if i not in seen]
        if missing:
            warnings.append('reading_order_repaired')
            payload['reading_order'] = ro + missing
    else:
        # generate stable reading order
        payload['reading_order'] = ids

    # completeness heuristic
    score = 0.0
    if elements:
        coverage = max(0.0, 1.0 - (invalid_bbox_count / max(1, len(elements))))
        text_coverage = sum(1 for e in elements if e.get('text')) / len(elements)
        hierarchy_coverage = 1.0 - (sum(1 for e in elements if e.get('parent_id') and e.get('parent_id') not in id_map) / max(1, len(elements)))
        score = 0.5 * coverage + 0.3 * text_coverage + 0.2 * hierarchy_coverage

    if len(elements) < 2:
        warnings.append('element_count_low')

    valid = len(errors) == 0
    validation = VisionValidation(valid=valid, completeness_score=round(min(1.0, score), 3), element_count=len(elements), errors=errors, warnings=warnings)

    # return result payload + validation
    result = dict(payload)
    result['validation'] = validation.model_dump()
    return result, validation


def select_better_vision_result(first_result: dict, first_validation: VisionValidation, second_result: dict, second_validation: VisionValidation, complexity: Optional[dict] = None) -> bool:
    """Return True if second should be chosen over first per deterministic rules."""
    # prefer valid over invalid
    if second_validation.valid and not first_validation.valid:
        return True
    if first_validation.valid and not second_validation.valid:
        return False

    # both same validity: compare completeness_score
    if second_validation.completeness_score > first_validation.completeness_score:
        return True
    if second_validation.completeness_score < first_validation.completeness_score:
        return False

    # compare errors severity (fewer errors preferred)
    if len(second_validation.errors) < len(first_validation.errors):
        return True
    if len(second_validation.errors) > len(first_validation.errors):
        return False

    # prefer higher detected_bbox_coverage if available in complexity
    if complexity and 'detected_bbox_coverage' in complexity:
        if complexity.get('detected_bbox_coverage', 0) > complexity.get('detected_bbox_coverage', 0):
            return True

    # lastly prefer more elements only as tie-breaker
    if second_validation.element_count > first_validation.element_count:
        return True

    return False
