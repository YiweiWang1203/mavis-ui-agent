"""A bounded, relation-only evidence stage; never edit source nodes or HTML."""
import copy
import json
from pathlib import Path
from src.utils.pipeline_trace import traced_stage


@traced_stage('architect.relation_specialist')
def refine_relation_state(state, user_intent, model, client, mode='source_ledger_v1'):
    if mode not in {'source_ledger_v1', 'container_slots_v1', 'container_slots_guard_v1'}:
        raise ValueError('Unsupported relation specialist mode')
    prompt_file = 'relation_container_slots.md' if mode in {'container_slots_v1', 'container_slots_guard_v1'} else 'relation_specialist.md'
    prompt = (Path(__file__).resolve().parents[1] / 'prompts' / prompt_file).read_text(encoding='utf-8')
    # Do not bias extraction with the planner's proposed parents or evaluator labels.
    nodes = [{'id': e['id'], 'vision_id': e.get('vision_id'), 'type': e.get('type'),
              'text': e.get('text') or ''} for e in state['elements']]
    payload = {'user_intent': user_intent, 'immutable_nodes': nodes}
    if mode in {'container_slots_v1', 'container_slots_guard_v1'}:
        from src.utils.relation_evidence import DESCRIPTORS, CONTAINER_ALIASES
        slots = {e['id']: e for e in nodes if CONTAINER_ALIASES.get(e['type'], e['type']) in DESCRIPTORS}
        payload['container_slots'] = slots
        if mode == 'container_slots_guard_v1' and not slots:
            # No legal parent role exists. Keep source evidence; do not ask the
            # model to invent roles or silently coerce ordinary controls.
            result = copy.deepcopy(state)
            result['relation_evidence_sources'] = [
                {'source': 'architect', 'relationships': copy.deepcopy(state.get('relationships'))},
                {'source': 'specialist', 'relationships': []}]
            result['relationships'] = copy.deepcopy(state.get('relationships', []))
            result.setdefault('page_meta', {})['relation_specialist'] = {
                'version': mode, 'additional_calls': 0, 'node_edits_allowed': False,
                'status': 'skipped_no_eligible_container', 'eligible_container_count': 0,
                'source_validation': 'pending',
                'semantic_review': 'required; missing containers remain unresolved upstream'}
            return result
    previous = getattr(client, 'stage', None)
    if previous is not None:
        client.stage = 'relation_specialist'
    try:
        response = client.chat.completions.create(model=model, temperature=0,
            max_tokens=8192, timeout=600, response_format={'type': 'json_object'},
            messages=[{'role': 'system', 'content': prompt},
                      {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}])
    finally:
        if previous is not None:
            client.stage = previous
    if getattr(response.choices[0], 'finish_reason', None) == 'length':
        raise ValueError('Specialist output truncated; no additional attempt')
    declarations = json.loads(response.choices[0].message.content)
    if mode in {'container_slots_v1', 'container_slots_guard_v1'}:
        relationships = compile_container_slots(declarations, slots)
    else:
        if not isinstance(declarations, dict) or set(declarations) != {'relationships'} or not isinstance(declarations['relationships'], list):
            raise ValueError('Specialist may only output a relationship ledger')
        relationships = declarations['relationships']
    result = copy.deepcopy(state)
    result['relation_evidence_sources'] = [
        {'source': 'architect', 'relationships': copy.deepcopy(state.get('relationships'))},
        {'source': 'specialist', 'relationships': copy.deepcopy(relationships)}]
    result['relationships'] = relationships
    result.setdefault('page_meta', {})['relation_specialist'] = {
        'version': mode, 'additional_calls': 1,
        'node_edits_allowed': False, 'source_validation': 'pending',
        'semantic_review': 'required; model extraction is not ground truth'}
    return result


def compile_container_slots(declarations, slots):
    """Parent roles are owned by existing typed slots, never invented or coerced."""
    if not isinstance(declarations, dict) or set(declarations) != {'children_by_container'}:
        raise ValueError('Specialist must return only container slots')
    groups = declarations['children_by_container']
    if not isinstance(groups, dict) or set(groups) != set(slots):
        raise ValueError('Missing or undeclared container slot')
    edges = []
    for parent, children in groups.items():
        if not isinstance(children, list):
            raise ValueError('Container children must be a list')
        for child in children:
            if not isinstance(child, dict) or set(child) != {'child_id', 'evidence_quote'}:
                raise ValueError('Child declaration may not choose or edit parent')
            edges.append({'parent_id': parent, **child})
    return edges
