"""Shared paired runner. CLI is offline only; injected transport is caller-owned.
No model SDK/network transport is constructed here. HTML export is opt-in only.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.agents import ui_architect,coder
from src.utils.pipeline_trace import PipelineTrace


def write(path,value):
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def export_coder_html(folder, rendered_code):
    """Export production fence extraction verbatim; never repair invalid output."""
    response_path=folder/'coder_response.json'
    response=json.loads(response_path.read_text(encoding='utf-8'))
    raw=response.get('content')
    if response.get('finish_reason')!='stop' or not isinstance(raw,str) or not raw.strip():
        raise ValueError('HTML_EXPORT_REQUIRES_NONEMPTY_STOP')
    from src.utils.html_output_wrapper import parse_html_output
    parsed_output=parse_html_output(raw,finish_reason=response.get('finish_reason'))
    code=parsed_output['code']
    if not code or code!=rendered_code:
        raise ValueError('HTML_EXTRACTION_MISMATCH_OR_EMPTY')
    class DocumentCheck(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False);self.tags=[]
        def handle_starttag(self,tag,attrs):
            if tag in {'html','body'}:self.tags.append(('start',tag))
        def handle_endtag(self,tag):
            if tag in {'html','body'}:self.tags.append(('end',tag))
    parser=DocumentCheck()
    try:parser.feed(code);parser.close()
    except Exception as exc:raise ValueError('HTML_PARSE_FAILED') from exc
    # A deliberately minimal completeness gate, not HTML validity/business QA.
    if parser.tags!=[('start','html'),('start','body'),('end','body'),('end','html')] or not code.rstrip().lower().endswith('</html>'):
        raise ValueError('INCOMPLETE_HTML_DOCUMENT')
    data=code.encode('utf-8');path=folder/'original_coder.html'
    with path.open('xb') as stream:stream.write(data)
    record={'raw_response_file':str(response_path),'raw_response_sha256':hashlib.sha256(response_path.read_bytes()).hexdigest(),
            'raw_content_utf8_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'html_file':str(path),'html_sha256':hashlib.sha256(data).hexdigest(),
            'extraction':'shared parse_html_output; exact original substring and rendered_code equality',
            'output_wrapper':parsed_output['record'],
            'completeness_gate':'one html/body start/end in document order and closing html suffix; not full HTML validity',
            'mutations':'NONE within selected original substring',
            'browser_acceptance':'NOT_EXECUTED'}
    write(folder/'html_export.json',record)
    return record


def run_pair(vision,intent,model,out,transport,*,transport_identity,export_original_html=False,comparison='legacy_vs_region'):
    """transport(arm,node,request) returns SDK-shaped response. Never retries.
    Failure stops that arm; the other frozen arm is still accounted separately.
    Caller must authorize any external transport separately. CLI uses synthetic only.
    """
    if comparison not in {'legacy_vs_region','region_relation_v1'}:raise ValueError('INVALID_COMPARISON')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    payload={'vision':vision,'intent':intent}
    write(out/'shared_input.json',payload)
    digest=hashlib.sha256((out/'shared_input.json').read_bytes()).hexdigest()
    shared=dict(UI_PAIRED_RUN_POLICY='frozen_v1',UI_PAIRED_MODEL=model,
        UI_NEUTRAL_VISUAL_MODE='neutral_v1',UI_STRUCTURE_MODE='baseline',UI_RENDERER_MODE='llm',
        UI_RELATION_SPECIALIST_MODE='off',UI_INPUT_SEMANTIC_AUDIT_MODE='off',UI_SEMANTIC_TYPE_MODE='off',
        UI_COORDINATE_RESPONSIBILITY_MODE='off',UI_RELATION_AGGREGATION_MODE='off',
        UI_FUSION_MODE='exact_id',UI_CODER_CONTRACT_MODE='baseline',UI_INPUT_CONTRACT_MODE='off',UI_REGION_RELATION_MODE='off',
        CODER_PROD_MODEL=model,CODER_MODEL=model)
    requests={};results=[]
    for arm in ('control','candidate'):
        folder=out/arm;folder.mkdir();requests[arm]={};terminal=[]
        def create(**kwargs):
            node='architect' if not requests[arm] else 'coder'
            if node in requests[arm]:raise ValueError('REQUEST_ALREADY_DISPATCHED')
            expected=dict(model=model,max_tokens=8192,timeout=600,temperature=.3 if node=='architect' else .2)
            if any(kwargs.get(k)!=v for k,v in expected.items()):raise ValueError('REQUEST_POLICY_MISMATCH')
            requests[arm][node]=copy.deepcopy(kwargs);write(folder/(node+'_request.json'),kwargs)
            # No fallback/retry even if transport raises or returns truncation.
            started=time.monotonic()
            try:
                response=transport(arm,node,kwargs)
                choice=response.choices[0];reason=getattr(choice,'finish_reason',None)
                text=choice.message.content
                usage=getattr(response,'usage',None)
                usage=usage.model_dump() if hasattr(usage,'model_dump') else usage if isinstance(usage,dict) else None
                write(folder/(node+'_response.json'),{'content':text,'finish_reason':reason,'usage':usage,'elapsed_seconds':time.monotonic()-started,'cost_currency':None,'missing_cost_is_not_zero':True})
                if reason!='stop' or not isinstance(text,str) or not text.strip():
                    raise ValueError('INVALID_TERMINAL:'+str(reason))
                terminal.append({'node':node,'status':'STOP_RETURNED'})
                return response
            except Exception as exc:
                terminal.append({'node':node,'status':'REQUEST_FAILED','exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-started})
                raise
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        environment=dict(shared,UI_REGION_TREE_MODE='off' if arm=='control' and comparison=='legacy_vs_region' else 'region_tree_v1')
        if comparison=='region_relation_v1' and arm=='candidate':environment['UI_REGION_RELATION_MODE']='relation_first_v1'
        with patch.dict(os.environ,environment),patch.object(ui_architect,'_get_openai_client',return_value=client),patch.object(coder,'_get_openai_client',return_value=client),patch.object(coder,'save_html_asset',return_value=None),PipelineTrace(folder/'trace',metadata={'arm':arm,'transport_identity':transport_identity}):
            state=None
            try:
                state=ui_architect.generate_ui_state(intent,copy.deepcopy(vision))
                write(folder/'ui_state.json',state)
                if not isinstance(state,dict) or state.get('error') or not state.get('elements'):raise ValueError('ARCHITECT_CONTRACT_FAILED')
                rendered=coder.generate_frontend_code(state)
                if not isinstance(rendered,dict) or not rendered.get('code'):raise ValueError('CODER_CONTRACT_FAILED')
                if export_original_html:export_coder_html(folder,rendered['code'])
                result={'arm':arm,'status':'PIPELINE_RETURNED_NOT_ACCEPTED','requests_dispatched':len(requests[arm])}
            except Exception as exc:
                result={'arm':arm,'status':'FAILED_NO_RETRY','exception_type':type(exc).__name__,
                        'reason':str(exc),'requests_dispatched':len(requests[arm])}
                if isinstance(state,dict) and state.get('error'):
                    result.update(original_error=state['error'],error_node=state.get('error_node','architect'),
                                  error_details=copy.deepcopy(state.get('error_details',[])))
        result['coder_dispatched']='coder' in requests[arm]
        result['html_exists']=(folder/'original_coder.html').is_file()
        result['terminal_events']=terminal;write(folder/'terminal.json',result);results.append(result)
    differences={}
    for node in ('architect','coder'):
        a=requests['control'].get(node);b=requests['candidate'].get(node)
        differences[node]={'available_both':a is not None and b is not None,
            'changed_top_level_fields':sorted(k for k in set(a or {})|set(b or {}) if (a or {}).get(k)!=(b or {}).get(k)),
            'shared_policy_equal': bool(a and b) and all(a.get(k)==b.get(k) for k in ('model','temperature','max_tokens','timeout')),
            'messages':{role:{'equal':bool(a and b) and a['messages'][i]==b['messages'][i]} for i,role in enumerate(('system','user'))}}
    write(out/'request_diff.json',differences)
    summary={'comparison':comparison,'transport':transport_identity,'input_sha256':digest,'model':model,'max_tokens':8192,'timeout_seconds':600,'max_retries':0,'max_requests':4,'results':results,'browser':'NOT_EXECUTED','effect':'NOT_EVALUATED','new_html_files':len(list(out.glob('*/original_coder.html'))),'html_export_enabled':export_original_html}
    write(out/'summary.json',summary);return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vision',type=Path,required=True);p.add_argument('--intent',type=Path,required=True);p.add_argument('--control-response',type=Path,required=True);p.add_argument('--candidate-response',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    answers={arm:json.loads(path.read_text(encoding='utf-8-sig')) for arm,path in [('control',args.control_response),('candidate',args.candidate_response)]}
    def synthetic(arm,node,request):
        value=json.dumps(answers[arm]) if node=='architect' else 'SYNTHETIC_NOT_A_PAGE'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value),finish_reason='stop')])
    run_pair(json.loads(args.vision.read_text(encoding='utf-8-sig')),args.intent.read_text(encoding='utf-8-sig'),args.model,args.out,synthetic,transport_identity='OFFLINE_SYNTHETIC_ZERO_NETWORK_ZERO_MODEL_REQUESTS')

if __name__=='__main__':main()
