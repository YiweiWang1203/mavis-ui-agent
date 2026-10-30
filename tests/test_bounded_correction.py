import copy
import json
import pytest
from src.utils.bounded_correction import initialize, digest, canonical, observe, build_correction_request, record_correction_response


def fixture(tmp_path, changed=True):
    projection = {'viewport': {'width': 300, 'height': 200}, 'objects': [{'id': 'message', 'role': 'display_only', 'left': 0, 'top': 0, 'width': 100, 'height': 40}]}
    request = {'model': 'frozen', 'messages': [{'role': 'system', 'content': 'original'}, {'role': 'user', 'content': 'original state'}], 'max_tokens': 8192, 'temperature': .2}
    session = initialize('synthetic-test-only', request, projection, b'<html>initial</html>', 'synthetic_test')
    def save(name, value):
        if name!='operations.json':
            value=copy.deepcopy(value)
            value['_capture']={'run_id':session['run_id'],'html_sha256':session['current_html_sha256'],'projection_sha256':session['projection_sha256']}
            if name!='geometry.json':value['_capture']['operation_id']='click-1'
        raw = json.dumps(value).encode(); (tmp_path/name).write_bytes(raw)
        return {'path': name, 'sha256': digest(raw)}
    before = {'visible_dom': [{'text': 'same message'}], 'url': 'http://local/', 'dialogs': []}
    after = copy.deepcopy(before)
    if changed: after['visible_dom'].append({'text': 'new popup'})
    env = {'run_id': session['run_id'], 'html_sha256': session['current_html_sha256'], 'projection_sha256': session['projection_sha256'], 'source': 'browser_tool_capture', 'producer': 'synthetic fixture, not real browser', 'operator_mode': 'synthetic_test', 'environment_status': 'READY',
           'operation_log_ref': save('operations.json', {'synthetic': True, 'run_id': session['run_id'], 'html_sha256': session['current_html_sha256'], 'projection_sha256': session['projection_sha256']}), 'geometry_capture': save('geometry.json', {'viewport': projection['viewport'], 'objects': [{'id': 'message', 'box': [0, 0, 100, 40]}]}),
           'display_operations': [{'operation_id':'click-1', 'target_id': 'message', 'type': 'ordinary_click', 'before_quiescent': True, 'css_point': [50,20], 'hit_ancestor_ids': ['child', 'message'], 'before': save('before.json', before), 'after': [dict(save('after.json', after), elapsed_ms=100), dict(save('afterlate.json', after), elapsed_ms=1500)]}]}
    log=json.loads((tmp_path/'operations.json').read_bytes());log['operations']=copy.deepcopy(env['display_operations']);env['operation_log_ref']=save('operations.json',log)
    return session, env


def test_whole_page_popup_detected_when_message_unchanged(tmp_path):
    s,e=fixture(tmp_path); out=observe(s,e,tmp_path)
    assert out['phase']=='READY_CORRECTION_REQUEST'
    assert out['history'][-1]['result']['feedback'][0]['failure_code']=='DISPLAY_PAGE_STATE_CHANGED'
    request=build_correction_request(out,b'<html>initial</html>')
    assert len(request['messages'])==4 and request['messages'][:2]==s['initial_request']['messages']
    assert s['phase']=='WAIT_OBSERVATION'


def test_no_change_scoped_pass_no_correction(tmp_path):
    s,e=fixture(tmp_path,False);out=observe(s,e,tmp_path)
    assert out['phase']=='STOP' and out['history'][-1]['result']['status']=='PASS_OBSERVED_SCOPE'
    with pytest.raises(ValueError):build_correction_request(out,b'<html>initial</html>')


@pytest.mark.parametrize('key',['run_id','html_sha256','projection_sha256'])
def test_wrong_identity_rejected(tmp_path,key):
    s,e=fixture(tmp_path);e[key]='wrong'
    with pytest.raises(ValueError):observe(s,e,tmp_path)


def test_blocked_environment_not_model_failure(tmp_path):
    s,e=fixture(tmp_path);e['environment_status']='ALERT_BLOCKED';out=observe(s,e,tmp_path)
    assert out['phase']=='STOP' and out['history'][-1]['result']['status']=='BLOCKED'


def test_missing_wholepage_and_missing_click_unknown(tmp_path):
    s,e=fixture(tmp_path);e['display_operations']=[];out=observe(s,e,tmp_path)
    assert out['phase']=='STOP' and out['history'][-1]['result']['status']=='UNKNOWN'


def test_hash_tamper_rejected(tmp_path):
    s,e=fixture(tmp_path);(tmp_path/'after.json').write_text('{}')
    with pytest.raises(ValueError):observe(s,e,tmp_path)


