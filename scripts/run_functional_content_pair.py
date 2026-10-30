"""Functional content paired Coder experiment with equal reviewed structure annotation."""
import argparse
import copy
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = '7623c77e700beabea42c8dc2d39011b20801730d'
MODEL = 'Qwen/Qwen3-VL-32B-Instruct'
PREFIX = 'Generate runnable frontend code from the following UI-State JSON.\n\n'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p, value): Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
def now(): return datetime.now(timezone.utc).isoformat()

def leaf_diff(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(a.keys() | b.keys()) for d in leaf_diff(a.get(k), b.get(k), path+'/'+str(k))]
    if isinstance(a, list) and isinstance(b, list) and len(a)==len(b):
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in leaf_diff(x,y,path+'/'+str(i))]
    return [] if a==b else [{'path':path,'old':a,'new':b}]

def compile_candidate(source_state, solver):
    # No exception recovery: rejected source geometry must not produce a request.
    frozen = copy.deepcopy(source_state)
    candidate = solver(source_state)
    if source_state != frozen: raise ValueError('SOLVER_MUTATED_SOURCE')
    return candidate

def prepare(source, dest, groups_path):
    from src.utils.layout_solver import solve_ui_layout
    summary=read(source/'run_summary.json');historical=read(source/'call_03.json')
    if summary['commit']!=BASE or summary['arm']!='S' or summary['case_id']!='002':raise ValueError('SOURCE_RUN_IDENTITY')
    raw=read(source/'pipeline_trace/016_architect_layout_input.json')['inputs']['ui_state']
    raw['interaction_groups']=read(groups_path)
    control=solve_ui_layout(raw,layout_mode='preserve_target',coordinate_space='target_px_xyxy')
    candidate=solve_ui_layout(raw,layout_mode='functional_content_v1',coordinate_space='target_px_xyxy')
    if control['interaction_groups']!=candidate['interaction_groups']:raise ValueError('COMMON_GROUP_EVIDENCE_CHANGED')
    for source_e,new in zip(raw['elements'],candidate['elements']):
        for key,value in source_e.items():
            if new.get(key)!=value:raise ValueError('SOURCE_FIELD_CHANGED:'+key)
    system=(ROOT/'src/prompts/coder.md').read_text(encoding='utf-8')
    contract=(ROOT/'src/prompts/coder_functional_content.md').read_text(encoding='utf-8')
    if historical['request']['model']!=MODEL or historical['request']['messages'][0]['content']!=system:raise ValueError('ORIGINAL_CODER_SYSTEM_OR_MODEL_CHANGED')
    request=lambda state,sysmsg:{'model':MODEL,'messages':[{'role':'system','content':sysmsg},{'role':'user','content':PREFIX+json.dumps(state,ensure_ascii=False,indent=2)}],'temperature':.2,'max_tokens':8192}
    requests={'control':request(control,system),'candidate':request(candidate,system+'\n\n'+contract)}
    validate_requests(requests)
    dest.mkdir(parents=True,exist_ok=False)
    for name in ('image.jpg','effective_image.jpg','transcript.txt','prompt.txt','run_summary.json','call_03.json'):shutil.copyfile(source/name,dest/name)
    shutil.copyfile(source/'pipeline_trace/016_architect_layout_input.json',dest/'016_architect_layout_input.json')
    shutil.copyfile(groups_path,dest/'reviewed_groups.json')
    write(dest/'control_state.json',control);write(dest/'candidate_state.json',candidate)
    write(dest/'requests.json',requests);write(dest/'layout_diff.json',leaf_diff(control,candidate))
    write(dest/'provenance.json',{'task':'FUNCTIONAL-CONTENT-V1','case_id':'002','source_run':str(source),'source_commit':BASE,
        'source_016_sha256':sha(source/'pipeline_trace/016_architect_layout_input.json'),'manual_structure_annotation':True,
        'both_arms_same_reviewed_groups':True,'conclusion_scope':'given manually reviewed group roles, not automatic discovery',
        'union_footprint_is_engineering_policy_not_GT':True,'new_information_sent':'reviewed group roles and common style metrics equal in both arms',
        'only_candidate_difference':'joint functional render surfaces and explicit Coder consumer contract',
        'prompt_difference':{'control_system_sha256':hashlib.sha256(system.encode()).hexdigest(),'candidate_system_sha256':hashlib.sha256((system+'\n\n'+contract).encode()).hexdigest(),'added_contract_sha256':hashlib.sha256(contract.encode()).hexdigest()},
        'physical_requests_max':2,'timeout':600,'max_tokens':8192,'retries':0,'new_budget_separate_from_preserve_target_four_calls':True})
    write(dest/'frozen_manifest.json',{p.name:sha(p) for p in dest.iterdir() if p.is_file()})
    print(json.dumps({'status':'PREPARED_PENDING_B','manifest_sha256':sha(dest/'frozen_manifest.json'),'physical_requests':0}))

def before_cutoff():
    return datetime.now(timezone(timedelta(hours=8))) < datetime.fromisoformat('2026-10-30T16:30:00+08:00')

