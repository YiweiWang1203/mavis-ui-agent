"""Fresh three-call shared state, paired deterministic layout; no saved HTML input."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_pilot_experiment import execute, load_inputs, write_json, sha256
from scripts.run_generation_comparison import source_record, BudgetClient
from scripts.run_relation_specialist_comparison import CappedProvider, persist_arm
from src.utils.pipeline_trace import PipelineTrace


def fresh_layout_input(shared):
    manifest=json.loads((shared/'pipeline_trace/manifest.json').read_text(encoding='utf-8'))
    events=[e for e in manifest['events'] if e['stage']=='architect.hierarchy_layout.input']
    if len(events)!=1:raise ValueError('Expected one current-run pre-layout state')
    path=shared/'pipeline_trace'/events[0]['file']
    if sha256(path)!=events[0]['sha256']:raise ValueError('Trace input hash mismatch')
    return json.loads(path.read_text(encoding='utf-8'))['inputs']['ui_state']


def fresh_refinement_output(shared):
    manifest=json.loads((shared/'pipeline_trace/manifest.json').read_text(encoding='utf-8'))
    events=[e for e in manifest['events'] if e['stage']=='architect.relation_specialist.output']
    if len(events)!=1:raise ValueError('Expected one current-run relation refinement')
    path=shared/'pipeline_trace'/events[0]['file']
    if sha256(path)!=events[0]['sha256']:raise ValueError('Refinement trace hash mismatch')
    return json.loads(path.read_text(encoding='utf-8'))['output']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--comparison',choices=['layout','relations','empty_slots','semantic_input'],default='layout')
    args=parser.parse_args()
    provenance=source_record();inputs=load_inputs(args.case.resolve(),'M2')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    batch=args.output_root.resolve()/stamp;case=batch/('01_'+args.case.name);shared=case/'shared_upstream'
    shared.mkdir(parents=True)
    inputs=dict(inputs,files=dict(inputs['files']))
    for key,path in list(inputs['files'].items()):
        target=case/(key+path.suffix);shutil.copyfile(path,target);inputs['files'][key]=target
        if key=='image':inputs['image']=target
    hashes={k:sha256(v) for k,v in inputs['files'].items()}
    from dotenv import load_dotenv
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env',override=True)
    key=os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    endpoint=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL');url=urlsplit(endpoint or '')
    if not key or url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credentials and credential-free HTTPS base URL required')
    model='Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(SILICONFLOW_BASE_URL=endpoint,VISION_MODEL=model,CODER_MODEL=model,CODER_PROD_MODEL=model,
        UI_STRUCTURE_MODE='hierarchy_registry_image_v1',UI_FUSION_MODE='source_alignment_v1',
        UI_CODER_CONTRACT_MODE='controlled_components_v1',UI_RENDERER_MODE='controlled_components_v1',
        UI_SEMANTIC_TYPE_MODE='declare_spoken_input_v1' if args.comparison=='semantic_input' else 'off',
        UI_RELATION_SPECIALIST_MODE='container_slots_guard_v1' if args.comparison=='semantic_input' else 'container_slots_v1',UI_RELATION_AGGREGATION_MODE='validated_union_v1' if args.comparison in {'empty_slots','semantic_input'} else 'off',
        UI_HIERARCHY_LAYOUT_MODE='container_extent_v1' if args.comparison in {'relations','empty_slots','semantic_input'} else 'baseline',
        UI_INPUT_CONTRACT_MODE='off',LAYOUT_SOLVER_ENABLED='1')
    from openai import OpenAI
    provider=CappedProvider(OpenAI(api_key=key,base_url=endpoint,max_retries=0,timeout=600),limit=3)
    client=BudgetClient(provider,shared)
    manifest=dict(provenance,status='started',call_limit=3,shared_calls=3,input_sha256=hashes,runs=[],
        comparison=args.comparison,design='same fresh three model responses; deterministic branch changes one declared mechanism')
    write_json(batch/'batch.json',manifest);print('Batch:',batch,flush=True)
    start=time.monotonic();baseline_code=None;baseline_state={'error':'shared_upstream_failed'}
    try:
        baseline_code=execute(inputs,'M2',client,shared,model)
    except Exception as error:write_json(shared/'failure.json',{'error_type':type(error).__name__})
    if (shared/'ui_state.json').is_file():baseline_state=json.loads((shared/'ui_state.json').read_text(encoding='utf-8'))
    elapsed=time.monotonic()-start
    candidate=case/({'relations':'relation_union','empty_slots':'empty_slot_guard','semantic_input':'spoken_input'}.get(args.comparison,'container_extent'));candidate.mkdir()
    candidate_code=None;candidate_state={'error':'no_valid_current_pre_layout_state'}
    common=dict(provenance,model=model,condition='M2',input_sha256=hashes,shared_call_count=len(client.calls),
        shared_request_path=str(shared),shared_usage=[c.get('response',{}).get('usage') for c in client.calls],
        shared_elapsed_seconds=elapsed,renderer='controlled_components_v1',behavior_evaluated=False,
        fusion_mode='source_alignment_v1',structure_mode='hierarchy_registry_image_v1',
        shared_artifact_sha256={p.relative_to(shared).as_posix():sha256(p) for p in shared.rglob('*') if p.is_file()})
    try:
        if args.comparison=='empty_slots':
            from src.utils.relation_evidence import DESCRIPTORS, CONTAINER_ALIASES
            parsed_files=list((shared/'pipeline_trace').glob('*_architect_model_parsed.json'))
            if len(parsed_files)!=1:raise ValueError('Expected one fresh architecture response')
            trace_manifest=json.loads((shared/'pipeline_trace/manifest.json').read_text(encoding='utf-8'))
            parsed_event=[e for e in trace_manifest['events'] if e['stage']=='architect.model_parsed']
            if len(parsed_event)!=1 or parsed_event[0]['sha256']!=sha256(parsed_files[0]):
                raise ValueError('Fresh architecture trace hash mismatch')
            common['shared_architect_state_sha256']=sha256(parsed_files[0])
            state=json.loads(parsed_files[0].read_text(encoding='utf-8'))['output']
            empty=not any(CONTAINER_ALIASES.get(e.get('type'),e.get('type')) in DESCRIPTORS for e in state['elements'])
            if empty:
                from src.agents.relation_specialist import refine_relation_state
                intent=inputs['prompt']+'\n\n[Spoken transcript]\n'+inputs['transcript']
                state=refine_relation_state(state,intent,model,None,mode='container_slots_guard_v1')
                # Two upstream calls shared; the old unnecessary third call is
                # baseline-only, even though its raw evidence lives in shared_upstream.
                common['shared_call_count']=min(2,len(client.calls))
                common['shared_usage']=[c.get('response',{}).get('usage') for c in client.calls[:2]]
            else:
                state=fresh_refinement_output(shared)
            common['empty_slot_guard_triggered']=empty
            common['physical_call_allocation']={'shared_indices':list(range(1,common['shared_call_count']+1)),
                'baseline_exclusive_indices':list(range(common['shared_call_count']+1,len(client.calls)+1)),
                'candidate_exclusive_indices':[]}
        else:
            state=fresh_refinement_output(shared) if args.comparison in {'relations','semantic_input'} else fresh_layout_input(shared)
        state_path=case/('shared_refinement_state.json' if args.comparison in {'relations','empty_slots','semantic_input'} else 'shared_pre_layout_state.json')
        write_json(state_path,state)
        common['shared_branch_input_sha256']=sha256(state_path)
        if args.comparison=='layout':common['shared_pre_layout_sha256']=sha256(state_path)
        if hashes!={k:sha256(v) for k,v in inputs['files'].items()} or source_record()!=provenance:
            raise ValueError('Source or inputs changed during generation')
        from src.utils.hierarchy_contract import solve_hierarchy
        from src.renderers.controlled_components import render_controlled_components
        with PipelineTrace(candidate/'pipeline_trace',{'entrypoint':'fresh_shared_state_comparison','comparison':args.comparison,'branch_input_sha256':common['shared_branch_input_sha256']}):
            if args.comparison in {'relations','empty_slots','semantic_input'}:
                from src.agents.ui_architect import finalize_ui_state
                os.environ['UI_RELATION_AGGREGATION_MODE']='validated_union_v1'
                if args.comparison=='semantic_input':os.environ['UI_SEMANTIC_TYPE_MODE']='spoken_input_v1'
                vision=json.loads((shared/'vision_validated.json').read_text(encoding='utf-8'))
                intent=inputs['prompt']+'\n\n[Spoken transcript]\n'+inputs['transcript']
                candidate_state=finalize_ui_state(copy.deepcopy(state),intent,vision,'hierarchy_registry_image_v1')
            else:
                os.environ['UI_HIERARCHY_LAYOUT_MODE']='container_extent_v1'
                candidate_state=solve_hierarchy(copy.deepcopy(state))
            candidate_code=render_controlled_components(candidate_state)
    except Exception as error:
        candidate_state={'error':type(error).__name__}
        write_json(candidate/'failure.json',{'error_type':type(error).__name__})
    finally:
        os.environ['UI_HIERARCHY_LAYOUT_MODE']='baseline'
        os.environ['UI_RELATION_AGGREGATION_MODE']='off'
        os.environ['UI_SEMANTIC_TYPE_MODE']='off'
    for folder,state,code in [(case/'baseline',baseline_state,baseline_code),(candidate,candidate_state,candidate_code)]:
        exclusive=client.calls[common['shared_call_count']:] if args.comparison=='empty_slots' and folder.name=='baseline' else []
        summary=persist_arm(folder,state,code,dict(common,arm=folder.name),exclusive)
        manifest['runs'].append({'folder':str(folder),'status':summary['status']})
    manifest.update(actual_total_calls=provider.count,shared_calls=common['shared_call_count'],status='generation_finished_pending_browser_validation' if baseline_code and candidate_code else 'generation_finished_with_failures')
    write_json(batch/'batch.json',manifest);shutil.make_archive(str(batch),'zip',root_dir=batch)
    print('Evidence ZIP:',batch.with_suffix('.zip'),flush=True)
    return 0 if baseline_code and candidate_code else 1


if __name__=='__main__':raise SystemExit(main())
