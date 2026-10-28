"""One bounded source-evidence audit, with an explicit verdict for each text node."""
import copy
import json
from pathlib import Path
from src.utils.pipeline_trace import traced_stage


def compile_input_audit(state, vision, intent, declaration):
    if not isinstance(declaration, dict) or set(declaration) != {'input_audit'}:
        raise ValueError('Expected only input_audit')
    slots = {e['id']: e for e in vision['elements'] if e.get('type') == 'text'}
    rows = declaration['input_audit']
    if not isinstance(rows, list):
        raise ValueError('Input audit must be a list')
    seen = set(); proposals = []; unresolved = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'vision_id', 'verdict', 'evidence_quote'}:
            raise ValueError('Audit cannot edit nodes or omit verdict fields')
        vid = row['vision_id']; verdict = row['verdict']; quote = row['evidence_quote']
        if not isinstance(vid, str) or vid not in slots or vid in seen:
            raise ValueError('Unknown or repeated audit slot')
        seen.add(vid)
        if verdict not in {'editable', 'not_editable', 'uncertain'} or not isinstance(quote, str):
            raise ValueError('Invalid audit verdict')
        if quote and quote not in intent:
            raise ValueError('Audit quote is absent from source')
        if verdict == 'editable':
            proposals.append({'vision_id': vid, 'target_type': 'input', 'evidence_quote': quote})
        elif verdict == 'uncertain':
            unresolved.append(copy.deepcopy(row))
    if seen != set(slots):
        raise ValueError('Missing input audit slots; omission is not a negative verdict')
    result = copy.deepcopy(state)
    result['semantic_input_overrides'] = proposals
    result.setdefault('page_meta', {})['input_semantic_audit'] = {
        'version': 'input_audit_v1', 'eligible_count': len(slots),
        'reviewed_count': len(rows), 'editable_proposals': len(proposals),
        'uncertain_count': len(unresolved), 'uncertain': unresolved,
        'verdicts': copy.deepcopy(rows),
        'limits': 'Node coverage only, not spoken requirement coverage. Negative verdicts require semantic review.'}
    return result


@traced_stage('architect.input_semantic_audit')
def audit_input_semantics(state, vision, intent, model, client):
    nodes = [{'vision_id': e['id'], 'type': e['type'], 'text': e.get('text') or ''}
             for e in vision['elements'] if e.get('type') == 'text']
    if not nodes:
        return compile_input_audit(state, vision, intent, {'input_audit': []})
    prompt = (Path(__file__).resolve().parents[1] / 'prompts/input_semantic_audit.md').read_text(encoding='utf-8')
    previous = getattr(client, 'stage', None)
    if previous is not None:
        client.stage = 'input_semantic_auditor'
    try:
        response = client.chat.completions.create(model=model, temperature=0,
            max_tokens=8192, timeout=600, response_format={'type': 'json_object'},
            messages=[{'role': 'system', 'content': prompt},
                      {'role': 'user', 'content': json.dumps({'original_intent': intent,
                       'immutable_text_slots': nodes}, ensure_ascii=False)}])
    finally:
        if previous is not None:
            client.stage = previous
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Input audit truncated; no additional attempt')
    return compile_input_audit(state, vision, intent,
        json.loads(response.choices[0].message.content))
