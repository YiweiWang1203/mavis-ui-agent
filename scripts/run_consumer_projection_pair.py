"""Deterministic consumer projection paired Coder experiment; no correction retry."""
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
EVIDENCE_SEPARATOR = '\n\nOriginal user ASR evidence (may contain transcription uncertainty; not evaluation answers):\n'
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

def prepare(source, dest, groups_path=None):
    from src.agents.coder import read_coder_prompt, build_coder_user_content
    original=read(source/'requests.json')
    state=read(source/'candidate_state.json')
    raw_asr=(source/'transcript.txt').read_text(encoding='utf-8')
    original_system=original['candidate']['messages'][0]['content']
    os.environ['UI_CODER_CONTRACT_MODE']='behavior_feedback_v1'
    if read_coder_prompt()!=original_system: raise ValueError('FUNCTIONAL_CONSUMER_CHANGED')
    os.environ['UI_CODER_CONTRACT_MODE']='consumer_projection_v1'
    candidate_system=read_coder_prompt()
    common_user=build_coder_user_content(state,raw_asr)
    requests={arm:{'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':build_coder_user_content(state,raw_asr,consumer_projection=arm=='candidate')}],'temperature':.2,'max_tokens':8192}
              for arm,system in [('control',original_system),('candidate',candidate_system)]}
    validate_requests(requests)
    dest.mkdir(parents=True,exist_ok=False)
    for name in ('image.jpg','effective_image.jpg','transcript.txt','prompt.txt','run_summary.json','call_03.json','016_architect_layout_input.json','reviewed_groups.json'):
        shutil.copyfile(source/name,dest/name)
    for arm in requests:write(dest/(arm+'_state.json'),state)
    from src.utils.consumer_projection import compile_consumer_projection
    write(dest/'consumer_projection.json',compile_consumer_projection(state))
    write(dest/'requests.json',requests)
    write(dest/'request_diff.json',leaf_diff(requests['control'],requests['candidate']))
    write(dest/'provenance.json',{'task':'CONSUMER-PROJECTION-V1','case_id':'002','source_frozen':str(source),'source_manifest_sha256':sha(source/'frozen_manifest.json'),'source_state_sha256':sha(source/'candidate_state.json'),'manual_structure_annotation':True,'same_state_both_arms':True,'same_original_asr_both_arms':True,'candidate_extra_information':'deterministic projection derived only from same state, not external evidence','raw_asr_added_to_both_relative_to_prior_round':True,'no_evaluation_reference_input':True,'physical_requests_max':2,'timeout':600,'retries':0,'only_difference':'final consumer projection plus its geometry and role consumption responsibility','scope':'known development case with manually reviewed interaction group; no end-to-end claim'})
    write(dest/'frozen_manifest.json',{p.name:sha(p) for p in dest.iterdir() if p.is_file()})
    print(json.dumps({'status':'PREPARED_PENDING_B_C','manifest_sha256':sha(dest/'frozen_manifest.json'),'physical_requests':0}))

def before_cutoff():
    return datetime.now(timezone(timedelta(hours=8))) < datetime.fromisoformat('2026-10-30T18:15:00+08:00')

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
        json.loads(messages[1]['content'][len(PREFIX):].split(EVIDENCE_SEPARATOR)[0])
    from src.agents.coder import read_coder_prompt, build_coder_user_content
    from src.utils.consumer_projection import PROJECTION_SEPARATOR
    os.environ['UI_CODER_CONTRACT_MODE']='behavior_feedback_v1'
    control=read_coder_prompt()
    os.environ['UI_CODER_CONTRACT_MODE']='consumer_projection_v1'
    candidate=read_coder_prompt()
    if requests['control']['messages'][0]['content']!=control or requests['candidate']['messages'][0]['content']!=candidate:
        raise ValueError('UNAPPROVED_CONSUMER_DIFFERENCE')
    base=requests['control']['messages'][1]['content']
    if base.count(EVIDENCE_SEPARATOR)!=1 or PROJECTION_SEPARATOR in base:raise ValueError('ORIGINAL_EVIDENCE_REQUIRED_ONCE')
    state_text,asr=base[len(PREFIX):].split(EVIDENCE_SEPARATOR)
    state=json.loads(state_text)
    if requests['candidate']['messages'][1]['content']!=build_coder_user_content(state,asr,consumer_projection=True):raise ValueError('CANDIDATE_HAS_EXTRA_NONDERIVED_INFORMATION')
    if 'Do not add business behavior' in candidate or 'mock click handler' in candidate:raise ValueError('CONFLICTING_RESPONSIBILITY')




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
    registry=project/'outputs/optimization_cycles/consumer_projection_v1_execution_registry'
    registry.mkdir(parents=True,exist_ok=True)
    with (registry/(case+'.json')).open('x',encoding='utf-8') as receipt:
        json.dump({'case_id':case,'manifest_sha256':approved,'state':str(state),'admitted_utc':now(),'physical_request_cap':2},receipt)
    state.mkdir(parents=True,exist_ok=False)
    for p in frozen.iterdir():
        if p.is_file(): shutil.copyfile(p,state/p.name)
    run={'task':'CONSUMER-PROJECTION-V1','status':'prepared','pid':os.getpid(),'started_utc':now(),
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
