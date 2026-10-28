"""Two fresh upstream calls; candidate adds one source-backed relative layout plan."""
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_pilot_experiment import load_inputs,execute,write_json,sha256
from scripts.run_generation_comparison import BudgetClient,source_record
from scripts.run_input_audit_comparison import CappedProvider
from src.agents.global_spatial_planner import parse_spatial_response
from src.utils.relative_region_layout import compile_relative_layout
from src.renderers.controlled_components import render_controlled_components


def main():
    import cv2
    import numpy as np
    from dotenv import load_dotenv
    from openai import OpenAI
    from urllib.parse import urlsplit
    p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--output-root',type=Path,required=True);a=p.parse_args()
    inputs=load_inputs(a.case.resolve(),'M2')
    batch=a.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]);batch.mkdir(parents=True)
    for source in inputs['files'].values():shutil.copyfile(source,batch/source.name)
    shared=batch/'shared_upstream';shared.mkdir()
    baseline=batch/'baseline_absolute';baseline.mkdir();candidate=batch/'candidate_relative';candidate.mkdir()
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env',override=True)
    endpoint=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL');key=os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY');url=urlsplit(endpoint or '')
    if not key or url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credentials and credential-free HTTPS endpoint required')
    model='Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(SILICONFLOW_BASE_URL=endpoint,VISION_MODEL=model,CODER_MODEL=model,CODER_PROD_MODEL=model,
        UI_STRUCTURE_MODE='hierarchy_v1',UI_FUSION_MODE='source_alignment_v1',UI_CODER_CONTRACT_MODE='controlled_components_v1',
        UI_RENDERER_MODE='controlled_components_v1',UI_RELATION_SPECIALIST_MODE='off',UI_RELATION_AGGREGATION_MODE='off',
        UI_SEMANTIC_TYPE_MODE='off',UI_INPUT_SEMANTIC_AUDIT_MODE='off',UI_INPUT_CONTRACT_MODE='off',UI_HIERARCHY_LAYOUT_MODE='baseline',LAYOUT_SOLVER_ENABLED='1')
    provider=CappedProvider(OpenAI(api_key=key,base_url=endpoint,max_retries=0,timeout=600),limit=3)
    upstream=BudgetClient(provider,shared);planner=BudgetClient(provider,candidate)
    manifest={**source_record(),'status':'started','model':model,'input_sha256':{k:sha256(v) for k,v in inputs['files'].items()},
        'call_accounting':{'physical_cap':3,'shared_upstream_cap':2,'baseline_effective':2,'candidate_effective':3},
        'max_tokens_per_stage':8192,'timeout_seconds':600,'max_retries':0,
        'runtime':{'python':sys.executable,'version':sys.version,'cv2':cv2.__file__,'numpy':np.__file__},
        'html_expected':True,'output_html_repair':False,'baseline_status':'not_generated','candidate_status':'not_generated'}
    write_json(batch/'batch.json',manifest);print('Batch:',batch,flush=True)
    try:
        code=execute(inputs,'M2',upstream,shared,model)
        if len(upstream.calls)!=2:raise ValueError('Exactly two shared upstream calls required; no budget expansion')
        if not isinstance(code,str) or '<html' not in code.lower() or '</html' not in code.lower():raise ValueError('Shared baseline generation failed')
        state=json.loads((shared/'ui_state.json').read_text(encoding='utf-8'))
        if not state.get('elements'):raise ValueError('Shared source objects missing')
        write_json(shared/'immutable_state.json',state);manifest['shared_state_sha256']=sha256(shared/'immutable_state.json')
        write_json(baseline/'ui_state.json',state);(baseline/'final_code.html').write_text(code,encoding='utf-8')
        manifest['baseline_status']='html_generated_pending_browser_review'
        payload={'original_transcript':inputs['transcript'],'target_viewport':state['page_meta']['viewport'],
            'immutable_objects':[{k:e.get(k) for k in ['id','type','text','rpa_action']} for e in state['elements']]}
        write_json(candidate/'planner_inputs.json',payload)
        image=shared/'effective_image.jpg'
        image_url='data:image/jpeg;base64,'+base64.b64encode(image.read_bytes()).decode('ascii')
        planner.stage='relative_region_planner'
        response=planner.create(model=model,temperature=0,response_format={'type':'json_object'},messages=[
            {'role':'system','content':(ROOT/'src/prompts/relative_region_layout.md').read_text(encoding='utf-8')},
            {'role':'user','content':[{'type':'text','text':json.dumps(payload,ensure_ascii=False)}, {'type':'image_url','image_url':{'url':image_url}}]}])
        if response.choices[0].finish_reason!='stop':raise ValueError('Relative plan not complete; no retry')
        proposal=parse_spatial_response(response.choices[0].message.content);write_json(candidate/'relative_plan_proposal.json',proposal)
        if not isinstance(proposal,dict) or set(proposal)!={'tree'}:raise ValueError('Expected only relative tree')
        result=compile_relative_layout(state,inputs['transcript'],proposal['tree']);write_json(candidate/'ui_state.json',result)
        write_json(candidate/'shared_state.json',state)
        candidate_code=render_controlled_components(result);(candidate/'final_code.html').write_text(candidate_code,encoding='utf-8')
        manifest['candidate_status']='html_generated_pending_browser_review'
    except Exception as exc:
        manifest.update(error_type=type(exc).__name__)
        if isinstance(exc,ValueError):manifest['validation_reason']=str(exc)
    for name,folder,client in [('baseline_absolute',baseline,upstream),('candidate_relative',candidate,planner)]:
        summary={'status':manifest['baseline_status' if name=='baseline_absolute' else 'candidate_status'],'shared_state_sha256':manifest.get('shared_state_sha256'),
            'shared_call_count':len(upstream.calls),'exclusive_call_count':0 if name=='baseline_absolute' else len(planner.calls),
            'effective_calls':len(upstream.calls)+(len(planner.calls) if name=='candidate_relative' else 0),
            'coder_model_enabled':False,'html_expected':True,'behavior_evaluated':False}
        write_json(folder/'run_summary.json',summary)
    manifest.update(status='finished_pending_review',physical_calls=provider.count,
        total_tokens=sum(c.get('response',{}).get('usage',{}).get('total_tokens',0) for c in upstream.calls+planner.calls),
        request_elapsed_seconds=sum(c['elapsed_seconds'] for c in upstream.calls+planner.calls))
    write_json(batch/'batch.json',manifest)
    write_json(batch/'artifact_manifest.json',{x.relative_to(batch).as_posix():sha256(x) for x in batch.rglob('*') if x.is_file() and x.name!='artifact_manifest.json'})


if __name__=='__main__':main()
