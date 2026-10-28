"""One symbolic grouping call, followed by deterministic allocation; no repair."""
import json
from pathlib import Path

from src.agents.frozen_region_planner import frozen_inventory, inventory_hash
from src.utils.text_evidence_contract import source_spans
from src.utils.semantic_page_plan import parse_semantic_json
from src.utils.symbolic_flow_layout import compile_symbolic_flow, expand_flat_program


def generate_symbolic_flow(state, vision, *, request, speech, frame, viewport, image_data_url, client, model, output, flat_program=False):
    if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/'):
        raise ValueError('Same fresh image required')
    payload = {'target_viewport': viewport, 'frame': frame, 'immutable_entities': frozen_inventory(state),
        'inventory_sha256': inventory_hash(frozen_inventory(state)), 'vision_observations': vision,
        'text_spans': source_spans({'request': request, 'speech': speech})}
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / 'symbolic_flow_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf8')
    prompt = (Path(__file__).resolve().parents[1] / ('prompts/symbolic_flat.md' if flat_program else 'prompts/symbolic_flow.md')).read_text(encoding='utf8')
    response = client.chat.completions.create(model=model, temperature=0.3, max_tokens=8192, timeout=600,
        response_format={'type': 'json_object'}, messages=[{'role': 'system', 'content': prompt},
        {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)},
         {'type': 'image_url', 'image_url': {'url': image_data_url}}]}])
    raw = response.choices[0].message.content or ''
    (output / 'symbolic_flow_raw.txt').write_text(raw, encoding='utf8')
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Symbolic tree truncated; no retry')
    parsed = parse_semantic_json(raw)
    (output / 'symbolic_flow_parsed.json').write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf8')
    tree = expand_flat_program(parsed) if flat_program else parsed
    (output / 'symbolic_flow_expanded.json').write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf8')
    result = compile_symbolic_flow(tree, state, vision, request=request, speech=speech, frame=frame, viewport=viewport)
    (output / 'ui_state.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result