def pack(state, label):
    write(state/'artifact_sha256.json',{str(p.relative_to(state)):sha(p) for p in state.rglob('*')
          if p.is_file() and p.suffix!='.zip' and p.name!='artifact_sha256.json'})
    with zipfile.ZipFile(state/(label+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in state.rglob('*'):
            if p.is_file() and p.suffix!='.zip': z.write(p,str(p.relative_to(state)))

def validate_requests(requests):
    if list(requests)!=['control','candidate']: raise ValueError('EXACTLY_TWO_ARMS_REQUIRED')
    for request in requests.values():
        if set(request)!={'model','messages','temperature','max_tokens'}:
            raise ValueError('UNEXPECTED_REQUEST_FIELDS')
        if request['model']!=MODEL or request['temperature']!=.2 or request['max_tokens']!=8192:
            raise ValueError('REQUEST_BUDGET_CHANGED')
        messages=request['messages']
        if len(messages)!=2 or messages[0].get('role')!='system' or messages[1].get('role')!='user':
            raise ValueError('MESSAGE_CONTRACT_CHANGED')
        if not messages[1]['content'].startswith(PREFIX): raise ValueError('USER_PREFIX_CHANGED')
        json.loads(messages[1]['content'][len(PREFIX):])
    system=(ROOT/'src/prompts/coder.md').read_text(encoding='utf-8')
    contract=(ROOT/'src/prompts/coder_functional_content.md').read_text(encoding='utf-8')
    if requests['control']['messages'][0]['content']!=system or requests['candidate']['messages'][0]['content']!=system+'\n\n'+contract:
        raise ValueError('UNAPPROVED_SYSTEM_CONTRACT_DIFFERENCE')
    states=[json.loads(r['messages'][1]['content'][len(PREFIX):]) for r in requests.values()]
    if states[0].get('interaction_groups')!=states[1].get('interaction_groups'):raise ValueError('UNEQUAL_GROUP_EVIDENCE')


def execute(frozen, state, approved, project, acceptance_gate=None, acceptance_gate_sha=None):
    from scripts.s01_transport import safe_error
    if sha(frozen/'frozen_manifest.json')!=approved: raise ValueError('APPROVED_MANIFEST_MISMATCH')
    for name,digest in read(frozen/'frozen_manifest.json').items():
        if sha(frozen/name)!=digest: raise ValueError('FROZEN_FILE_CHANGED:'+name)
    if not before_cutoff(): raise ValueError('NEW_REQUEST_CUTOFF')
    requests=read(frozen/'requests.json')
    validate_requests(requests)
    case=read(frozen/'provenance.json')['case_id']
    if case!='002':raise ValueError('ONLY_002_AUTHORIZED')
    registry=project/'outputs/optimization_cycles/functional_content_v1_execution_registry'
    registry.mkdir(parents=True,exist_ok=True)
    with (registry/(case+'.json')).open('x',encoding='utf-8') as receipt:
        json.dump({'case_id':case,'manifest_sha256':approved,'state':str(state),'admitted_utc':now(),'physical_request_cap':2},receipt)
    state.mkdir(parents=True,exist_ok=False)
    for p in frozen.iterdir():
        if p.is_file(): shutil.copyfile(p,state/p.name)
    run={'task':'FUNCTIONAL-CONTENT-V1','status':'prepared','pid':os.getpid(),'started_utc':now(),
         'python':sys.executable,'python_version':platform.python_version(),
         'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'approved_manifest_sha256':approved,'max_physical_requests':2,'timeout_seconds':600,'retries':0,'calls':[]}
    write(state/'run.json',run)
    from dotenv import dotenv_values
    from openai import OpenAI
    env=dotenv_values(project/'.env')
    client=OpenAI(api_key=env.get('SILICONFLOW_API_KEY') or env.get('OPENAI_API_KEY'),
                  base_url=env.get('SILICONFLOW_BASE_URL') or env.get('VISION_BASE_URL'),timeout=600,max_retries=0)
    try:
        for idx,(arm,request) in enumerate(requests.items(),1):
            if not before_cutoff(): raise ValueError('NEW_REQUEST_CUTOFF')
            rec={'index':idx,'arm':arm,'request':request,'status':'request_started','started_utc':now()}
            write(state/f'call_{idx:02}.json',rec)
            run.update(status='running',current_arm=arm);run['calls'].append({'index':idx,'arm':arm});write(state/'run.json',run)
            start=time.monotonic()
            try:
                response=client.chat.completions.create(**request)
                rec.update(status='returned',response=response.model_dump(),finish_reason=response.choices[0].finish_reason,
                           usage=response.usage.model_dump() if response.usage else None)
                if rec['finish_reason']!='stop': raise ValueError('NON_STOP_RESPONSE')
                html=response.choices[0].message.content or ''
                if html.strip().startswith('```'):
                    lines=html.strip().splitlines();html='\n'.join(lines[1:-1] if lines[-1].strip()=='```' else lines[1:])
                if '<html' not in html.lower() or '</html>' not in html.lower(): raise ValueError('INVALID_HTML_DOCUMENT')
                (state/(arm+'.html')).write_text(html,encoding='utf-8')
                write(state/(arm+'_ready.json'),{'sha256':sha(state/(arm+'.html')),'status':'pending_browser','utc':now()})
            except Exception as exc:
                rec.update(status='failed',error=safe_error(exc));raise
            finally:
                rec.update(ended_utc=now(),elapsed_seconds=time.monotonic()-start);write(state/f'call_{idx:02}.json',rec)
            pack(state,arm)
        run.update(status='completed_pending_browser',ended_utc=now());write(state/'run.json',run)
    except Exception as exc:
        run.update(status='failed',error=safe_error(exc),ended_utc=now());write(state/'run.json',run)
    finally: pack(state,'terminal')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',type=Path);p.add_argument('--frozen',type=Path,required=True)
    p.add_argument('--state',type=Path);p.add_argument('--approved-manifest-sha');p.add_argument('--project',type=Path)
    p.add_argument('--acceptance-gate',type=Path);p.add_argument('--acceptance-gate-sha');p.add_argument('--groups',type=Path)
    a=p.parse_args()
    if a.prepare: prepare(a.prepare,a.frozen,a.groups)
    else: execute(a.frozen,a.state,a.approved_manifest_sha,a.project,a.acceptance_gate,a.acceptance_gate_sha)
