"""Approved frozen-upstream behavior input comparison; no layout/vision calls."""
import argparse,copy,hashlib,json,os,platform,shutil,sys,time,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.s01_transport import safe_error
MODEL='Qwen/Qwen3-VL-32B-Instruct'
APPROVED_SHA='e6dfd5086468121369228dea216cdb5ea130e2b1195a94a6a23f1d31c2625df2'
MARKER='\n\n[Source-side observable behavior requirements]\n'
def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def prepare_requests(request,contract):
    base=copy.deepcopy(request)
    if base.get('model')!=MODEL or base.get('temperature')!=.2 or base.get('max_tokens')!=8192:raise ValueError('FROZEN_PARAMS_DIFFER')
    if len(base['messages'])!=2 or base['messages'][0]['role']!='system' or base['messages'][1]['role']!='user' or not isinstance(base['messages'][1]['content'],str):raise ValueError('UNEXPECTED_REQUEST')
    selected=[r for r in contract['requirements'] if r['case_id']=='008']
    if len(selected)!=8 or len({r['requirement_id'] for r in selected})!=8:raise ValueError('CONTRACT_SCOPE')
    block={'version':contract['version'],'requirements':selected}
    candidate=copy.deepcopy(base);candidate['messages'][1]['content']+=MARKER+json.dumps(block,ensure_ascii=False,indent=2)
    test=copy.deepcopy(candidate);test['messages'][1]['content']=test['messages'][1]['content'].split(MARKER)[0]
    if test!=base:raise ValueError('PAIRED_REQUEST_GUARD')
    return base,candidate,block
def pack(s,label):
    write(s/'artifact_sha256.json',{str(p.relative_to(s)):sha(p) for p in s.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name!='artifact_sha256.json'})
    with zipfile.ZipFile(s/(label+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in s.rglob('*'):
            if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(s)))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--state',type=Path,required=True);ap.add_argument('--input',type=Path,required=True);ap.add_argument('--contract',type=Path,required=True);ap.add_argument('--project',type=Path,required=True);a=ap.parse_args()
    if sha(a.contract)!=APPROVED_SHA:raise ValueError('B_APPROVED_HASH_MISMATCH')
    source_call=read(a.input/'call_03.json');contract=read(a.contract)
    base,candidate,block=prepare_requests(source_call['request'],contract)
    state_path=next((a.input/'pipeline_trace').glob('020*'));state=read(state_path)['inputs']['ui_state_json']
    prefix='Generate runnable frontend code from the following UI-State JSON.\n\n'
    if json.loads(base['messages'][1]['content'].removeprefix(prefix))!=state:raise ValueError('FROZEN_STATE_MISMATCH')
    s=a.state;s.mkdir(parents=True,exist_ok=False)
    write(s/'ui_state.json',state);write(s/'selected_contract.json',block)
    for n in ('image.jpg','transcript.txt','prompt.txt'):shutil.copyfile(a.input/n,s/n)
    write(s/'provenance.json',{'input_run':str(a.input),'input_hashes':{n:sha(a.input/n) for n in ('call_03.json','image.jpg','transcript.txt','prompt.txt')},'state_source':str(state_path),'state_sha256':sha(state_path),'contract_file':str(a.contract),'approved_contract_sha256':APPROVED_SHA,'information_condition':'candidate adds human-organized source-side requirements; not equal-information ablation','guards_sent':False,'evaluation_files_sent':False})
    run={'status':'prepared','pid':os.getpid(),'started_utc':now(),'python':sys.executable,'python_version':platform.python_version(),'max_physical_requests':2,'timeout_seconds':600,'automatic_retries':0,'calls':[]};write(s/'run.json',run)
    from dotenv import dotenv_values
    from openai import OpenAI
    env=dotenv_values(a.project/'.env');client=OpenAI(api_key=env.get('SILICONFLOW_API_KEY') or env.get('OPENAI_API_KEY'),base_url=env.get('SILICONFLOW_BASE_URL') or env.get('VISION_BASE_URL'),timeout=600,max_retries=0)
    try:
        for idx,(arm,request) in enumerate([('control',base),('candidate',candidate)],1):
            record={'arm':arm,'request':request,'started_utc':now(),'status':'request_started'};write(s/f'call_{idx:02}.json',record)
            run['calls'].append({'index':idx,'arm':arm});run.update(status='running',current_arm=arm);write(s/'run.json',run)
            start=time.monotonic()
            try:
                res=client.chat.completions.create(**request);record.update(status='returned',response=res.model_dump(),finish_reason=res.choices[0].finish_reason,usage=res.usage.model_dump() if res.usage else None)
                if res.choices[0].finish_reason!='stop':raise ValueError('NON_STOP_RESPONSE')
                from src.agents.coder import strip_markdown_code_fence
                html=strip_markdown_code_fence(res.choices[0].message.content or '')
                if '<html' not in html.lower() or '</html>' not in html.lower():raise ValueError('INVALID_HTML_DOCUMENT')
                (s/(arm+'.html')).write_text(html,encoding='utf-8');write(s/(arm+'_ready.json'),{'status':'pending_browser','sha256':sha(s/(arm+'.html')),'utc':now()})
            except Exception as exc:record.update(status='failed',error=safe_error(exc));raise
            finally:record.update(ended_utc=now(),elapsed_seconds=time.monotonic()-start);write(s/f'call_{idx:02}.json',record)
            pack(s,arm)
        run.update(status='completed_pending_browser',ended_utc=now());write(s/'run.json',run)
    except Exception as exc:run.update(status='failed',error=safe_error(exc),ended_utc=now());write(s/'run.json',run)
    finally:pack(s,'terminal')
if __name__=='__main__':main()
