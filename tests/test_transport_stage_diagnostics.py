"""No network: prove stage meaning, redaction and bounded IPC supervision."""
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from src.utils import single_attempt_transport as t


SECRET = 'SYNTHETIC_SECRET_BODY_AUTH_URL_MUST_NOT_BE_LOGGED'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def stages(path):
    return [row['stage'] for row in rows(path)]


def test_http_hooks_log_only_header_metadata_and_never_read_body(tmp_path):
    path = tmp_path/'events.jsonl'
    hooks = t.http_event_hooks(t.StageRecorder(path))
    class Response:
        status_code = 429
        headers = {'x-request-id':'provider-123', 'authorization':SECRET, 'set-cookie':SECRET}
        @property
        def content(self):
            pytest.fail('hook must not read response body')
    hooks['request'][0](SimpleNamespace(url=SECRET,headers={'Authorization':SECRET},content=SECRET))
    hooks['response'][0](Response())
    assert stages(path) == ['http_request_hook','http_response_headers']
    assert rows(path)[1]['http_status'] == 429
    assert rows(path)[1]['provider_request_id'] == 'provider-123'
    assert SECRET not in path.read_text(encoding='utf-8')


def test_sdk_success_and_exception_keep_original_packet_no_extra_create(tmp_path,monkeypatch):
    calls = []
    def factory(observe):
        class Client:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def create(self,**request):
                calls.append(request)
                return SimpleNamespace(_request_id='provider-456',model_dump=lambda:{'choices':[{'text':SECRET}]})
            def __init__(self): self.chat=SimpleNamespace(completions=self)
        return Client()
    monkeypatch.setattr(t,'build_client',factory)
    sent=[]; path=tmp_path/'worker.jsonl'; req={'messages':SECRET}
    t.sdk_worker(SimpleNamespace(send=sent.append,close=lambda:None),req,diagnostics_path=path)
    assert calls==[req] and sent[0]['response']['choices'][0]['text']==SECRET
    assert stages(path)==['worker_started','client_create_started','client_create_complete',
        'sdk_call_started','sdk_call_returned','serialization_started','serialization_complete',
        'ipc_send_started','ipc_send_complete','worker_finished']
    assert SECRET not in path.read_text(encoding='utf-8')
    def fail(observe): raise RuntimeError(SECRET)
    monkeypatch.setattr(t,'build_client',fail)
    path=tmp_path/'exception.jsonl';sent.clear()
    t.sdk_worker(SimpleNamespace(send=sent.append,close=lambda:None),req,diagnostics_path=path)
    assert sent==[{'ok':False,'error_type':'RuntimeError','http_status':None}]
    assert 'worker_exception' in stages(path)
    assert SECRET not in path.read_text(encoding='utf-8')


def test_logging_failure_does_not_change_packet_or_raise(tmp_path):
    t.StageRecorder(tmp_path/'missing'/'events.jsonl')('worker_started')
    path=tmp_path/'events.jsonl';observe=t.StageRecorder(path)
    observe('http_response_headers',provider_request_id='Bearer SECRET\nAuthorization: x')
    assert 'provider_request_id' not in rows(path)[0]
    observe(SECRET)
    assert len(rows(path))==1


def test_default_dispatch_supplies_same_diagnostics_without_changing_requests(tmp_path,monkeypatch):
    calls=[]
    def dispatch(request,deadline,*,diagnostics_directory):
        calls.append((request,deadline,diagnostics_directory))
        t.StageRecorder(diagnostics_directory/'parent.jsonl')('supervisor_started')
        return {'ok':True,'response':{'choices':[{'finish_reason':'stop',
                'message':{'content':'SYNTHETIC'}}]}}
    monkeypatch.setattr(t,'isolated_sdk_call',dispatch)
    adapter=t.SingleAttemptTransport(tmp_path/'transport','fixture',dispatch=dispatch)
    req=dict(model=t.MODEL,max_tokens=8192,timeout=600,temperature=.3,
             messages=[{'role':'system','content':'fixture'},{'role':'user','content':SECRET}])
    for arm in ('control','candidate'):
        adapter(arm,'architect',req)
        terminal=json.loads((tmp_path/f'transport/{arm}_architect_terminal.json').read_text())
        assert terminal['stage_diagnostics']['schema']=='metadata_stages_v1'
        assert terminal['stage_diagnostics']['missing_events']=='UNKNOWN_NOT_PROOF_OF_ABSENCE'
    assert [c[:2] for c in calls]==[(req,600),(req,600)]
    assert calls[0][2].name=='control_architect_stages'
    assert calls[1][2].name=='candidate_architect_stages'


def successful_worker(connection,request,*,diagnostics_path):
    observe=t.StageRecorder(diagnostics_path);observe('worker_started')
    observe('sdk_call_started');observe('sdk_call_returned')
    observe('ipc_send_started');connection.send({'ok':True,'response':request})
    observe('ipc_send_complete');connection.close()


def stalled_request_worker(connection,request,*,diagnostics_path):
    observe=t.StageRecorder(diagnostics_path);observe('worker_started')
    observe('sdk_call_started');time.sleep(8)


def crashing_worker(connection,request,*,diagnostics_path):
    t.StageRecorder(diagnostics_path)('worker_started')
    raise RuntimeError(SECRET)


def decode_delay():
    time.sleep(8)
    return {'ok':True}


class DelayedDecode:
    def __reduce__(self): return decode_delay,()


def stalled_ipc_worker(connection,request,*,diagnostics_path):
    observe=t.StageRecorder(diagnostics_path);observe('worker_started')
    observe('sdk_call_returned');observe('serialization_complete');observe('ipc_send_started')
    connection.send(DelayedDecode());observe('ipc_send_complete');time.sleep(8)


def test_successful_receipt_has_distinct_worker_and_parent_evidence(tmp_path):
    value=t.isolated_sdk_call({'synthetic':SECRET},deadline=4,worker=successful_worker,
                              diagnostics_directory=tmp_path)
    assert value=={'ok':True,'response':{'synthetic':SECRET}}
    assert 'ipc_receive_complete' in stages(tmp_path/'parent.jsonl')
    assert 'hard_deadline_reached' not in stages(tmp_path/'parent.jsonl')
    assert SECRET not in ''.join(p.read_text(encoding='utf-8') for p in tmp_path.glob('*.jsonl'))


@pytest.mark.parametrize('worker,last_stage',[(stalled_request_worker,'sdk_call_started'),
                                              (stalled_ipc_worker,'ipc_send_complete')])
def test_hard_cutoff_does_not_claim_unobserved_http_phase(tmp_path,worker,last_stage):
    started=time.monotonic()
    with pytest.raises(TimeoutError,match='HARD_REQUEST_DEADLINE'):
        t.isolated_sdk_call({},deadline=1.8,worker=worker,diagnostics_directory=tmp_path)
    assert time.monotonic()-started<3.5
    assert last_stage in stages(tmp_path/'worker.jsonl')
    assert 'http_response_headers' not in stages(tmp_path/'worker.jsonl')
    parent=stages(tmp_path/'parent.jsonl')
    assert 'hard_deadline_reached' in parent and parent[-1]=='supervisor_finished'


def test_abrupt_worker_exit_reports_ipc_error_without_retry(tmp_path):
    with pytest.raises(EOFError):
        t.isolated_sdk_call({},deadline=4,worker=crashing_worker,diagnostics_directory=tmp_path)
    events=stages(tmp_path/'parent.jsonl')
    assert 'ipc_receive_error' in events and 'hard_deadline_reached' not in events
    assert events.count('worker_spawned')==1
