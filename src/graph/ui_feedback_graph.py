"""Bounded LangGraph UI target-layout feedback subgraph.

This is an explicit UI-only graph: observation and the first architect response
may be shared by a comparison runner.  It never invokes coordinator, planner,
semantic reviewer, or an API-level retry.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.utils.architect_target_layout import compile_architect_target_layout
from src.utils.coordinate_contract import audit_architect_coordinate_responsibility
from src.utils.pipeline_trace import trace_event
from src.utils.pipeline_trace import state_changes


class UIFeedbackState(TypedDict, total=False):
    user_intent: str
    vision_elements: dict
    trusted_coordinate_context: dict
    allow_repair: bool
    attempts: list[dict]
    feedback_history: list[dict]
    quality_history: list[dict]
    route_history: list[dict]
    pending_feedback: dict | None
    ui_state_json: dict | None
    final_code: str | None
    browser_audit: dict | None
    downstream_validity: dict
    downstream_history: list[dict]
    release_gate: dict
    model_call_count: int
    model_call_limit: int


REPAIRABLE_CODES = {
    'invalid_target_bbox': 'spatial_info.bbox',
    'missing_placement': 'spatial_info.bbox',
    'missing_or_wrong_coordinate_space': 'spatial_info.coordinate_space',
    'missing_or_wrong_viewport_id': 'spatial_info.viewport_id',
    'missing_derivation': 'spatial_info.derivation',
    'missing_derivation_sources': 'spatial_info.derivation.evidence_refs',
    'unknown_derivation_sources': 'spatial_info.derivation.evidence_refs',
    'missing_derivation_reason': 'spatial_info.derivation.reason',
}
IMMUTABLE_ELEMENT_FIELDS = ('id', 'vision_id', 'origin', 'type', 'text', 'parent_id', 'rpa_action')


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _immutable_differences(first: dict, repaired: dict) -> list[dict]:
    differences = []
    first_elements = {item.get('id'): item for item in first.get('elements', []) if isinstance(item, dict)}
    repaired_elements = {item.get('id'): item for item in repaired.get('elements', []) if isinstance(item, dict)}
    if set(first_elements) != set(repaired_elements):
        differences.append({'field': 'elements.inventory', 'before': sorted(first_elements),
                            'after': sorted(repaired_elements)})
        return differences
    for eid in sorted(first_elements):
        before, after = first_elements[eid], repaired_elements[eid]
        for field in IMMUTABLE_ELEMENT_FIELDS:
            if before.get(field) != after.get(field):
                differences.append({'object_id': eid, 'field': field,
                                    'before': copy.deepcopy(before.get(field)),
                                    'after': copy.deepcopy(after.get(field))})
    first_view = first.get('page_meta', {}).get('viewport')
    repaired_view = repaired.get('page_meta', {}).get('viewport')
    if first_view != repaired_view:
        differences.append({'field': 'page_meta.viewport', 'before': copy.deepcopy(first_view),
                            'after': copy.deepcopy(repaired_view)})
    return differences


def _spatial_leaves(value: Any, prefix='spatial_info') -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    result = {}
    for key, item in value.items():
        path = prefix + '.' + key
        if isinstance(item, dict):
            result.update(_spatial_leaves(item, path))
        else:
            result[path] = item
    return result


def _unauthorized_spatial_differences(first: dict, repaired: dict,
                                      allowed: set[tuple[str | None, str]]) -> list[dict]:
    differences = []
    left = {item.get('id'): item for item in first.get('elements', []) if isinstance(item, dict)}
    right = {item.get('id'): item for item in repaired.get('elements', []) if isinstance(item, dict)}
    for eid in sorted(set(left) & set(right)):
        before = _spatial_leaves(left[eid].get('spatial_info', {}))
        after = _spatial_leaves(right[eid].get('spatial_info', {}))
        for field in sorted(set(before) | set(after)):
            if before.get(field) == after.get(field):
                continue
            permitted = any(owner == eid and (
                field == authorized or field.startswith(authorized + '.'))
                for owner, authorized in allowed)
            if not permitted:
                differences.append({'object_id': eid, 'field': field,
                                    'before': copy.deepcopy(before.get(field)),
                                    'after': copy.deepcopy(after.get(field))})
    return differences


def _feedback_from_diagnostic(diagnostic: dict, attempt: dict) -> dict:
    records, unknown = [], []
    for element in diagnostic.get('elements', []):
        for issue in element.get('issues', []):
            code = issue.get('code')
            field = REPAIRABLE_CODES.get(code)
            raw_value = element.get('raw_bbox')
            if code in {'missing_or_wrong_coordinate_space', 'missing_or_wrong_viewport_id'}:
                raw_value = issue.get('actual')
            elif code in {'missing_derivation_sources', 'unknown_derivation_sources'}:
                raw_value = copy.deepcopy(issue.get('references'))
            elif code in {'missing_derivation', 'missing_derivation_reason'}:
                raw_value = None
            record = {
                'failed_node': 'ui_architect',
                'detected_by': 'coordinate_quality_gate',
                'object_id': element.get('id'),
                'field': field,
                'raw_value': copy.deepcopy(raw_value),
                'constraint': code,
                'evidence_ref': copy.deepcopy(element.get('vision_id')),
                'allowed_change': [field] if field else [],
                'repair_target': 'complete target-layout JSON for the same object inventory',
                'acceptance': 'all target placements pass the strict coordinate contract and immutable fields remain unchanged',
            }
            records.append(record)
            if field is None:
                unknown.append(record)
    for issue in diagnostic.get('global_issues', []):
        record = {
            'failed_node': 'ui_architect', 'detected_by': 'coordinate_quality_gate',
            'object_id': None, 'field': None,
            'raw_value': copy.deepcopy(issue), 'constraint': issue.get('code'),
            'evidence_ref': None, 'allowed_change': [], 'repair_target': None,
            'acceptance': 'requires caller or inventory correction; architect repair is not authorized',
        }
        records.append(record); unknown.append(record)
    original_state = copy.deepcopy(attempt.get('parsed'))
    original_raw = attempt.get('raw_response')
    allowed_changes = [
        {'object_id': object_id, 'field': field}
        for object_id, field in sorted({
            (record['object_id'], field) for record in records
            for field in record.get('allowed_change', []) if field
        }, key=lambda item: (str(item[0]), item[1]))]
    return {'version': 'architect-coordinate-feedback-v1',
            'source_attempt_id': attempt.get('attempt_id'), 'failures': records,
            'unknown_failure_count': len(unknown),
            'allowed_changes': allowed_changes,
            'supported_fields_not_authorized': sorted(set(REPAIRABLE_CODES.values())),
            'preserve_fields': list(IMMUTABLE_ELEMENT_FIELDS),
            'original_state': original_state,
            'original_state_sha256': _sha(original_state),
            'original_raw_response': original_raw,
            'original_raw_response_sha256': hashlib.sha256(
                (original_raw or '').encode('utf-8')).hexdigest()}


def build_ui_feedback_graph(architect_call: Callable[..., dict], renderer: Callable[[dict], str],
                            *, allow_repair: bool):
    """Compile a real bounded UI subgraph with at most one architect correction."""

    def ui_architect(state: UIFeedbackState):
        attempts = copy.deepcopy(state.get('attempts', []))
        pending = state.get('pending_feedback')
        if attempts and pending is None:
            return {'route_history': state.get('route_history', []) + [
                {'node': 'ui_architect', 'action': 'reuse_shared_first_attempt'}]}
        if len(attempts) >= 2:
            raise RuntimeError('Architect correction limit exceeded')
        if state.get('model_call_count', 0) >= state.get('model_call_limit', 1):
            raise RuntimeError('Architect model call budget exceeded')
        attempt_id = f'architect-{len(attempts)}'
        try:
            attempt = architect_call(
                user_intent=state['user_intent'], vision_elements=state['vision_elements'],
                trusted_coordinate_context=state['trusted_coordinate_context'],
                correction_feedback=copy.deepcopy(pending), attempt_id=attempt_id)
        except Exception as exc:
            attempt = {'attempt_id': attempt_id, 'status': 'provider_error', 'parsed': None,
                       'raw_response': None, 'error_type': type(exc).__name__,
                       'correction_feedback': copy.deepcopy(pending)}
        attempts.append(copy.deepcopy(attempt))
        trace_event('ui_feedback.architect_attempt', attempt=attempt)
        return {'attempts': attempts, 'pending_feedback': None,
                'model_call_count': state.get('model_call_count', 0) + 1,
                'route_history': state.get('route_history', []) + [
                    {'node': 'ui_architect', 'action': 'initial' if len(attempts) == 1 else 'repair',
                     'attempt_id': attempt_id}]}

    def quality_gate(state: UIFeedbackState):
        attempt = state['attempts'][-1]
        parsed = attempt.get('parsed')
        if attempt.get('status') != 'parsed' or not isinstance(parsed, dict):
            quality = {'status': 'rejected', 'known_repairable': False,
                       'attempt_id': attempt.get('attempt_id'),
                       'error': {'code': attempt.get('status') or 'missing_attempt'}}
            return {'quality_history': state.get('quality_history', []) + [quality],
                    'route_history': state.get('route_history', []) + [
                        {'node': 'quality_gate', 'action': 'reject_unparsed'}]}
        raw = copy.deepcopy(parsed)
        provenance = copy.deepcopy(state['trusted_coordinate_context'])
        diagnostic = audit_architect_coordinate_responsibility(raw, state['vision_elements'], provenance)
        immutable = []
        if len(state['attempts']) > 1:
            first = state['attempts'][0].get('parsed')
            if isinstance(first, dict):
                immutable = _immutable_differences(first, raw)
                allowed = {(failure.get('object_id'), field)
                           for failure in state.get('feedback_history', [])[0].get('failures', [])
                           for field in failure.get('allowed_change', []) if field}
                immutable += _unauthorized_spatial_differences(first, raw, allowed)
                preserve_denominator = len(first.get('elements', [])) * len(IMMUTABLE_ELEMENT_FIELDS) + 1
                immutable_changed = len([item for item in immutable
                                         if item.get('field') in IMMUTABLE_ELEMENT_FIELDS
                                         or item.get('field') in {'elements.inventory', 'page_meta.viewport'}])
                preserved_count = max(0, preserve_denominator - immutable_changed)
            else:
                preserve_denominator = preserved_count = 0
        else:
            preserve_denominator = preserved_count = 0
        feedback = _feedback_from_diagnostic(diagnostic, attempt)
        known = diagnostic['status'] != 'valid' and feedback['unknown_failure_count'] == 0
        quality = {'status': diagnostic['status'], 'known_repairable': known,
                   'attempt_id': attempt.get('attempt_id'), 'diagnostic': diagnostic,
                   'immutable_differences': immutable, 'input_sha256': _sha(raw),
                   'preserved_immutable_field_count': preserved_count,
                   'immutable_field_denominator': preserve_denominator,
                   'attempt_changes_from_first': state_changes(
                       state['attempts'][0].get('parsed'), raw) if len(state['attempts']) > 1 else None,
                   'validation_scope': 'numeric_and_source_contract_only',
                   'semantic_correctness_evaluated': False}
        if immutable:
            quality.update(status='rejected', known_repairable=False,
                           regression={'code': 'unauthorized_repair_change', 'changes': immutable})
        if quality['status'] == 'valid':
            try:
                compiled = compile_architect_target_layout(
                    raw, state['vision_elements'],
                    frame=provenance['observation_frame'], viewport=provenance['target_viewport'])
                quality['compiled_sha256'] = _sha(compiled)
            except Exception as exc:
                compiled = None
                quality.update(status='rejected', known_repairable=False,
                               compile_error={'type': type(exc).__name__})
        else:
            compiled = None
        trace_event('ui_feedback.quality_gate', quality=quality, feedback=feedback)
        updates = {'quality_history': state.get('quality_history', []) + [quality],
                   'route_history': state.get('route_history', []) + [
                       {'node': 'quality_gate', 'action': quality['status'],
                        'attempt_id': attempt.get('attempt_id')}],
                   'ui_state_json': compiled}
        if quality['status'] != 'valid':
            updates['feedback_history'] = state.get('feedback_history', []) + [feedback]
        return updates

    def supervisor(state: UIFeedbackState) -> Command[str]:
        quality = state['quality_history'][-1]
        if quality['status'] == 'valid':
            return Command(goto='render', update={
                'release_gate': {'status': 'coordinate_contract_passed',
                                 'scope': 'numeric_and_source_contract_only',
                                 'semantic_correctness_evaluated': False,
                                 'attempt_id': quality['attempt_id']},
                'route_history': state.get('route_history', []) + [
                    {'node': 'supervisor', 'action': 'release_to_render'}]})
        can_repair = (allow_repair and quality.get('known_repairable') is True
                      and len(state.get('attempts', [])) == 1
                      and state.get('model_call_count', 0) < state.get('model_call_limit', 1))
        if can_repair:
            feedback = state['feedback_history'][-1]
            return Command(goto='ui_architect', update={
                'pending_feedback': copy.deepcopy(feedback),
                'ui_state_json': None, 'final_code': None, 'browser_audit': None,
                'downstream_validity': {'status': 'invalidated_by_upstream_change',
                                        'source_attempt_id': quality['attempt_id']},
                'downstream_history': state.get('downstream_history', []) + [{
                    'status': 'invalidated_by_upstream_change',
                    'source_attempt_id': quality['attempt_id'],
                    'cleared_fields': ['ui_state_json', 'final_code', 'browser_audit']}],
                'release_gate': {'status': 'repair_requested', 'attempt_id': quality['attempt_id']},
                'route_history': state.get('route_history', []) + [
                    {'node': 'supervisor', 'action': 'return_to_ui_architect_once'}]})
        return Command(goto=END, update={
            'ui_state_json': None, 'final_code': None,
            'release_gate': {'status': 'blocked', 'attempt_id': quality.get('attempt_id'),
                             'reason': 'repair_disabled_or_exhausted_or_unknown'},
            'route_history': state.get('route_history', []) + [
                {'node': 'supervisor', 'action': 'stop'}]})

    def render(state: UIFeedbackState):
        code = renderer(state['ui_state_json'])
        trace_event('ui_feedback.render', ui_state_sha256=_sha(state['ui_state_json']),
                    html_sha256=hashlib.sha256(code.encode('utf-8')).hexdigest())
        return {'final_code': code,
                'downstream_validity': {'status': 'active',
                                        'source_attempt_id': state['attempts'][-1]['attempt_id']},
                'downstream_history': state.get('downstream_history', []) + [{
                    'status': 'active', 'source_attempt_id': state['attempts'][-1]['attempt_id']}],
                'route_history': state.get('route_history', []) + [
                    {'node': 'render', 'action': 'render_validated_state'}]}

    builder = StateGraph(UIFeedbackState)
    builder.add_node('ui_architect', ui_architect)
    builder.add_node('coordinate_quality_gate', quality_gate)
    builder.add_node('supervisor', supervisor)
    builder.add_node('render', render)
    builder.add_edge(START, 'ui_architect')
    builder.add_edge('ui_architect', 'coordinate_quality_gate')
    builder.add_edge('coordinate_quality_gate', 'supervisor')
    builder.add_edge('render', END)
    return builder.compile()
