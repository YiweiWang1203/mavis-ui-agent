"""Two bounded Coder requests; only treatment is a reviewed media content block."""
import argparse,copy,json,os,platform,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_s03_behavior import sha,read,write,pack,now,MODEL,MARKER
from scripts.s01_transport import safe_error
MEDIA_MARKER='\n\n[Source-side media content requirements]\n'
MEDIA_SHA='ed57970141d01fb272d5f3493fd802f1cf174c4d40ae47ea27ed46a720a7cb30'

def prepare_requests(base,state,media,transcript):
    a=copy.deepcopy(base)
    if a.get('model')!=MODEL or a.get('temperature')!=.2 or a.get('max_tokens')!=8192:raise ValueError('FROZEN_PARAMS_DIFFER')
    if len(a['messages'])!=2 or not isinstance(a['messages'][1]['content'],str):raise ValueError('UNEXPECTED_REQUEST')
    content=a['messages'][1]['content'];parts=content.split(MARKER)
    if len(parts)!=2 or MEDIA_MARKER in content:raise ValueError('ORIGINAL_BEHAVIOR_BLOCK_REQUIRED')
    prefix='Generate runnable frontend code from the following UI-State JSON.\n\n'
    if json.loads(parts[0].removeprefix(prefix))!=state:raise ValueError('FROZEN_STATE_MISMATCH')
    behavior=json.loads(parts[1])
    if len(behavior['requirements'])!=8 or any(r['case_id']!='008' for r in behavior['requirements']):raise ValueError('BEHAVIOR_SCOPE')
    source=media['source_object'];matches=[e for e in state['elements'] if all(e.get(k)==v for k,v in source.items())]
    if len(matches)!=1:raise ValueError('MEDIA_SOURCE_UNKNOWN')
    if not media.get('source_quote') or media['source_quote'] not in transcript:raise ValueError('QUOTE_NOT_FOUND')
    b=copy.deepcopy(a);b['messages'][1]['content']+=MEDIA_MARKER+json.dumps(media,ensure_ascii=False,indent=2)
    check=copy.deepcopy(b);check['messages'][1]['content']=check['messages'][1]['content'].split(MEDIA_MARKER)[0]
    if check!=a:raise ValueError('PAIRED_DIFFERENCE_GUARD')
    return a,b

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--state',type=Path,required=True);ap.add_argument('--input',type=Path,required=True);ap.add_argument('--media',type=Path,required=True);ap.add_argument('--project',type=Path,required=True);a=ap.parse_args()
    if sha(a.media)!=MEDIA_SHA:raise ValueError('APPROVED_MEDIA_HASH_MISMATCH')
    state=read(a.input/'ui_state.json');media=read(a.media);source_call=read(a.input/'call_02.json')
    if source_call.get('arm')!='candidate' or source_call.get('finish_reason')!='stop':raise ValueError('SOURCE_RUN_IDENTITY')
    control,candidate=prepare_requests(source_call['request'],state,media,(a.input/'transcript.txt').read_text(encoding='utf-8-sig'))
    s=a.state;s.mkdir(parents=True,exist_ok=False)
    for n in ('ui_state.json','image.jpg','transcript.txt','prompt.txt'):shutil.copyfile(a.input/n,s/n)
    shutil.copyfile(a.media,s/'media_content_contract.json')
    write(s/'provenance.json',{'input_run':str(a.input),'source_hashes':{n:sha(a.input/n) for n in ('ui_state.json','image.jpg','transcript.txt','prompt.txt','call_02.json')},'media_sha256':MEDIA_SHA,'information_condition':'candidate adds source-role media content requirements; not equal-information ablation','layout_changed':False,'structural_guards_sent':False,'behavior_same':True,'engineering_settings':media['engineering_settings']})
    run={'status':'prepared','pid':os.getpid(),'started_utc':now(),'python':sys.executable,'python_version':platform.python_version(),'max_physical_requests':2,'timeout_seconds':600,'automatic_retries':0,'calls':[]};write(s/'run.json',run)
    from dotenv import dotenv_values
    from openai import OpenAI
    env=dotenv_values(a.project/'.env');client=OpenAI(api_key=env.get('SILICONFLOW_API_KEY') or env.get('OPENAI_API_KEY'),base_url=env.get('SILICONFLOW_BASE_URL') or env.get('VISION_BASE_URL'),timeout=600,max_retries=0)
    try:
        for idx,(arm,request) in enumerate([('control',control),('candidate',candidate)],1):
            rec={'arm':arm,'request':request,'started_utc':now(),'status':'request_started'};write(s/f'call_{idx:02}.json',rec);run['calls'].append({'index':idx,'arm':arm});run.update(status='running',current_arm=arm);write(s/'run.json',run);start=time.monotonic()
            try:
                res=client.chat.completions.create(**request);rec.update(status='returned',response=res.model_dump(),finish_reason=res.choices[0].finish_reason,usage=res.usage.model_dump() if res.usage else None)
                if rec['finish_reason']!='stop':raise ValueError('NON_STOP_RESPONSE')
                from src.agents.coder import strip_markdown_code_fence
                html=strip_markdown_code_fence(res.choices[0].message.content or '')
                if '<html' not in html.lower() or '</html>' not in html.lower():raise ValueError('INVALID_HTML_DOCUMENT')
                (s/(arm+'.html')).write_text(html,encoding='utf-8');write(s/(arm+'_ready.json'),{'sha256':sha(s/(arm+'.html')),'status':'pending_browser','utc':now()})
            except Exception as exc:rec.update(status='failed',error=safe_error(exc));raise
            finally:rec.update(ended_utc=now(),elapsed_seconds=time.monotonic()-start);write(s/f'call_{idx:02}.json',rec)
            pack(s,arm)
        run.update(status='completed_pending_browser',ended_utc=now());write(s/'run.json',run)
    except Exception as exc:run.update(status='failed',error=safe_error(exc),ended_utc=now());write(s/'run.json',run)
    finally:pack(s,'terminal')
if __name__=='__main__':main()
