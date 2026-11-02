import json
import sys
import time
from types import SimpleNamespace
import pytest
from src.utils import single_attempt_transport as t


def request(node='architect'):
    return dict(model=t.MODEL,max_tokens=8192,timeout=600,
                temperature=.3 if node=='architect' else .2,
                messages=[{'role':'system','content':'synthetic system'},
                          {'role':'user','content':'synthetic input'}])


def packet(reason='stop',content='SYNTHETIC',ok=True):
    return {'ok':ok,'provider_request_id':'synthetic-provider-id',
            'response':{'id':'synthetic-response-id','usage':{'total_tokens':1},
                        'choices':[{'finish_reason':reason,'message':{'content':content}}]}}


def test_actual_factory_arguments_are_identical_for_both_arms(monkeypatch):
    calls=[]
    class HTTP:
        def __init__(self,**kwargs):calls.append(('http',kwargs))
        def close(self):pass
    def transport(**kwargs):calls.append(('http_transport',kwargs));return 'SYNTHETIC_TRANSPORT'
    def sdk(**kwargs):calls.append(('sdk',kwargs));return SimpleNamespace(max_retries=kwargs['max_retries'])
    monkeypatch.setitem(sys.modules,'httpx',SimpleNamespace(Client=HTTP,HTTPTransport=transport))
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(OpenAI=sdk))
    monkeypatch.setenv('SILICONFLOW_API_KEY','SYNTHETIC_NOT_REAL')
    for arm in ['control','candidate']:t.build_client()
    assert calls[:3][0:2]==calls[3:6][0:2]
    for kind,kwargs in calls:
        if kind=='http_transport':assert kwargs=={'retries':0}
        elif kind=='http':assert kwargs['timeout']==600 and not kwargs['follow_redirects'] and not kwargs['trust_env']
        else:assert kwargs['base_url']==t.BASE_URL and kwargs['max_retries']==0 and kwargs['timeout']==600


@pytest.mark.parametrize('reason,content,fail',[('stop','SYNTHETIC',False),('length','cut',True),('stop','',True),('content_filter','',True)])
def test_terminal_consumes_slot_and_forbids_reuse(tmp_path,reason,content,fail):
    calls=[]
    def dispatch(req,deadline):calls.append(req);assert deadline==600;return packet(reason,content)
    adapter=t.SingleAttemptTransport(tmp_path/'transport','synthetic',dispatch=dispatch)
    if fail:
        with pytest.raises(ValueError):adapter('control','architect',request())
    else:assert adapter('control','architect',request()).choices[0].message.content=='SYNTHETIC'
    with pytest.raises(FileExistsError):adapter('control','architect',request())
    assert len(calls)==1
    terminal=json.loads((tmp_path/'transport/control_architect_terminal.json').read_text())
    assert terminal['status']==('FAILED_SLOT_CONSUMED_NO_RETRY' if fail else 'STOP_RETURNED_NOT_ACCEPTED')
    assert terminal['provider_request_id']=='synthetic-provider-id'


@pytest.mark.parametrize('failure',['timeout','sdk_error'])
def test_transport_failure_never_retries(tmp_path,failure):
    calls=[]
    def dispatch(req,deadline):
        calls.append(req)
        if failure=='timeout':raise TimeoutError('synthetic')
        return {'ok':False,'error_type':'SyntheticHTTP429','http_status':429}
    adapter=t.SingleAttemptTransport(tmp_path/'transport','synthetic',dispatch=dispatch)
    with pytest.raises((TimeoutError,RuntimeError)):adapter('candidate','coder',request('coder'))
    with pytest.raises(FileExistsError):adapter('candidate','coder',request('coder'))
    assert len(calls)==1


def test_four_slots_only_and_no_output_directory_resume(tmp_path):
    calls=[]
    def dispatch(req,deadline):calls.append(req);return packet()
    adapter=t.SingleAttemptTransport(tmp_path/'transport','synthetic',dispatch=dispatch)
    for arm in ('control','candidate'):
        for node in ('architect','coder'):adapter(arm,node,request(node))
    with pytest.raises(ValueError):adapter('third_arm','coder',request('coder'))
    with pytest.raises(FileExistsError):t.SingleAttemptTransport(tmp_path/'transport','synthetic',dispatch=dispatch)
    assert len(calls)==4 and len(list((tmp_path/'transport').glob('*_claim.json')))==4


@pytest.mark.parametrize('change',[{'model':'different'},{'max_tokens':9000},{'timeout':601},{'temperature':.7},{'max_retries':2},{'stream':True}])
def test_policy_mismatch_rejected_before_dispatch(tmp_path,change):
    def no_dispatch(*args,**kwargs):pytest.fail('unexpected transport call')
    adapter=t.SingleAttemptTransport(tmp_path/'transport','synthetic',dispatch=no_dispatch)
    req=request();req.update(change)
    with pytest.raises(ValueError):adapter('control','architect',req)
    assert not list((tmp_path/'transport').glob('*_claim.json'))


