"""Single layout-only call over a code-owned, immutable semantic inventory."""
import copy
import hashlib
import json
from pathlib import Path

from src.utils.region_layout_contract import compile_region_structure
from src.utils.semantic_page_plan import parse_semantic_json
from src.utils.text_evidence_contract import source_spans


IDENTITY_FIELDS = ('id', 'vision_id', 'origin', 'type', 'text', 'parent_id', 'rpa_action', 'source_refs')


def frozen_inventory(state):
    return [{k: copy.deepcopy(e[k]) for k in IDENTITY_FIELDS if k in e} for e in state['elements']]


def inventory_hash(inventory):
    return hashlib.sha256(json.dumps(inventory, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def compile_frozen_regions(plan, state, vision, *, request, speech, frame, viewport):
    if not isinstance(plan, dict) or set(plan) != {'version', 'root_region_id', 'regions', 'placements'}:
        raise ValueError('Layout-only response must contain exactly the region plan, no semantic edits')
    inventory = frozen_inventory(state)
    sources = {'request': request, 'speech': speech}
    clean = {'page_meta': {'viewport': {k: viewport[k] for k in ('width', 'height')},
                           'locale': state.get('page_meta', {}).get('locale', 'zh-CN')},
             'elements': copy.deepcopy(inventory)}
    result = compile_region_structure(clean, vision, frame=frame, viewport=viewport,
        region_plan=plan, text_sources=sources, text_evidence=source_spans(sources))
    if frozen_inventory(result) != inventory:
        raise ValueError('Layout compilation changed immutable semantics')
    result['page_meta']['frozen_inventory_layout'] = {
        'version': 'frozen-regions-v1', 'inventory_sha256': inventory_hash(inventory),
        'identity_type_text_parent_action_preserved': True,
        'requirements_coverage': None, 'missing_semantics_repaired': False,
        'semantic_review_required': True, 'user_effect_evaluated': False,
        'status': 'layout_compiled_full_requirement_coverage_unknown'}
    return result


def generate_frozen_region_plan(state, vision, *, request, speech, frame, viewport,
                                image_data_url, client, model, output):
    if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/'):
        raise ValueError('Same fresh image required')
    inventory = frozen_inventory(state)
    payload = {'target_viewport': viewport, 'frame': frame,
        'text_spans': source_spans({'request': request, 'speech': speech}),
        'immutable_entities': inventory, 'vision_observations': vision,
        'inventory_sha256': inventory_hash(inventory)}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'region_plan_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    prompt = (Path(__file__).resolve().parents[1] / 'prompts/frozen_region_plan.md').read_text(encoding='utf-8')
    response = client.chat.completions.create(model=model, temperature=0.3, max_tokens=8192, timeout=600,
        response_format={'type': 'json_object'}, messages=[{'role': 'system', 'content': prompt},
        {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)},
            {'type': 'image_url', 'image_url': {'url': image_data_url}}]}])
    raw = response.choices[0].message.content or ''
    (output / 'region_plan_raw.txt').write_text(raw, encoding='utf-8')
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Region plan truncated; no retry')
    plan = parse_semantic_json(raw)
    (output / 'region_plan_parsed.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    result = compile_frozen_regions(plan, state, vision, request=request, speech=speech, frame=frame, viewport=viewport)
    (output / 'ui_state.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
