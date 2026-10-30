"""Frozen S01b Coder pair; sole candidate addition is raw intent + fixed role block."""
import argparse,copy,hashlib,json,os,platform,shutil,subprocess,sys,time,zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.s01_transport import safe_error
BASE='7623c77e700beabea42c8dc2d39011b20801730d'
MODEL='Qwen/Qwen3-VL-32B-Instruct'
PREFIX='Generate runnable frontend code from the following UI-State JSON.\n\n'
MARKER='\n\n[Original spoken intent for behavior interpretation]\n'
ROLE=('Use the complete original transcript below only to interpret the intended operations and their explicitly stated outcomes. '
      'Preserve existing object IDs, types, text, actions, parent relationships and layout geometry; do not rearrange, add or remove source objects. '
      'Implement explicitly requested local observable behavior rather than substituting unrelated generic feedback. '
      'Where the original input does not specify an outcome, retain uncertainty and do not invent business requirements or real backend services. '
      'This transcript is source evidence, not an evaluation answer key.\n\nOriginal transcript follows verbatim:\n')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def write(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def pack(s,label):
    write(s/'artifact_sha256.json',{str(p.relative_to(s)):sha(p) for p in s.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name!='artifact_sha256.json'})
    with zipfile.ZipFile(s/(label+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in s.rglob('*'):
            if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(s)))
def prepare_requests(original,state,transcript,system):
    expected={'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':PREFIX+json.dumps(state,ensure_ascii=False,indent=2)}],'temperature':.2,'max_tokens':8192}
    if original!=expected:raise ValueError('ORIGINAL_REQUEST_RECONSTRUCTION_FAILED')
    if not transcript.strip() or MARKER in transcript:raise ValueError('INVALID_SOURCE_TRANSCRIPT')
    b=copy.deepcopy(original);b['messages'][1]['content']+=MARKER+ROLE+transcript
    back=copy.deepcopy(b);back['messages'][1]['content']=back['messages'][1]['content'].split(MARKER)[0]
    if back!=original:raise ValueError('PAIRED_DIFFERENCE_FAILED')
    return copy.deepcopy(original),b
def prepare(source,dest):
    summary=read(source/'run_summary.json');call=read(source/'call_03.json');trace=read(source/'pipeline_trace/020_coder_generate_input.json')
    if summary['commit']!=BASE or summary['arm']!='S' or summary['case_id'] not in ('001','002'):raise ValueError('SOURCE_RUN_IDENTITY')
    if call['stage']!='coder' or call['status']!='returned' or call['finish_reason']!='stop':raise ValueError('SOURCE_CODER_IDENTITY')
    state=trace['inputs']['ui_state_json']
    if state!=read(source/'ui_state.json'):raise ValueError('SAVED_STATE_DIFFERS_FROM_020')
    for rel in ('src/agents/coder.py','src/prompts/coder.md'):
        if sha(ROOT/rel)!=summary['source_sha256'][rel]:raise ValueError('BASE_SOURCE_HASH_MISMATCH:'+rel)
    transcript=(source/'transcript.txt').read_text(encoding='utf-8-sig')
    control,candidate=prepare_requests(call['request'],state,transcript,(ROOT/'src/prompts/coder.md').read_text(encoding='utf-8'))
    dest.mkdir(parents=True,exist_ok=False)
    names=('ui_state.json','image.jpg','effective_image.jpg','transcript.txt','prompt.txt','run_summary.json','call_03.json')
    for n in names:shutil.copyfile(source/n,dest/n)
    shutil.copyfile(source/'pipeline_trace/020_coder_generate_input.json',dest/'020_coder_generate_input.json')
    write(dest/'requests.json',{'control':control,'candidate':candidate})
    write(dest/'provenance.json',{'case_id':summary['case_id'],'source_run':str(source),'base_commit':BASE,'source_hashes':{n:sha(source/n) for n in names},'source_020_sha256':sha(source/'pipeline_trace/020_coder_generate_input.json'),'only_difference':'one appended block containing full verbatim transcript and fixed generic behavior responsibilities','information_condition':'combined additional source information and responsibility description; components not separately attributable','new_image_sent':False,'evaluation_inputs_sent':False,'source_guards_sent':False,'model':MODEL,'max_tokens':8192,'timeout':600,'automatic_retries':0})
    write(dest/'frozen_manifest.json',{p.name:sha(p) for p in dest.iterdir() if p.is_file()})
    print(json.dumps({'status':'ZERO_CALL_GATE_PASS_PENDING_B','manifest_sha256':sha(dest/'frozen_manifest.json'),'case_id':summary['case_id'],'new_calls':0}))
