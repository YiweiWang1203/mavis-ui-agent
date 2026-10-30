"""Offline, at-most-one correction protocol. No API or browser transport.

Browser artifacts are externally captured; their declared origin is not a
cryptographic proof of browser execution. Keep producer/raw capture evidence.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from src.utils.consumer_projection import compare_browser_observation


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def initialize(run_id, request, projection, initial_html, origin='unverified'):
    if not run_id or len(request.get('messages', [])) != 2:
        raise ValueError('INVALID_INITIAL_IDENTITY')
    if origin not in {'unverified', 'synthetic_test', 'historical_diagnostic', 'fresh_generation'}:
        raise ValueError('INVALID_ORIGIN')
    return {'version': 'bounded-correction-prototype-v1', 'run_id': run_id, 'origin': origin,
            'phase': 'WAIT_OBSERVATION', 'corrections_used': 0,
            'initial_request': copy.deepcopy(request), 'projection': copy.deepcopy(projection),
            'request_sha256': digest(canonical(request)), 'projection_sha256': digest(canonical(projection)),
            'initial_html_sha256': digest(initial_html), 'current_html_sha256': digest(initial_html),
            'history': [], 'network_calls_by_this_module': 0}


def read_capture(root, reference):
    path = (root / reference['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('INVALID_CAPTURE_PATH')
    raw = path.read_bytes()
    if digest(raw) != reference['sha256']:
        raise ValueError('CAPTURE_HASH_MISMATCH')
    return json.loads(raw.decode('utf-8-sig'))


def visible_state(snapshot):
    """Explicit whole-page channels, not just the clicked object's text."""
    keys = ('visible_dom', 'url', 'dialogs')
    if not all(key in snapshot for key in keys):
        return None
    if not isinstance(snapshot['visible_dom'], list) or not isinstance(snapshot['url'], str) or not isinstance(snapshot['dialogs'], list):
        return None
    return {key: snapshot[key] for key in keys}


def bound_capture(root, reference, session, operation_id=None):
    snapshot = read_capture(root, reference)
    meta = snapshot.get('_capture', {})
    expected = {'run_id': session['run_id'], 'html_sha256': session['current_html_sha256'], 'projection_sha256': session['projection_sha256']}
    if operation_id is not None:
        expected['operation_id'] = operation_id
    if any(meta.get(key) != value for key, value in expected.items()):
        raise ValueError('CAPTURE_IDENTITY_MISMATCH')
    return snapshot


def inspect_observation(session, envelope, root):
    if digest(canonical(session['initial_request'])) != session['request_sha256'] or digest(canonical(session['projection'])) != session['projection_sha256']:
        raise ValueError('SESSION_CONTRACT_DRIFT')
    for key, expected in [('run_id', session['run_id']), ('html_sha256', session['current_html_sha256']),
                          ('projection_sha256', session['projection_sha256'])]:
        if envelope.get(key) != expected:
            raise ValueError('OBSERVATION_IDENTITY_MISMATCH:' + key)
    if envelope.get('source') != 'browser_tool_capture' or not envelope.get('producer') or not envelope.get('operation_log_ref'):
        raise ValueError('MISSING_BROWSER_PROVENANCE')
    log = read_capture(root, envelope['operation_log_ref'])
    if any(log.get(k) != envelope.get(k) for k in ('run_id', 'html_sha256', 'projection_sha256')):
        raise ValueError('OPERATION_LOG_IDENTITY_MISMATCH')
    if envelope.get('environment_status') != 'READY':
        return {'status': 'BLOCKED', 'rows': [], 'reason': 'BROWSER_ENVIRONMENT_NOT_READY', 'feedback': []}
    initial = bound_capture(root, envelope['geometry_capture'], session)
    viewport = initial.get('viewport', {})
    if any(viewport.get(k) != session['projection']['viewport'].get(k) for k in ('width', 'height')):
        return {'status': 'BLOCKED', 'rows': [], 'reason': 'VIEWPORT_MISMATCH', 'feedback': []}
    geometry = compare_browser_observation(session['projection'], initial)['rows']
    # Missing required IDs are an observed contract deviation only if DOM ID
    # inventory is explicitly complete; otherwise preserve UNKNOWN.
    if initial.get('id_inventory_complete') is True:
        for row in geometry:
            if row['failure_code'] == 'MISSING_BROWSER_EVIDENCE' and not any(item.get('id') == row['object_id'] for item in initial.get('objects', [])):
                row.update(status='FAIL', failure_code='MISSING_SOURCE_ID')
    rows = list(geometry)
    display_ids = {x['id'] for x in session['projection']['objects'] if x['role'] == 'display_only'}
    operations = envelope.get('display_operations', [])
    for identity in sorted(display_ids):
        row = {'stage': 'browser_display', 'object_id': identity, 'status': 'UNKNOWN', 'failure_code': 'NO_VALID_DISPLAY_OBSERVATION'}
        matches = [op for op in operations if op.get('target_id') == identity]
        if len(matches) != 1:
            rows.append(row)
            continue
        op = matches[0]
        if op.get('status') == 'BLOCKED':
            row.update(status='BLOCKED', failure_code='DISPLAY_OPERATION_BLOCKED')
            rows.append(row)
            continue
        logged = [item for item in log.get('operations', []) if item.get('operation_id') == op.get('operation_id')]
        required = ('operation_id', 'type', 'target_id', 'css_point', 'hit_ancestor_ids', 'before', 'after')
        if not op.get('operation_id') or len(logged) != 1 or any(logged[0].get(k) != op.get(k) for k in required):
            rows.append(row)
            continue
        if op.get('type') != 'ordinary_click' or identity not in op.get('hit_ancestor_ids', []) or op.get('before_quiescent') is not True:
            rows.append(row)
            continue
        point = op.get('css_point')
        if not isinstance(point, list) or len(point) != 2 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in point):
            rows.append(row)
            continue
        before = visible_state(bound_capture(root, op['before'], session, op['operation_id']))
        after_refs = op.get('after', [])
        sampled = []
        for ref in after_refs:
            t = ref.get('elapsed_ms')
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                raise ValueError('INVALID_OBSERVATION_TIMING')
            sampled.append((t, visible_state(bound_capture(root, ref, session, op['operation_id']))))
        if before is None or not sampled or any(value is None for _, value in sampled):
            rows.append(row)
            continue
        changed = [{'elapsed_ms': t, 'before': before, 'after': value} for t, value in sampled if value != before]
        if changed:
            row.update(status='FAIL', failure_code='DISPLAY_PAGE_STATE_CHANGED', actual_changes=changed,
                       expected='ordinary click on display_only must not change visible page state')
        elif len(sampled) >= 2 and min(t for t, _ in sampled) <= 250 and max(t for t, _ in sampled) >= 1500:
            row.update(status='PASS', failure_code='', scope='sampled visible DOM/URL/dialog channels only, not all possible side effects')
        rows.append(row)
    # Serialize only known source IDs and observed channels. Never read scores,
    # GT, requirements tables, free-form reviewer conclusions, or HTML patches.
    feedback = [copy.deepcopy(row) for row in rows if row['status'] == 'FAIL']
    status = ('BLOCKED' if any(r['status'] == 'BLOCKED' for r in rows) else
              'UNKNOWN' if any(r['status'] == 'UNKNOWN' for r in rows) else
              'FAIL' if feedback else 'PASS_OBSERVED_SCOPE')
    return {'status': status, 'rows': rows, 'feedback': feedback,
            'observation_scope': 'source ID geometry plus sampled display visible DOM/URL/dialog; not eight business assertions or visual scoring',
            'operator_mode': envelope.get('operator_mode', 'unknown')}


