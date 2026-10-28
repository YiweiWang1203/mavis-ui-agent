"""Validate a source-bound semantic plan before explicit regional compilation."""
import copy
import json

from src.utils.coordinate_contract import _id
from src.utils.region_layout_contract import compile_region_structure
from src.utils.text_evidence_contract import source_spans


def parse_semantic_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate semantic JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def _rows(value, key):
    if not isinstance(value, list):
        raise ValueError('Missing semantic list: ' + key)
    result = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError('Invalid semantic record')
        rid = _id(row.get(key))
        if rid in result:
            raise ValueError('Duplicate semantic record: ' + rid)
        result[rid] = row
    return result


def _reason(row):
    if not isinstance(row.get('reason'), str) or not row['reason'].strip():
        raise ValueError('Explicit semantic disposition reason required')


def compile_semantic_plan(plan, vision, *, request, speech, frame, viewport):
    required = {'version', 'requirements', 'entities', 'source_dispositions',
                'observation_dispositions', 'region_plan'}
    if not isinstance(plan, dict) or set(plan) != required or plan['version'] != 'semantic-page-v1':
        raise ValueError('Incomplete or unknown SemanticPagePlan contract')
    text_sources = {'request': request, 'speech': speech}
    spans = source_spans(text_sources)
    sources = {s['ref']: s for s in spans}
    visual = _rows(vision['elements'], 'id')
    entities = _rows(plan['entities'], 'id')
    if not set(visual) <= set(entities):
        raise ValueError('Observed entities missing from semantic plan')
    if len(entities) > 512:
        raise ValueError('Semantic plan entity cap exceeded')
    all_refs = set(sources) | {'vision:' + vid for vid in visual}
    state = {'page_meta': {'viewport': {k: viewport[k] for k in ('width', 'height')}, 'locale': 'zh-CN'}, 'elements': []}
    for eid, entity in entities.items():
        if set(entity) != {'id', 'type', 'text', 'parent_id', 'rpa_action', 'evidence_refs'}:
            raise ValueError('Invalid entity fields')
        refs = entity['evidence_refs']
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in all_refs for r in refs):
            raise ValueError('Entity evidence missing or unknown')
        if not all(isinstance(entity[k], str) for k in ('type', 'text', 'rpa_action')):
            raise ValueError('Invalid entity semantics')
        if entity['parent_id'] is not None and entity['parent_id'] not in entities:
            raise ValueError('Unknown semantic parent')
        out = copy.deepcopy(entity)
        if eid in visual:
            v = visual[eid]
            if entity['type'] != v['type'] or entity['text'] != (v.get('text') or '') or 'vision:' + eid not in refs:
                raise ValueError('This trial freezes visual type/text/source identity')
            out.update(vision_id=eid, origin='vision')
        else:
            if not eid.startswith('u_') or not any(r in sources for r in refs):
                raise ValueError('Spoken-only entity requires explicit text source and u_ ID')
            if entity['type'] not in {'text', 'button', 'input', 'container', 'card', 'list', 'image', 'divider'}:
                raise ValueError('Unsupported spoken-only type')
            out.update(origin='spoken')
        state['elements'].append(out)
    requirements = _rows(plan['requirements'], 'id')
    requirement_records = []
    for row in requirements.values():
        if set(row) != {'id', 'source_id', 'intent', 'entity_ids', 'status', 'reason'}:
            raise ValueError('Invalid requirement fields')
        _reason(row)
        if row['source_id'] not in sources or not isinstance(row['intent'], str) or not row['intent'].strip():
            raise ValueError('Requirement source or intent invalid')
        ids = row['entity_ids']
        if not isinstance(ids, list) or any(not isinstance(eid, str) or eid not in entities for eid in ids) or len(set(ids)) != len(ids):
            raise ValueError('Requirement binding unknown or duplicated')
        if row['status'] not in {'accepted', 'unresolved', 'rejected'} or (row['status'] == 'accepted' and not ids):
            raise ValueError('Accepted requirement needs explicit binding')
        requirement_records.append({**copy.deepcopy(row), 'source': copy.deepcopy(sources[row['source_id']])})
    dispositions = _rows(plan['source_dispositions'], 'source_id')
    observations = _rows(plan['observation_dispositions'], 'vision_id')
    if set(dispositions) != set(sources) or set(observations) != set(visual):
        raise ValueError('Incomplete source/observation dispositions')
    for row in dispositions.values():
        _reason(row)
        if row.get('status') not in {'used', 'context', 'unresolved'}:
            raise ValueError('Invalid source disposition status')
    for row in observations.values():
        _reason(row)
        if row.get('status') not in {'accepted', 'unresolved'}:
            raise ValueError('Visual evidence cannot silently disappear')
    for row in requirement_records:
        if dispositions[row['source_id']]['status'] != 'used':
            raise ValueError('Requirement source must be declared used')
    result = compile_region_structure(state, vision, frame=frame, viewport=viewport,
                region_plan=plan['region_plan'], text_sources=text_sources, text_evidence=spans)
    unresolved = [r for r in requirement_records if r['status'] != 'accepted']
    unresolved_sources = [r for r in dispositions.values() if r['status'] == 'unresolved']
    unresolved_observations = [r for r in observations.values() if r['status'] == 'unresolved']
    meta = {'version': 'semantic-page-v1', 'requirements': requirement_records,
        'source_dispositions': copy.deepcopy(plan['source_dispositions']),
        'observation_dispositions': copy.deepcopy(plan['observation_dispositions']),
        'requirement_accepted': sum(r['status'] == 'accepted' for r in requirement_records),
        'requirement_proposed': len(requirement_records), 'source_span_count': len(spans),
        'unresolved_requirements': unresolved, 'unresolved_sources': unresolved_sources,
        'unresolved_observations': unresolved_observations, 'semantic_review_required': True,
        'all_user_intent_covered': None}
    meta['status'] = 'page_plan_incomplete' if (not plan['region_plan']['regions'] or unresolved or
        unresolved_sources or unresolved_observations or not requirement_records) else 'declared_plan_compiled_pending_semantic_review'
    result['page_meta']['semantic_plan'] = meta
    return result
