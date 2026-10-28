"""Two new model calls shared by normal fitting and parent-geometry reconciliation."""
import argparse
from datetime import datetime, timezone
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
from src.utils.parent_geometry_guard import reconcile_parent_geometry
from src.utils.hierarchy_contract import solve_hierarchy
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
    baseline=batch/'baseline_absolute';baseline.mkdir();candidate=batch/'candidate_parent_geometry';candidate.mkdir()
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env',override=True)
    endpoint=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL');key=os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY');url=urlsplit(endpoint or '')
    if not key or url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credentials and credential-free HTTPS endpoint required')
    model='Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(SILICONFLOW_BASE_URL=endpoint,VISION_MODEL=model,CODER_MODEL=model,CODER_PROD_MODEL=model,
        UI_STRUCTURE_MODE='hierarchy_v1',UI_FUSION_MODE='source_alignment_v1',UI_CODER_CONTRACT_MODE='controlled_components_v1',
        UI_RENDERER_MODE='controlled_components_v1',UI_RELATION_SPECIALIST_MODE='off',UI_RELATION_AGGREGATION_MODE='off',
        UI_SEMANTIC_TYPE_MODE='off',UI_INPUT_SEMANTIC_AUDIT_MODE='off',UI_INPUT_CONTRACT_MODE='off',UI_HIERARCHY_LAYOUT_MODE='baseline',LAYOUT_SOLVER_ENABLED='1')
    provider=CappedProvider(OpenAI(api_key=key,base_url=endpoint,max_retries=0,timeout=600),limit=2)
    upstream=BudgetClient(provider,shared)
    manifest={**source_record(),'status':'started','model':model,'input_sha256':{k:sha256(v) for k,v in inputs['files'].items()},
        'call_accounting':{'physical_cap':2,'shared_upstream_cap':2,'baseline_effective':2,'candidate_effective':2,'exclusive_calls_each':0},
        'max_tokens_per_stage':8192,'timeout_seconds':600,'max_retries':0,
        'runtime':{'python':sys.executable,'version':sys.version,'cv2':cv2.__file__,'numpy':np.__file__},
        'html_expected':True,'output_html_repair':False,'baseline_status':'not_generated','candidate_status':'not_generated'}
    write_json(batch/'batch.json',manifest);print('Batch:',batch,flush=True)
    try:
        code=execute(inputs,'M2',upstream,shared,model)
        if len(upstream.calls)!=2:raise ValueError('Exactly two new shared calls required')
        if not isinstance(code,str) or '<html' not in code.lower() or '</html' not in code.lower():raise ValueError('Shared baseline generation failed')
        state=json.loads((shared/'ui_state.json').read_text(encoding='utf-8'))
        trace=shared/'pipeline_trace/013_architect_hierarchy_layout_input.json'
        pre=json.loads(trace.read_text(encoding='utf-8'))['inputs']['ui_state']
        write_json(shared/'shared_pre_layout_state.json',pre)
        manifest['shared_pre_layout_sha256']=sha256(shared/'shared_pre_layout_state.json')
        # Recompilation must reproduce this new baseline state before changing a parent.
        rebuilt=solve_hierarchy(pre)
        if rebuilt!=state:raise ValueError('Fresh baseline state differs from shared pre-layout compilation')
        write_json(baseline/'ui_state.json',state);(baseline/'final_code.html').write_text(code,encoding='utf-8')
        manifest['baseline_status']='html_generated_pending_browser_review'
        guarded=reconcile_parent_geometry(pre)
        write_json(candidate/'parent_guard_state.json',guarded)
        result=solve_hierarchy(guarded)
        write_json(candidate/'ui_state.json',result)
        (candidate/'final_code.html').write_text(render_controlled_components(result),encoding='utf-8')
        manifest['candidate_status']='html_generated_pending_browser_review'
        manifest['parent_guard']=guarded['page_meta']['parent_geometry_guard']
    except Exception as exc:
        manifest.update(error_type=type(exc).__name__)
        if isinstance(exc,ValueError):manifest['validation_reason']=str(exc)
    for folder,status in [(baseline,manifest['baseline_status']),(candidate,manifest['candidate_status'])]:
        write_json(folder/'run_summary.json',{'status':status,'shared_pre_layout_sha256':manifest.get('shared_pre_layout_sha256'),
            'shared_call_count':len(upstream.calls),'exclusive_call_count':0,'effective_calls':len(upstream.calls),
            'coder_model_enabled':False,'html_expected':True,'behavior_evaluated':False})
    manifest.update(status='finished_pending_review',physical_calls=provider.count,
        total_tokens=sum(c.get('response',{}).get('usage',{}).get('total_tokens',0) for c in upstream.calls),
        request_elapsed_seconds=sum(c['elapsed_seconds'] for c in upstream.calls))
    write_json(batch/'batch.json',manifest)
    write_json(batch/'artifact_manifest.json',{x.relative_to(batch).as_posix():sha256(x) for x in batch.rglob('*') if x.is_file() and x.name!='artifact_manifest.json'})


if __name__=='__main__':main()
