"""Opt-in stage evidence; observes values without repairing outputs."""
from collections import Counter
from contextvars import ContextVar
from functools import wraps
import hashlib
import inspect
import json
from pathlib import Path
import time
import dataclasses

_active = ContextVar('mavis_pipeline_trace', default=None)


def plain(value):
    if hasattr(value, 'model_dump'):
        return plain(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value,type):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): ('[redacted]' if str(k).lower() in {
            'api_key', 'authorization', 'access_token', 'secret_key'} else plain(v)) for k,v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, bytes):
        return {'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value,(str,int,float,bool)):
        return value
    return {'unserialized_type':type(value).__name__}


def state_summary(state):
    if not isinstance(state,dict) or not isinstance(state.get('elements'),list):
        return None
    elements=state['elements']
    ids=[str(e.get('id') or '') for e in elements if isinstance(e,dict)]
    counts=Counter(ids)
    meta=state.get('page_meta') if isinstance(state.get('page_meta'),dict) else {}
    viewport=meta.get('viewport') or state.get('canvas')
    viewport=viewport if isinstance(viewport,dict) else None
    invalid,outside=[],[]
    for i,e in enumerate(elements):
        if not isinstance(e,dict):
            invalid.append({'index':i,'reason':'not_object'}); continue
        spatial=e.get('spatial_info') if isinstance(e.get('spatial_info'),dict) else {}
        box=spatial.get('bbox')
        if box is None:  # normalized vision boxes have a different coordinate contract
            continue
        if not isinstance(box,list) or len(box)!=4 or not all(isinstance(x,(int,float)) for x in box) or box[0]>=box[2] or box[1]>=box[3]:
            invalid.append({'index':i,'id':e.get('id'),'reason':'invalid_pixel_bbox'}); continue
        if viewport and all(isinstance(viewport.get(k),(int,float)) for k in ('width','height')) and (box[0]<0 or box[1]<0 or box[2]>viewport['width'] or box[3]>viewport['height']):
            outside.append({'index':i,'id':e.get('id'),'bbox':box})
    return {'element_count':len(elements),'ids':ids,
            'duplicate_ids':{k:v for k,v in counts.items() if k and v>1},
            'missing_id_count':counts.get('',0),
            'types':dict(Counter(str(e.get('type')) for e in elements if isinstance(e,dict))),
            'viewport':viewport,'invalid_boxes':invalid,'out_of_bounds':outside}


def state_changes(before,after):
    a,b=state_summary(before),state_summary(after)
    if a is None or b is None:
        return None
    result={'before':a,'after':b,'count_delta':b['element_count']-a['element_count'],
            'added_ids':sorted(set(b['ids'])-set(a['ids'])),
            'removed_ids':sorted(set(a['ids'])-set(b['ids'])),
            'viewport_changed':a['viewport']!=b['viewport'],'changed_elements':[]}
    if a['duplicate_ids'] or b['duplicate_ids']:
        result['field_comparison']='ambiguous_duplicate_ids'
        return result
    left={str(e.get('id')):e for e in before['elements'] if isinstance(e,dict) and e.get('id')}
    right={str(e.get('id')):e for e in after['elements'] if isinstance(e,dict) and e.get('id')}
    for eid in sorted(left.keys() & right.keys()):
        fields={k:{'before':left[eid].get(k),'after':right[eid].get(k)}
                for k in sorted(left[eid].keys()|right[eid].keys()) if left[eid].get(k)!=right[eid].get(k)}
        if fields:
            result['changed_elements'].append({'id':eid,'fields':fields})
    return result


class PipelineTrace:
    def __init__(self,folder,metadata=None):
        self.folder=Path(folder)
        self.folder.mkdir(parents=True,exist_ok=False)
        self.events=[]
        self.manifest={'schema_version':'pipeline-trace-v1','metadata':plain(metadata or {}),
                       'status':'started','events':self.events,'reported_error_stages':[],
                       'limits':'Stage diagnostics, not requirement correctness or browser usability scores.'}
        self._save()

    def _save(self):
        (self.folder/'manifest.json').write_text(json.dumps(self.manifest,ensure_ascii=False,indent=2),encoding='utf-8')

    def __enter__(self):
        self.token=_active.set(self)
        return self

    def __exit__(self,kind,error,tb):
        _active.reset(self.token)
        self.manifest['status']='failed' if kind else ('completed_with_reported_errors' if self.manifest['reported_error_stages'] else 'completed')
        if kind:
            self.manifest['error_type']=kind.__name__
        self._save()

    def record(self,stage,**payload):
        value={'stage':stage,**plain(payload)}
        filename=f'{len(self.events)+1:03d}_{stage.replace(".","_")}.json'
        raw=json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
        (self.folder/filename).write_bytes(raw)
        event={'stage':stage,'file':filename,'sha256':hashlib.sha256(raw).hexdigest()}
        changes=value.get('changes')
        if changes:
            event['transition']={'before_count':changes['before']['element_count'],
                'after_count':changes['after']['element_count'],'added_ids':changes['added_ids'],
                'removed_ids':changes['removed_ids'],'changed_count':len(changes['changed_elements']),
                'out_of_bounds_count':len(changes['after']['out_of_bounds'])}
        self.events.append(event)
        if isinstance(payload.get('output'),dict) and payload['output'].get('error'):
            self.manifest['reported_error_stages'].append(stage)
        self._save()


def trace_event(stage,**payload):
    trace=_active.get()
    if trace is not None:
        trace.record(stage,**payload)


def html_contract_summary(code,state):
    """Static declared-type/DOM identity diagnostic; not browser validation."""
    from html.parser import HTMLParser
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__(); self.ids={}; self.native=[]
        def handle_starttag(self,tag,attrs):
            values=dict(attrs)
            if values.get('id'):
                self.ids.setdefault(values['id'],[]).append({'tag':tag,'type':values.get('type')})
            if tag in {'input','textarea','select'}:
                self.native.append({'tag':tag,'id':values.get('id'),'type':values.get('type')})
        handle_startendtag=handle_starttag
    parser=Tags(); parser.feed(code or '')
    types={'input','text_input','search_input','search_bar','textarea','password_input','email_input','number_input'}
    checks=[{'id':e.get('id'),'declared_type':e.get('type'),'dom_matches':parser.ids.get(str(e.get('id')),[])}
            for e in (state or {}).get('elements',[]) if isinstance(e,dict) and e.get('type') in types]
    return {'mode':'static_only_not_behavior_score','declared_inputs':checks,
            'native_controls':parser.native,'duplicate_dom_ids':{k:len(v) for k,v in parser.ids.items() if len(v)>1},
            'has_html_end_tag':'</html>' in (code or '').lower()}


def trace_html_contract(code,state,**metadata):
    if _active.get() is not None:
        trace_event('coder.html_contract',diagnostics=html_contract_summary(code,state),**metadata)


def traced_stage(stage,fields=None):
    """Capture named inputs before mutation and full output after return."""
    def decorate(function):
        signature=inspect.signature(function)
        @wraps(function)
        def wrapped(*args,**kwargs):
            trace=_active.get()
            if trace is None:
                return function(*args,**kwargs)
            bound=signature.bind(*args,**kwargs)
            bound.apply_defaults()
            inputs=plain({k:v for k,v in bound.arguments.items()
                          if k not in {'self','audit_logger'} and (fields is None or k in fields)})
            trace.record(stage+'.input',inputs=inputs)
            start=time.monotonic()
            try:
                output=function(*args,**kwargs)
            except Exception as exc:
                trace.record(stage+'.error',error_type=type(exc).__name__,elapsed_seconds=time.monotonic()-start)
                raise
            before=next((v for k,v in inputs.items() if k in {'ui_state','ui_state_json'}),None)
            after=plain(output)
            trace.record(stage+'.output',output=after,elapsed_seconds=time.monotonic()-start,
                         changes=state_changes(before,after),summary=state_summary(after))
            return output
        return wrapped
    return decorate
