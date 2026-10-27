"""A bounded, relation-only evidence stage; never edit source nodes or HTML."""
import copy
import json
from pathlib import Path
from src.utils.pipeline_trace import traced_stage


@traced_stage('architect.relation_specialist')
def refine_relation_state(state, user_intent, model, client):
    prompt = (Path(__file__).resolve().parents[1] / 'prompts/relation_specialist.md').read_text(encoding='utf-8')
    # Do not bias extraction with the planner's proposed parents or evaluator labels.
    nodes = [{'id': e['id'], 'vision_id': e.get('vision_id'), 'type': e.get('type'),
              'text': e.get('text') or ''} for e in state['elements']]
    previous = getattr(client, 'stage', None)
    if previous is not None:
        client.stage = 'relation_specialist'
    try:
        response = client.chat.completions.create(model=model, temperature=0,
            max_tokens=8192, timeout=600, response_format={'type': 'json_object'},
            messages=[{'role': 'system', 'content': prompt},
                      {'role': 'user', 'content': json.dumps({'user_intent': user_intent, 'immutable_nodes': nodes}, ensure_ascii=False)}])
    finally:
        if previous is not None:
            client.stage = previous
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Specialist output truncated; no additional attempt')
    declarations = json.loads(response.choices[0].message.content)
    if not isinstance(declarations, dict) or set(declarations) != {'relationships'} or not isinstance(declarations['relationships'], list):
        raise ValueError('Specialist may only output a relationship ledger')
    result = copy.deepcopy(state)
    result['relationships'] = declarations['relationships']
    result.setdefault('page_meta', {})['relation_specialist'] = {
        'version': 'source-ledger-v1', 'additional_calls': 1,
        'node_edits_allowed': False, 'source_validation': 'pending',
        'semantic_review': 'required; model extraction is not ground truth'}
    return result
