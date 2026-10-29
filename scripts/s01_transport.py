"""Offline-testable S01 transport safeguards; no network on import."""
import base64, copy, hashlib, json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

def now(): return datetime.now(timezone.utc).isoformat()
def atomic_write(path, value):
    path=Path(path); tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,default=str);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def hashed(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def freeze_clock(messages, clock):
    messages=copy.deepcopy(messages)
    for m in messages:
        if m.get('role')=='system' and isinstance(m.get('content'),str):
            m['content']=re.sub(r'(?m)^CURRENT_TIME: [^\r\n]*',lambda _: 'CURRENT_TIME: '+clock,m['content'])
    return messages

def safe_error(exc):
    # Never serialize str(exc), headers, request, URL or arbitrary nested objects.
    out={'exception_type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)}
    body=getattr(exc,'body',None)
    if isinstance(body,dict):
        body=body.get('error',body)
        if isinstance(body,dict):
            for k in ('code','type','message'):
                v=body.get(k)
                if isinstance(v,(str,int)):
                    v=str(v)
                    # Drop whole field on credential/header/query markers, rather than risk partial redaction.
                    if re.search(r'(?i)https?://|bearer|authorization|headers?|api.?key|token|secret|sk-|[?&]\w+=',v):
                        v='[REDACTED_SENSITIVE_FIELD]'
                    out[k]=v[:300]
    return out

def counts(arms,expected=9):
    success=sum(a['status']=='html_generated_pending_browser' for a in arms)
    failed=sum(a['status']=='failed' for a in arms)
    skipped=sum(a['status'].startswith('NOT_EXECUTED') for a in arms)
    return dict(expected=expected,completed=success+failed,success=success,failed=failed,not_executed=skipped,unaccounted=expected-len(arms))
def terminal(arms,expected=9):
    c=counts(arms,expected)
    if c['unaccounted']: return 'interrupted_incomplete'
    if c['success']==expected:return 'completed_generation'
    if c['success']:return 'completed_with_failures'
    return 'completed_all_failed'

class Guard:
    def __init__(self,clock):self.clock=clock;self.frozen={};self.inputs={};self.blocked=None;self.contract_error=None
    def check(self,case,arm,stage,kwargs):
        kwargs=copy.deepcopy(kwargs);kwargs['messages']=freeze_clock(kwargs['messages'],self.clock)
        expected={'vision':(0.0,{'type':'json_object'}),'ui_architect':(0.3,{'type':'json_object'}),'coder':(0.2,None),'direct':(0.2,None),'probe_json':(0,{'type':'json_object'}),'probe_text':(0,None)}
        temp,fmt=expected[stage]
        params={k:v for k,v in kwargs.items() if k not in ('model','messages')}
        wanted={'temperature':temp,'max_tokens':1024 if stage.startswith('probe_') else 8192}
        if fmt is not None:wanted['response_format']=fmt
        if params!=wanted:raise ValueError('Frozen non-model request parameters differ')
        if arm in ('R','S'):
            signature={'system':[m for m in kwargs['messages'] if m['role']=='system'],'params':params}
            key=(case,stage)
            if key in self.frozen and signature!=self.frozen[key]:raise ValueError('Paired system prompt or parameters differ')
            self.frozen.setdefault(key,signature)
            if stage=='vision':
                key=(case,'vision_messages')
                if key in self.frozen and kwargs['messages']!=self.frozen[key]:raise ValueError('Paired vision evidence differs')
                self.frozen.setdefault(key,kwargs['messages'])
        return kwargs
    def bind_inputs(self,case,hashes):
        if case in self.inputs and hashes!=self.inputs[case]:raise ValueError('Paired input bytes differ')
        self.inputs.setdefault(case,hashes)

class Transport:
    def __init__(self,client,output,models,cap,guard,run,state,case,arm,safe_messages):
        self.client=client;self.output=output;self.models=models;self.cap=cap;self.guard=guard
        self.run=run;self.state=state;self.case=case;self.arm=arm;self.safe_messages=safe_messages
        self.calls=[];self.stage='unknown';self.chat=SimpleNamespace(completions=self)
    def progress(self,status):
        self.run.update(current_arm=self.case+'_'+self.arm,current_stage=self.stage,request_status=status,updated_at=now())
        atomic_write(self.state/'run.json',self.run)
    def create(self,**kwargs):
        if self.guard.blocked:raise RuntimeError('Service circuit open')
        if self.guard.contract_error:raise RuntimeError('Request contract circuit open')
        try:
            if len(self.calls)>=self.cap:raise ValueError('Unexpected extra request')
            if self.stage not in self.models:raise ValueError('Unapproved stage')
            kwargs.update(model=self.models[self.stage],max_tokens=1024 if self.stage.startswith('probe_') else 8192)
            kwargs=self.guard.check(self.case,self.arm,self.stage,kwargs)
            image_hashes=[]
            for m in kwargs['messages']:
                if isinstance(m.get('content'),list):
                    for part in m['content']:
                        if part.get('type')=='image_url':
                            url=part['image_url']['url']
                            image_hashes.append(hashlib.sha256(base64.b64decode(url.split(',',1)[1],validate=True)).hexdigest())
            if image_hashes and self.arm in ('R','S','D'):
                effective=self.output/'effective_image.jpg'
                if image_hashes!=[hashlib.sha256(effective.read_bytes()).hexdigest()]:raise ValueError('Effective image bytes differ')
                key=(self.case,'effective_image')
                if key in self.guard.frozen and image_hashes!=self.guard.frozen[key]:raise ValueError('Paired effective images differ')
                self.guard.frozen.setdefault(key,image_hashes)
        except Exception:
            self.guard.contract_error='pre_request_contract_failed';self.progress('contract_failed_before_request');raise
        record={'index':len(self.calls)+1,'case':self.case,'arm':self.arm,'stage':self.stage,'requested_model':kwargs['model'],
                'started_utc':now(),'status':'request_started','effective_image_sha256':image_hashes,
                'request':{**kwargs,'messages':self.safe_messages(kwargs['messages'])},
                'system_prompt_sha256':hashed([m for m in kwargs['messages'] if m['role']=='system'])}
        self.calls.append(record);path=self.output/('call_%02d.json'%record['index'])
        atomic_write(path,record);self.progress('request_started');start=time.monotonic()
        try:
            response=self.client.chat.completions.create(**kwargs)
            payload=response.model_dump();record.update(response=payload,status='returned',http_status=200,
                response_model=payload.get('model'),finish_reason=response.choices[0].finish_reason,usage=payload.get('usage'))
        except Exception as exc:
            record.update(status='failed',error=safe_error(exc),http_status=getattr(exc,'status_code',None))
            status=record['http_status']
            if status in (401,402,403,408,429) or (isinstance(status,int) and status>=500) or type(exc).__name__ in ('APIConnectionError','APITimeoutError'):
                self.guard.blocked={'http_status':status,'error_type':type(exc).__name__}
                self.run['service_block']=self.guard.blocked
            raise RuntimeError('Provider request failed; see safe record') from None
        finally:
            record.update(finished_utc=now(),elapsed_seconds=time.monotonic()-start)
            atomic_write(path,record);self.progress(record['status'])
        if record['finish_reason']!='stop' or not response.choices[0].message.content:raise ValueError('Invalid visible model completion')
        return response
