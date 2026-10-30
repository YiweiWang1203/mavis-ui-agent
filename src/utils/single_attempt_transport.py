"""Opt-in SDK adapter. Importing this module never constructs a network client."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace

BASE_URL = 'https://api.siliconflow.cn/v1'
MODEL = 'Qwen/Qwen3-VL-32B-Instruct'
TIMEOUT = 600


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def client_configuration():
    return {'base_url':BASE_URL, 'max_retries':0, 'timeout':TIMEOUT,
            'http_transport_retries':0, 'follow_redirects':False, 'trust_env':False}


def build_client():
    # Lazy imports: the offline CLI and import-time checks need neither package.
    import httpx
    from openai import OpenAI
    key = os.environ.get('SILICONFLOW_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not key:
        raise ValueError('MISSING_EXISTING_CREDENTIAL')
    http = httpx.Client(transport=httpx.HTTPTransport(retries=0),
                        timeout=TIMEOUT, follow_redirects=False, trust_env=False)
    try:
        client = OpenAI(api_key=key, base_url=BASE_URL, max_retries=0,
                        timeout=TIMEOUT, http_client=http)
        if client.max_retries != 0:
            raise ValueError('SDK_RETRY_CONFIGURATION_MISMATCH')
        return client
    except BaseException:
        http.close()
        raise


def sdk_worker(connection, request):
    """One SDK create only. Exception messages/credentials never cross the pipe."""
    try:
        with build_client() as client:
            response = client.chat.completions.create(**request)
            connection.send({'ok':True, 'response':response.model_dump(),
                             'provider_request_id':getattr(response, '_request_id', None)})
    except BaseException as exc:
        connection.send({'ok':False, 'error_type':type(exc).__name__,
                         'http_status':getattr(exc, 'status_code', None)})
    finally:
        connection.close()


def isolated_sdk_call(request, deadline=TIMEOUT, worker=sdk_worker, *, receive_packet=None):
    """Supervise complete receipt/decoding, never block the supervisor on recv.

    The daemon receiver owns the read handle and may not publish late results.
    A stalled receiver is never joined without a bound. Killing the sole writer
    releases normal partial reads; a pathological decoder may outlive this call
    in its daemon thread, but cannot delay the caller or dispatch another API.
    """
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(send, request))
    started = time.monotonic()
    cutoff = started + deadline
    complete = threading.Event()
    received = {}
    receiver = None
    def collect():
        try:
            received['packet'] = receive.recv() if receive_packet is None else receive_packet(receive)
        except BaseException as exc:
            received['error'] = exc
        finally:
            receive.close()
            complete.set()
    try:
        process.start()
        send.close()
        receiver = threading.Thread(target=collect, daemon=True,
                                    name='single-attempt-complete-receiver')
        receiver.start()
        if not complete.wait(max(0, cutoff - time.monotonic())) or time.monotonic() >= cutoff:
            raise TimeoutError('HARD_REQUEST_DEADLINE')
        if 'error' in received:
            raise received['error']
        return received['packet']
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        if receiver is None:
            receive.close()
        else:
            # Never make timeout cleanup depend on completing a partial message
            # or an unresponsive decoder. The receiver closes its own handle.
            receiver.join(timeout=.05)
        send.close()


class SingleAttemptTransport:
    """Caller must obtain separate authorization; no automatic runner dispatch.

    Each of the four fixed slots is claimed on disk BEFORE process creation.
    A timeout, crash, truncation or parse failure consumes its slot permanently.
    Reusing an output directory is refused. No resume, fallback or retry API.
    """
    def __init__(self, directory, run_id, *, dispatch=isolated_sdk_call):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
            raise ValueError('INVALID_RUN_ID')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.run_id = run_id
        self.dispatch = dispatch
        self.lock = threading.Lock()
        write_new(self.directory/'configuration.json', {
            'run_id':run_id, 'model':MODEL, 'client':client_configuration(),
            'max_slots':4, 'outer_retries':0, 'hard_deadline_seconds':TIMEOUT,
            'proxy_policy':'explicit direct connection; no environment proxy inheritance',
            'authorization':'must be obtained by caller; construction is not authorization'})

    def __call__(self, arm, node, request):
        if not self.lock.acquire(blocking=False):
            raise ValueError('CONCURRENT_DISPATCH_FORBIDDEN')
        try:
            return self._call(arm, node, request)
        finally:
            self.lock.release()

    def _call(self, arm, node, request):
        if arm not in {'control','candidate'} or node not in {'architect','coder'}:
            raise ValueError('INVALID_REQUEST_SLOT')
        expected = {'model':MODEL, 'max_tokens':8192, 'timeout':TIMEOUT,
                    'temperature':.3 if node=='architect' else .2}
        if any(request.get(k)!=v for k,v in expected.items()):
            raise ValueError('TRANSPORT_POLICY_MISMATCH')
        allowed = set(expected)|{'messages','response_format'}
        if set(request)-allowed:
            raise ValueError('UNAPPROVED_REQUEST_OVERRIDE')
        messages=request.get('messages')
        if not isinstance(messages,list) or [m.get('role') for m in messages]!=['system','user'] or any(not isinstance(m.get('content'),str) for m in messages):
            raise ValueError('TEXT_ONLY_TWO_MESSAGE_CONTRACT')
        slot = arm+'_'+node
        request_id = self.run_id+'_'+slot
        serialized = json.dumps(request,ensure_ascii=False,sort_keys=True).encode('utf-8')
        claim = {'request_id':request_id,'arm':arm,'node':node,
                 'request_sha256':hashlib.sha256(serialized).hexdigest(),
                 'budget_slot_consumed':True,'dispatch_attempts':1,
                 'physical_server_receipt':'UNKNOWN_UNTIL_RESPONSE'}
        write_new(self.directory/(slot+'_claim.json'), claim)
        write_new(self.directory/(slot+'_request.json'), request)
        started=time.monotonic()
        terminal={'request_id':request_id,'provider_request_id':None,'usage':None,
                  'currency_cost':None,'missing_cost_is_not_zero':True}
        try:
            packet=self.dispatch(request,deadline=TIMEOUT)
            terminal['http_status']=packet.get('http_status')
            if not packet.get('ok'):
                terminal['sdk_error_type']=packet.get('error_type')
                raise RuntimeError('SDK_REQUEST_FAILED:'+str(packet.get('error_type')))
            data=packet['response']
            terminal.update(provider_request_id=packet.get('provider_request_id'),
                            provider_response_id=data.get('id'),usage=data.get('usage'))
            write_new(self.directory/(slot+'_response.json'),packet)
            choices=data.get('choices',[])
            if len(choices)!=1 or choices[0].get('finish_reason')!='stop':
                raise ValueError('NON_STOP_OR_INVALID_CHOICES')
            text=choices[0].get('message',{}).get('content')
            if not isinstance(text,str) or not text.strip():
                raise ValueError('EMPTY_MODEL_CONTENT')
            terminal['status']='STOP_RETURNED_NOT_ACCEPTED'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text),finish_reason='stop')],usage=data.get('usage'))
        except BaseException as exc:
            terminal.update(status='FAILED_SLOT_CONSUMED_NO_RETRY',error_type=type(exc).__name__)
            raise
        finally:
            terminal['elapsed_seconds']=time.monotonic()-started
            write_new(self.directory/(slot+'_terminal.json'),terminal)
