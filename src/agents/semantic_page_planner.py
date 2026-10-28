"""Single-call semantic-region planning boundary; no repair or implicit retry."""
import json
from pathlib import Path

from src.utils.semantic_page_plan import compile_semantic_plan, parse_semantic_json
from src.utils.text_evidence_contract import source_spans


def generate_semantic_page_plan(vision, *, request, speech, frame, viewport,
                                image_data_url, client, model, output):
    if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/'):
        raise ValueError('Same fresh vision image required')
    spans = source_spans({'request': request, 'speech': speech})
    payload = {'target_viewport': viewport, 'frame': frame,
               'text_spans': spans, 'vision_observations': vision}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'semantic_plan_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    prompt = (Path(__file__).resolve().parents[1] / 'prompts/semantic_page_plan.md').read_text(encoding='utf-8')
    response = client.chat.completions.create(model=model, temperature=0.3, max_tokens=8192, timeout=600,
        response_format={'type': 'json_object'}, messages=[{'role': 'system', 'content': prompt},
        {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)},
          {'type': 'image_url', 'image_url': {'url': image_data_url}}]}])
    raw = response.choices[0].message.content or ''
    (output / 'semantic_plan_raw.txt').write_text(raw, encoding='utf-8')
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Semantic plan truncated; no repair request')
    plan = parse_semantic_json(raw)
    (output / 'semantic_plan_parsed.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    state = compile_semantic_plan(plan, vision, request=request, speech=speech, frame=frame, viewport=viewport)
    (output / 'ui_state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state
