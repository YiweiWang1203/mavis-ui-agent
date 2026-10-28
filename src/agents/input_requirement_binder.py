"""Bind code-owned verbatim editable requirements to immutable visual identities."""
import copy
import json
import re
from pathlib import Path
from src.utils.pipeline_trace import traced_stage
from src.utils.spoken_input_evidence import EDITABLE_BEHAVIOR_PATTERN, NEGATIVE_INPUT_PATTERN


def input_requirement_slots(intent):
    slots = []; unresolved = []
    # Do not strip, paraphrase, truncate, or combine a negative clause away.
    for match in re.finditer(r'.+?(?:[。！？!?]|\.(?=\s|$)|$)', intent, re.M):
        quote = match.group()
        if not re.search(EDITABLE_BEHAVIOR_PATTERN, quote, re.I):
            continue
        row = {'requirement_id': 'r' + str(len(slots) + len(unresolved) + 1),
               'start': match.start(), 'end': match.end(), 'quote': quote}
        reason = 'negative_or_readonly_source' if re.search(NEGATIVE_INPUT_PATTERN, quote, re.I) else (
                 'source_span_exceeds_limit' if len(quote) > 400 else None)
        if reason:
            unresolved.append(dict(row, reason=reason))
        else:
            slots.append(row)
    return slots, unresolved


def compile_requirement_bindings(state, vision, intent, declaration):
    slots, local_unresolved = input_requirement_slots(intent)
    if not isinstance(declaration, dict) or set(declaration) != {'bindings'} or not isinstance(declaration['bindings'], list):
        raise ValueError('Expected only requirement bindings')
    slot_map = {row['requirement_id']: row for row in slots}
    visual = {e['id']: e for e in vision['elements']}
    elements = {e.get('vision_id') or e['id']: e for e in state['elements']}
    if len(visual) != len(vision['elements']) or len(elements) != len(state['elements']):
        raise ValueError('Duplicate source identity')
    seen = set(); bound = []; unresolved = copy.deepcopy(local_unresolved); proposals = []; native = []
    for row in declaration['bindings']:
        if not isinstance(row, dict) or set(row) != {'requirement_id', 'vision_id'}:
            raise ValueError('Binding may only select a requirement and source identity')
        rid = row['requirement_id']; vid = row['vision_id']
        if not isinstance(rid, str) or rid not in slot_map or rid in seen:
            raise ValueError('Unknown or repeated requirement slot')
        seen.add(rid); source = slot_map[rid]
        if vid is None:
            unresolved.append(dict(source, reason='model_unbound')); continue
        if not isinstance(vid, str) or vid not in visual or vid not in elements:
            raise ValueError('Unknown visual source binding')
        v = visual[vid]; e = elements[vid]; label = v.get('text') or ''; quote = source['quote']
        if v.get('type') not in {'text', 'input'}:
            raise ValueError('Binding outside eligible visual role')
        reason = None
        if not label or label not in quote or (e.get('text') or '') != label:
            reason = 'literal_label_not_anchored'
        elif sum((n.get('text') or '') == label for n in visual.values()) != 1:
            reason = 'ambiguous_literal_label'
        elif (v['type'], e.get('type')) not in {('text', 'text'), ('input', 'input')}:
            reason = 'source_architect_type_disagreement'
        if reason:
            unresolved.append(dict(source, vision_id=vid, reason=reason)); continue
        bound.append(dict(source, vision_id=vid))
        if v['type'] == 'text':
            # Several utterances may describe one object; keep all evidence in
            # bound, but the existing compiler accepts only one change per ID.
            if not any(p['vision_id'] == vid for p in proposals):
                proposals.append({'vision_id': vid, 'target_type': 'input', 'evidence_quote': quote})
        else:
            native.append(dict(source, vision_id=vid))
    if seen != set(slot_map):
        raise ValueError('Missing requirement bindings; omission is not unresolved')
    result = copy.deepcopy(state)
    result['semantic_input_overrides'] = proposals
    result.setdefault('page_meta', {})['input_requirement_binding'] = {
        'version': 'requirement_slots_v1', 'source_slots': slots,
        'eligible_count': len(slots), 'reviewed_count': len(seen), 'bound_count': len(bound),
        'bound': bound, 'already_native': native, 'type_change_proposals': len(proposals),
        'unresolved_count': len(unresolved), 'unresolved': unresolved,
        'limits': 'Coverage of explicit editable-pattern sentences only, not all spoken requirements; binding semantics need review.'}
    return result


@traced_stage('architect.input_requirement_binding')
def bind_input_requirements(state, vision, intent, model, client):
    slots, _ = input_requirement_slots(intent)
    if not slots:
        return compile_requirement_bindings(state, vision, intent, {'bindings': []})
    nodes = [{'vision_id': e['id'], 'type': e['type'], 'text': e.get('text') or ''}
             for e in vision['elements'] if e.get('type') in {'text', 'input'}]
    prompt = (Path(__file__).resolve().parents[1] / 'prompts/input_requirement_binding.md').read_text(encoding='utf-8')
    previous = getattr(client, 'stage', None)
    if previous is not None:
        client.stage = 'input_requirement_binder'
    try:
        response = client.chat.completions.create(model=model, temperature=0, max_tokens=8192,
            timeout=600, response_format={'type': 'json_object'}, messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps({'original_intent': intent,
                 'immutable_requirements': slots, 'immutable_nodes': nodes}, ensure_ascii=False)}])
    finally:
        if previous is not None:
            client.stage = previous
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Requirement binding truncated; no additional attempt')
    return compile_requirement_bindings(state, vision, intent,
        json.loads(response.choices[0].message.content))