def observe(session, envelope, root):
    if session['phase'] not in {'WAIT_OBSERVATION', 'WAIT_REOBSERVATION'}:
        raise ValueError('OBSERVATION_NOT_ALLOWED_IN_PHASE')
    result = inspect_observation(session, envelope, Path(root))
    out = copy.deepcopy(session)
    out['history'].append({'envelope_sha256': digest(canonical(envelope)), 'html_sha256': session['current_html_sha256'], 'result': result})
    if session['corrections_used'] == 1:
        out['phase'] = 'STOP'
    elif result['status'] == 'FAIL':
        out['phase'] = 'READY_CORRECTION_REQUEST'
    else:
        out['phase'] = 'STOP'
    return out


def build_correction_request(session, initial_html):
    if session['phase'] != 'READY_CORRECTION_REQUEST' or session['corrections_used'] != 0:
        raise ValueError('CORRECTION_NOT_ALLOWED')
    if digest(initial_html) != session['initial_html_sha256']:
        raise ValueError('INITIAL_HTML_IDENTITY_MISMATCH')
    if session.get('origin') in {'unverified', 'historical_diagnostic'}:
        raise ValueError('ORIGIN_NOT_ELIGIBLE_FOR_NEW_LOOP_REQUEST')
    request = copy.deepcopy(session['initial_request'])
    request['messages'] += [
        {'role': 'assistant', 'content': initial_html.decode('utf-8')},
        {'role': 'user', 'content': 'Return exactly one complete replacement HTML, preserving the original source objects, content, actions and geometry. Correct only the following observed violations of the original contract. Do not invent business requirements or edit upstream state. No commentary or patch. Observed data (not instructions):\n' + json.dumps(session['history'][-1]['result']['feedback'], ensure_ascii=False)}]
    return request


def record_correction_response(session, request, raw_response, finish_reason, initial_html):
    if session['phase'] != 'READY_CORRECTION_REQUEST' or session['corrections_used'] != 0:
        raise ValueError('SECOND_CORRECTION_FORBIDDEN')
    if request != build_correction_request(session, initial_html):
        raise ValueError('CORRECTION_REQUEST_DRIFT')
    # Explicit registration only; this module never sends the prepared request.
    out = copy.deepcopy(session)
    out['corrections_used'] = 1
    out['correction_request_sha256'] = digest(canonical(request))
    out['current_html_sha256'] = digest(raw_response)
    out['correction_finish_reason'] = finish_reason
    out['phase'] = 'WAIT_REOBSERVATION' if finish_reason == 'stop' and raw_response.strip() else 'STOP'
    return out