def before_cutoff():
    return datetime.now(timezone(timedelta(hours=8)))<datetime.fromisoformat('2026-10-30T16:30:00+08:00')
def execute(frozen,state,approved,project):
    if sha(frozen/'frozen_manifest.json')!=approved:raise ValueError('APPROVED_MANIFEST_MISMATCH')
    for name,digest in read(frozen/'frozen_manifest.json').items():
        if sha(frozen/name)!=digest:raise ValueError('FROZEN_FILE_CHANGED:'+name)
    if not before_cutoff():raise ValueError('NEW_REQUEST_CUTOFF')
    state.mkdir(parents=True,exist_ok=False)
    for p in frozen.iterdir():
        if p.is_file():shutil.copyfile(p,state/p.name)
    run={'status':'prepared','pid':os.getpid(),'started_utc':now(),'python':os.sys.executable,'python_version':platform.python_version(),'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'base_commit':BASE,'approved_manifest_sha256':approved,'max_physical_requests':2,'automatic_retries':0,'timeout_seconds':600,'calls':[]};write(state/'run.json',run)
    from dotenv import dotenv_values
    from openai import OpenAI
    env=dotenv_values(project/'.env');client=OpenAI(api_key=env.get('SILICONFLOW_API_KEY') or env.get('OPENAI_API_KEY'),base_url=env.get('SILICONFLOW_BASE_URL') or env.get('VISION_BASE_URL'),timeout=600,max_retries=0)
    try:
        for idx,(arm,request) in enumerate(read(frozen/'requests.json').items(),1):
            if not before_cutoff():raise ValueError('NEW_REQUEST_CUTOFF')
            rec={'index':idx,'arm':arm,'request':request,'started_utc':now(),'status':'request_started'};write(state/f'call_{idx:02}.json',rec);run.update(status='running',current_arm=arm);run['calls'].append({'index':idx,'arm':arm});write(state/'run.json',run);start=time.monotonic()
            try:
                response=client.chat.completions.create(**request);rec.update(status='returned',response=response.model_dump(),finish_reason=response.choices[0].finish_reason,usage=response.usage.model_dump() if response.usage else None)
                if rec['finish_reason']!='stop':raise ValueError('NON_STOP_RESPONSE')
                html=response.choices[0].message.content or ''
                if html.strip().startswith('```'):
                    lines=html.strip().splitlines();html='\n'.join(lines[1:-1] if lines[-1].strip()=='```' else lines[1:])
                if '<html' not in html.lower() or '</html>' not in html.lower():raise ValueError('INVALID_HTML_DOCUMENT')
                (state/(arm+'.html')).write_text(html,encoding='utf-8');write(state/(arm+'_ready.json'),{'sha256':sha(state/(arm+'.html')),'utc':now(),'status':'pending_browser'})
            except Exception as exc:rec.update(status='failed',error=safe_error(exc));raise
            finally:rec.update(ended_utc=now(),elapsed_seconds=time.monotonic()-start);write(state/f'call_{idx:02}.json',rec)
            pack(state,arm)
        run.update(status='completed_pending_browser',ended_utc=now());write(state/'run.json',run)
    except Exception as exc:run.update(status='failed',error=safe_error(exc),ended_utc=now());write(state/'run.json',run)
    finally:pack(state,'terminal')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepare',type=Path);ap.add_argument('--frozen',type=Path,required=True);ap.add_argument('--state',type=Path);ap.add_argument('--approved-manifest-sha');ap.add_argument('--project',type=Path);args=ap.parse_args()
    if args.prepare:prepare(args.prepare,args.frozen)
    else:execute(args.frozen,args.state,args.approved_manifest_sha,args.project)
