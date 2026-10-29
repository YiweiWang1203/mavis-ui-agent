"""One constraint request, human-independent B gate, then two isolated Coder calls."""
import argparse,base64,hashlib,json,os,platform,shutil,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.s01_transport import safe_error
from src.utils.composite_input_layout import compile_composite,CONFIG
MODEL='Qwen/Qwen3-VL-32B-Instruct'
def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def pack(s,label):
    files={str(p.relative_to(s)):sha(p) for p in s.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name!='artifact_sha256.json'}
    write(s/'artifact_sha256.json',files)
    with zipfile.ZipFile(s/(label+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in s.rglob('*'):
            if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(s)))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('phase',choices=['plan','render']);ap.add_argument('--state',type=Path,required=True);ap.add_argument('--input',type=Path);ap.add_argument('--project',type=Path,required=True);a=ap.parse_args();s=a.state
    if a.phase=='plan':
        s.mkdir(parents=True,exist_ok=False)
        for n in ('image.jpg','transcript.txt','prompt.txt'):
            shutil.copyfile(a.input/n,s/n)
        for prefix,name in [('016','source.json'),('017','baseline.json')]:
            p=next((a.input/'pipeline_trace').glob(prefix+'*'));d=read(p);write(s/name,d['inputs']['ui_state'] if prefix=='016' else d['output'])
        run={'phase':'plan','status':'prepared','pid':os.getpid(),'started_utc':now(),'python':sys.executable,'python_version':platform.python_version(),'input_run':str(a.input),'config':CONFIG,'max_requests':3,'calls':[],'input_hashes':{n:sha(s/n) for n in ('source.json','baseline.json','image.jpg','transcript.txt','prompt.txt')}}
        write(s/'run.json',run)
    else:
        run=read(s/'run.json');approval=read(s/'B_approval.json')
        if run['status']!='awaiting_B' or approval.get('decision')!='PASS' or approval['contract_sha256']!=sha(s/'contract.json') or not approval.get('six_material_gate_pass'):raise ValueError('B_AND_REGRESSION_GATES_REQUIRED')
        if len(run['calls'])!=1:raise ValueError('REQUEST_BUDGET_GUARD')
    from dotenv import dotenv_values
    from openai import OpenAI
    env=dotenv_values(a.project/'.env');client=OpenAI(api_key=env.get('SILICONFLOW_API_KEY') or env.get('OPENAI_API_KEY'),base_url=env.get('SILICONFLOW_BASE_URL') or env.get('VISION_BASE_URL'),timeout=600,max_retries=0)
    def call(stage,messages,json_mode=False):
        if len(run['calls'])>=3:raise ValueError('REQUEST_BUDGET_GUARD')
        idx=len(run['calls'])+1;record={'stage':stage,'started_utc':now(),'status':'request_started','request':{'model':MODEL,'messages':messages,'temperature':.3 if json_mode else .2,'max_tokens':8192}}
        if json_mode:record['request']['response_format']={'type':'json_object'}
        run['calls'].append({'index':idx,'stage':stage});run.update(status='running',current_stage=stage,pid=os.getpid());write(s/'run.json',run);write(s/f'call_{idx:02}.json',record)
        try:
            response=client.chat.completions.create(**record['request']);record.update(status='returned',response=response.model_dump(),finish_reason=response.choices[0].finish_reason,usage=response.usage.model_dump() if response.usage else None)
            if record['finish_reason']!='stop':raise ValueError('NON_STOP_RESPONSE')
            return response.choices[0].message.content
        except Exception as exc:
            record.update(status='failed',error=safe_error(exc));raise
        finally:record['ended_utc']=now();write(s/f'call_{idx:02}.json',record)
    try:
        if a.phase=='plan':
            instruction='Observe the full image and spoken requirements. Identify ONE composite text-entry region only if supported. Use existing source object IDs without renaming or adding semantic objects/parents. Do not evaluate prior pages. Return JSON {status:supported|unknown, region:{bbox:[target pixel x1,y1,x2,y2], input_id:ID, tools:[{id:ID,horizontal_anchor:left|right,vertical_anchor:bottom,order:integer,quote:exact transcript substring}], boundary_evidence:{quote:exact transcript substring or empty, image_description:string, image_bbox_normalized:[x1,y1,x2,y2]}, scope_reason:string}}. Order is left-to-right within each side. Distinguish observed region boundaries from free space: do not enlarge beyond source-supported range to satisfy layout. Unknown boundaries or identities must yield unknown. Layout engineering minima are body44px high + gap8px + tools44px high, tool width>=44px; these are NOT user statements and never justify inventing space. Target pixels use source page_meta viewport, photo pixels are a different coordinate system. Include all existing tools belonging to the observed region; no answer IDs or fixed target region supplied.'
            source=read(s/'source.json');text=(s/'transcript.txt').read_text(encoding='utf-8-sig')
            messages=[{'role':'system','content':instruction},{'role':'user','content':[{'type':'text','text':json.dumps({'intent':(s/'prompt.txt').read_text(encoding='utf-8-sig'),'transcript':text,'source_state':source},ensure_ascii=False)},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode((s/'image.jpg').read_bytes()).decode()}}]}]
            answer=call('constraint_planner',messages,True);write(s/'contract.json',json.loads(answer));run.update(status='awaiting_B',ended_utc=now());write(s/'run.json',run)
        else:
            c=read(s/'contract.json');source=read(s/'source.json');base=read(s/'baseline.json')
            candidate=compile_composite(source,base,c,(s/'transcript.txt').read_text(encoding='utf-8-sig'));write(s/'candidate.json',candidate)
            system=(ROOT/'src/prompts/coder.md').read_text(encoding='utf-8')
            for arm,state in [('control',base),('candidate',candidate)]:
                content='Generate runnable frontend code from the following UI-State JSON.\n\n'+json.dumps(state,ensure_ascii=False,indent=2)+'\n\nShared source-supported layout context (same in both arms; bbox remains authoritative):\n'+json.dumps(c,ensure_ascii=False)
                answer=call(arm,[{'role':'system','content':system},{'role':'user','content':content}])
                from src.agents.coder import strip_markdown_code_fence
                html=strip_markdown_code_fence(answer)
                if '<html' not in html.lower() or '</html>' not in html.lower():raise ValueError('INVALID_HTML_DOCUMENT')
                (s/(arm+'.html')).write_text(html,encoding='utf-8');write(s/(arm+'_ready.json'),{'sha256':sha(s/(arm+'.html')),'status':'pending_browser','utc':now()})
            run.update(status='completed_pending_browser',ended_utc=now());write(s/'run.json',run)
    except Exception as exc:
        run.update(status='failed',error=safe_error(exc),ended_utc=now());write(s/'run.json',run)
    finally:pack(s,a.phase)

if __name__=='__main__':main()