def sleepy_worker(connection,request):
    time.sleep(10)


def test_hard_deadline_terminates_subprocess_without_respawn():
    start=time.monotonic()
    with pytest.raises(TimeoutError):t.isolated_sdk_call({},deadline=.2,worker=sleepy_worker)
    assert time.monotonic()-start<5


def test_sdk_worker_calls_create_exactly_once_and_closes(monkeypatch):
    calls=[];sent=[]
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):calls.append('closed')
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: calls.append('create') or SimpleNamespace(model_dump=lambda:packet()['response'],_request_id='synthetic')))
    monkeypatch.setattr(t,'build_client',lambda:Client())
    pipe=SimpleNamespace(send=sent.append,close=lambda:calls.append('pipe_closed'))
    t.sdk_worker(pipe,request())
    assert calls==['create','closed','pipe_closed'] and sent[0]['ok']


def test_sdk_worker_error_not_retried_and_no_secret_message(monkeypatch):
    calls=[];sent=[]
    def fail():calls.append('construct');raise RuntimeError('SYNTHETIC_SECRET_MUST_NOT_BE_LOGGED')
    monkeypatch.setattr(t,'build_client',fail)
    t.sdk_worker(SimpleNamespace(send=sent.append,close=lambda:None),request())
    assert calls==['construct'] and not sent[0]['ok']
    assert 'SECRET' not in json.dumps(sent)


def test_adapter_connected_to_real_pair_entry_without_network(tmp_path):
    import importlib.util
    from pathlib import Path
    from test_region_tree_contract import sample
    s,v=sample();calls=[]
    path=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py'
    spec=importlib.util.spec_from_file_location('adapter_pair_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def dispatch(req,deadline):
        calls.append(req)
        node='architect' if len(calls) in (1,3) else 'coder'
        return packet(content=json.dumps(s) if node=='architect' else '<html><body>SYNTHETIC OFFLINE FIXTURE</body></html>')
    adapter=t.SingleAttemptTransport(tmp_path/'transport','synthetic_pair',dispatch=dispatch)
    result=module.run_pair(v,'',t.MODEL,tmp_path/'pair',adapter,transport_identity='ADAPTER_WITH_SYNTHETIC_DISPATCH_NO_NETWORK')
    assert len(calls)==4 and all(r['status']=='PIPELINE_RETURNED_NOT_ACCEPTED' for r in result['results'])
    assert len(list((tmp_path/'transport').glob('*_claim.json')))==4
    assert not list(tmp_path.rglob('*.html'))


def partial_packet_worker(connection,request):
    connection.send_bytes(b'SYNTHETIC_FIRST_CHUNK')
    time.sleep(4)
    connection.send({'ok':True})


def delayed_packet_worker(connection,request):
    time.sleep(4)
    connection.send({'ok':True})


def slow_decode(flag):
    from pathlib import Path
    Path(flag).write_text('decoder entered',encoding='utf-8')
    time.sleep(4)
    return {'ok':True}


class SlowDecodedPacket:
    def __init__(self,flag):self.flag=flag
    def __reduce__(self):return slow_decode,(self.flag,)


def slow_decode_worker(connection,request):
    connection.send(SlowDecodedPacket(request['flag']))
    time.sleep(4)


@pytest.mark.parametrize('phase',['partial','late_complete','decode'])
def test_complete_receipt_deadline_covers_stalled_transfer_and_decode(tmp_path,phase):
    import multiprocessing
    flag=tmp_path/'phase_entered.txt'
    before={p.pid for p in multiprocessing.active_children()}
    def receive_chunks(connection):
        assert connection.recv_bytes()==b'SYNTHETIC_FIRST_CHUNK'
        flag.write_text('first chunk consumed; awaiting rest',encoding='utf-8')
        return connection.recv()
    worker={'partial':partial_packet_worker,'late_complete':delayed_packet_worker,'decode':slow_decode_worker}[phase]
    started=time.monotonic()
    with pytest.raises(TimeoutError,match='HARD_REQUEST_DEADLINE'):
        t.isolated_sdk_call({'flag':str(flag)},deadline=1.2,worker=worker,
                            receive_packet=receive_chunks if phase=='partial' else None)
    assert time.monotonic()-started<2.5 # stalled operation takes 4s without supervision
    assert {p.pid for p in multiprocessing.active_children()}<=before
    if phase in {'partial','decode'}:assert flag.exists() # proves the blocked stage was reached