def test_second_correction_forbidden_and_failed_recheck_stops(tmp_path):
    s,e=fixture(tmp_path);ready=observe(s,e,tmp_path);request=build_correction_request(ready,b'<html>initial</html>')
    revised=record_correction_response(ready,request,b'<html>replacement</html>','stop',b'<html>initial</html>')
    e['html_sha256']=revised['current_html_sha256']
    log=json.loads((tmp_path/'operations.json').read_bytes());log['html_sha256']=e['html_sha256'];raw=json.dumps(log).encode();(tmp_path/'operations.json').write_bytes(raw);e['operation_log_ref']['sha256']=digest(raw)
    with pytest.raises(ValueError,match='CAPTURE_IDENTITY_MISMATCH'):observe(revised,e,tmp_path)
    refs=[e['geometry_capture']]+[e['display_operations'][0]['before']]+e['display_operations'][0]['after']
    for ref in refs:
        value=json.loads((tmp_path/ref['path']).read_bytes());value['_capture']['html_sha256']=e['html_sha256'];raw=json.dumps(value).encode();(tmp_path/ref['path']).write_bytes(raw);ref['sha256']=digest(raw)
    log['operations']=copy.deepcopy(e['display_operations']);raw=json.dumps(log).encode();(tmp_path/'operations.json').write_bytes(raw);e['operation_log_ref']['sha256']=digest(raw)
    final=observe(revised,e,tmp_path)
    assert final['phase']=='STOP' and final['corrections_used']==1
    with pytest.raises(ValueError):build_correction_request(final,b'<html>initial</html>')
    with pytest.raises(ValueError):record_correction_response(revised,request,b'again','stop',b'<html>initial</html>')


@pytest.mark.parametrize('reason',['length','timeout','error'])
def test_unsuccessful_response_terminal_no_retry(tmp_path,reason):
    s,e=fixture(tmp_path);ready=observe(s,e,tmp_path);request=build_correction_request(ready,b'<html>initial</html>')
    out=record_correction_response(ready,request,b'partial',reason,b'<html>initial</html>')
    assert out['phase']=='STOP' and out['corrections_used']==1


def test_gt_freeform_fields_not_serialized(tmp_path):
    s,e=fixture(tmp_path);e['reviewer_scores']='SECRET_GT';e['display_operations'][0]['desired_patch']='SECRET_PATCH'
    ready=observe(s,e,tmp_path);req=build_correction_request(ready,b'<html>initial</html>')
    assert 'SECRET' not in json.dumps(req)


def test_historical_replay_cannot_prepare_new_loop_request(tmp_path):
    s,e=fixture(tmp_path);s['origin']='historical_diagnostic';ready=observe(s,e,tmp_path)
    with pytest.raises(ValueError,match='ORIGIN_NOT_ELIGIBLE'):build_correction_request(ready,b'<html>initial</html>')


def test_logged_click_mismatch_does_not_trigger(tmp_path):
    s,e=fixture(tmp_path);e['display_operations'][0]['hit_ancestor_ids']=['other']
    out=observe(s,e,tmp_path)
    assert out['phase']=='STOP' and out['history'][-1]['result']['status']=='UNKNOWN'


def test_contract_tamper_rejected(tmp_path):
    s,e=fixture(tmp_path);s['projection']['objects'][0]['width']=20
    with pytest.raises(ValueError,match='SESSION_CONTRACT_DRIFT'):observe(s,e,tmp_path)


def test_present_id_missing_box_stays_unknown(tmp_path):
    s,e=fixture(tmp_path);ref=e['geometry_capture'];value=json.loads((tmp_path/ref['path']).read_bytes());value['id_inventory_complete']=True;value['objects'][0]['box']=None
    raw=json.dumps(value).encode();(tmp_path/ref['path']).write_bytes(raw);ref['sha256']=digest(raw)
    out=observe(s,e,tmp_path)
    assert out['phase']=='STOP' and out['history'][-1]['result']['rows'][0]['status']=='UNKNOWN'


def test_stale_click_capture_identity_rejected(tmp_path):
    s,e=fixture(tmp_path);ref=e['display_operations'][0]['before'];value=json.loads((tmp_path/ref['path']).read_bytes());value['_capture']['html_sha256']='stale'
    raw=json.dumps(value).encode();(tmp_path/ref['path']).write_bytes(raw);ref['sha256']=digest(raw)
    log=json.loads((tmp_path/'operations.json').read_bytes());log['operations']=copy.deepcopy(e['display_operations']);raw=json.dumps(log).encode();(tmp_path/'operations.json').write_bytes(raw);e['operation_log_ref']['sha256']=digest(raw)
    with pytest.raises(ValueError,match='CAPTURE_IDENTITY_MISMATCH'):observe(s,e,tmp_path)
