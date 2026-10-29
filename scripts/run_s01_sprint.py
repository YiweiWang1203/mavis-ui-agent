"""S01 thin orchestration only: existing pilot chain, explicit models, no repair retries."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, platform, shutil, subprocess, sys, time, zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE='63b9b865bf5c09ef8ab87f3671380cf0a331d1f3'
STRONG='moonshotai/Kimi-K2.7-Code'
REFERENCE='Qwen/Qwen3-VL-8B-Instruct'
FLAGS={'UI_STRUCTURE_MODE':'baseline','UI_FUSION_MODE':'exact_id','LAYOUT_SOLVER_ENABLED':'1',
 'UI_RENDERER_MODE':'llm','UI_CODER_CONTRACT_MODE':'baseline','UI_INPUT_CONTRACT_MODE':'off',
 'UI_SEMANTIC_TYPE_MODE':'off','UI_RELATION_SPECIALIST_MODE':'off','UI_INPUT_SEMANTIC_AUDIT_MODE':'off',
 'UI_RELATION_AGGREGATION_MODE':'off','UI_COORDINATE_RESPONSIBILITY_MODE':'off'}
def now():return datetime.now(timezone.utc).isoformat()
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
from scripts.s01_transport import atomic_write as write, Guard, Transport, counts, terminal
def routing_kwargs(stage,kwargs,models):
 if stage not in models:raise ValueError('Unapproved stage '+stage)
 return {**kwargs,'model':models[stage],'max_tokens':8192}
def pack(folder):
 manifest={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file() and p.name!='artifact_sha256.json'}
 write(folder/'artifact_sha256.json',manifest)
 archive=folder.with_suffix('.zip')
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
  for p in folder.rglob('*'):
   if p.is_file():z.write(p,str(p.relative_to(folder)))
 return {'archive':str(archive),'sha256':digest(archive)}
def prepare(project,state):
 definitions=[('001','taobaoshangpin1_asr_v1',None,'7ce4ec362f59ac9ad7e8cdbc853b65ad3ef81af9669cd763355122ea7762a4b5'),
 ('002','002_chat_asr_v1','round49_20261028T172145Z','340bfd115af912a98a074bc77a8eb00248e8d9e8d47578a0af79b800a495c7c6'),
 ('008','008_asr_20261022T105518Z_946eac','round38_20261028T092647Z','d1e3e82369c511201eceb454a8a8d25fde016c9cda4296d4d3b7627869df7751')]
 cases={}
 for name,old,cycle,expected in definitions:
  src=project/'outputs/pilot_cases'/old;m=json.loads((src/'case.json').read_text())
  dst=state/'cases'/name;dst.mkdir(parents=True)
  provenance={}
  for field in ['image','transcript','prompt']:
   f=(src/m[field]).resolve()
   if field=='image' and cycle:f=project/'outputs/optimization_cycles'/cycle/'full_frame_case/image.jpg'
   suffix='.jpg' if field=='image' else '.txt';target=dst/(field+suffix)
   shutil.copyfile(f,target);provenance[field]={'path':str(f),'sha256':digest(f)}
   assert digest(target)==digest(f)
  assert provenance['image']['sha256']==expected
  assert provenance['prompt']['sha256']=='027f904e73ce81dfa75a96c4bad03c84fc15484de7057e00d1788a57e2c6c9ce'
  if cycle:shutil.copyfile(project/'outputs/optimization_cycles'/cycle/'provenance.json',dst/'frame_provenance.json')
  write(dst/'case.json',{'image':'image.jpg','transcript':'transcript.txt','prompt':'prompt.txt','transcript_source':m['transcript_source']})
  write(dst/'input_provenance.json',provenance);cases[name]=dst
 return cases
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True);ap.add_argument('--state',type=Path,required=True);a=ap.parse_args()
 a.state.mkdir(parents=True,exist_ok=False)
 run={'experiment':'S01','started_utc':now(),'worker_pid':os.getpid(),'base_commit':BASE,
      'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'python':sys.version,'python_executable':sys.executable,'status':'preparing','flags':FLAGS,
      'max_tokens':8192,'timeout_seconds':600,'sdk_retries':0,'max_concurrent_arms':1,
      'updated_at':now(),'counts':counts([]),'current_arm':None,'current_stage':None,
      'models':{'R':REFERENCE,'S':STRONG,'D':STRONG},'arms':[],'cost_currency':None,'cost_amount':None}
 write(a.state/'run.json',run)
 try:
  from dotenv import dotenv_values
  conf=dotenv_values(a.project/'.env')
  # Only provider fields; never import behavior switches from the dirty primary checkout.
  key=conf.get('SILICONFLOW_API_KEY') or conf.get('OPENAI_API_KEY')
  endpoint=conf.get('SILICONFLOW_BASE_URL') or conf.get('VISION_BASE_URL')
  if not key or not endpoint:raise ValueError('Missing provider configuration')
  from urllib.parse import urlsplit
  u=urlsplit(endpoint)
  if u.scheme!='https' or u.username or u.password or u.query or u.fragment:raise ValueError('Invalid endpoint')
  for k in list(os.environ):
   if k.startswith('UI_'):os.environ.pop(k)
  os.environ.update(FLAGS)
  os.environ.update(SILICONFLOW_API_KEY=key,SILICONFLOW_BASE_URL=endpoint,VISION_MODEL=REFERENCE,CODER_MODEL=REFERENCE,CODER_PROD_MODEL=REFERENCE)
  cases=prepare(a.project,a.state)
  from scripts import run_pilot_experiment as pilot
  pilot.write_json=write  # Atomic diagnostic files, without changing pipeline semantics.
  from openai import OpenAI
  client=OpenAI(api_key=key,base_url=endpoint,timeout=600,max_retries=0)
  guard=Guard(run['started_utc'])
  run['prompt_clock']=guard.clock
  class Traced(Transport):
   def __init__(self,output,models,cap,case='probe',arm='probe'):
    super().__init__(client,output,models,cap,guard,run,a.state,case,arm,pilot.safe_messages)
  probe=a.state/'probe';probe.mkdir()
  traced=Traced(probe,{'probe_json':STRONG,'probe_text':STRONG},2)
  image=base64.b64encode((cases['001']/'image.jpg').read_bytes()).decode()
  run['status']='probe_running';write(a.state/'run.json',run)
  traced.stage='probe_json'
  response=traced.create(model=STRONG,temperature=0,response_format={'type':'json_object'},messages=[
   {'role':'system','content':'Return a JSON object only.'},
   {'role':'user','content':[{'type':'text','text':'Briefly describe the visible sketch in one sentence. Return {"description":"..."}. Do not generate a page.'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+image}}]}])
  parsed=json.loads(response.choices[0].message.content)
  if not isinstance(parsed.get('description'),str) or not parsed['description'].strip():raise ValueError('JSON probe contract failed')
  traced.stage='probe_text'
  response=traced.create(model=STRONG,temperature=0,messages=[{'role':'user','content':'Output exactly S01_READY as plain text, without markdown or explanation.'}])
  if response.choices[0].message.content.strip()!='S01_READY':raise ValueError('Text probe contract failed')
  write(probe/'probe_summary.json',{'status':'admitted','usage':[c['response'].get('usage') for c in traced.calls],'warning':'protocol access only; no page quality conclusion'})
  run['probe_archive']=pack(probe);run['status']='generating';write(a.state/'run.json',run)
  sources={str(p.relative_to(ROOT)):digest(p) for directory in ['src','scripts'] for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'}}
  write(a.state/'source_sha256.json',sources)
  for case,casepath in cases.items():
   for arm,model,condition in [('R',REFERENCE,'M2'),('S',STRONG,'M2'),('D',STRONG,'direct')]:
    if guard.blocked or guard.contract_error:
     run['arms'].append({'case':case,'arm':arm,'status':'NOT_EXECUTED_SERVICE_BLOCKED' if guard.blocked else 'NOT_EXECUTED_CONTRACT_BLOCKED'})
     run['counts']=counts(run['arms']);run['updated_at']=now();write(a.state/'run.json',run)
     continue
    folder=a.state/'results'/(case+'_'+arm);folder.mkdir(parents=True)
    models={s:model for s in ['vision','ui_architect','coder','direct']};trace=Traced(folder,models,1 if arm=='D' else 3,case,arm)
    summary={'experiment':'S01','case_id':case,'arm':arm,'condition':condition,'started_utc':now(),'status':'running',
      'commit':run['commit'],'models':models,'renderer':'llm','flags':FLAGS,'source_sha256':sources,'cost_amount':None}
    write(folder/'run_summary.json',summary)
    start=time.monotonic()
    try:
     os.environ.update(FLAGS,VISION_MODEL=model,CODER_MODEL=model,CODER_PROD_MODEL=model)
     inputs=pilot.load_inputs(casepath,condition)
     summary['input_sha256']={k:digest(v) for k,v in inputs['files'].items()}
     try:guard.bind_inputs(case,summary['input_sha256'])
     except ValueError:
      guard.contract_error='input_identity_mismatch';raise
     for k,v in inputs['files'].items():shutil.copyfile(v,folder/(k+v.suffix))
     code=pilot.execute(inputs,condition,trace,folder,model)
     if not isinstance(code,str) or '<html' not in code.lower() or '</html>' not in code.lower():raise ValueError('Incomplete HTML')
     (folder/'final_code.html').write_text(code,encoding='utf-8')
     summary['html_sha256']=digest(folder/'final_code.html');summary['status']='html_generated_pending_browser'
    except Exception as exc:
     summary['status']='failed';summary['error_type']=type(exc).__name__
     # Never serialize provider exception text (may contain authentication headers).
     summary['failure_location']='pilot_or_output_gate; inspect saved stage records and pipeline trace'
    summary.update(finished_utc=now(),elapsed_seconds=time.monotonic()-start,call_count=len(trace.calls),
      usage=[c.get('response',{}).get('usage') for c in trace.calls],response_models=[c.get('response_model') for c in trace.calls])
    write(folder/'run_summary.json',summary)
    artifact=pack(folder);run['arms'].append({'case':case,'arm':arm,'status':summary['status'],'folder':str(folder),**artifact})
    run['counts']=counts(run['arms']);run['updated_at']=now()
    write(a.state/'run.json',run)
    print(json.dumps(run['arms'][-1]),flush=True)
  run['status']=terminal(run['arms']);run['browser_review']='pending' if counts(run['arms'])['success'] else 'no_html'
 except Exception as exc:
  run['status']='failed_preparation_or_admission';run['error_type']=type(exc).__name__
  if 'guard' in locals() and guard.blocked:
   known={(x['case'],x['arm']) for x in run['arms']}
   for case in ('001','002','008'):
    for arm in ('R','S','D'):
     if (case,arm) not in known:run['arms'].append({'case':case,'arm':arm,'status':'NOT_EXECUTED_SERVICE_BLOCKED'})
   run['status']='service_blocked_before_generation'
 finally:
  run['counts']=counts(run['arms']);run['current_arm']=None;run['current_stage']=None
  run['finished_utc']=now();run['updated_at']=now();write(a.state/'run.json',run)
 return 0 if run['status']=='completed_generation' else 1
if __name__=='__main__':raise SystemExit(main())
