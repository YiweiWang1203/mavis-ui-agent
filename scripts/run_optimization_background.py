"""Launch one bounded experiment and persist state for the next heartbeat."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]

def write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--worker-token')
    parser.add_argument('--trial', choices=['source_alignment','hierarchy','placement','typed_controls','controlled','relations','partial_relations','container_registry','inline_registry','visual_context'], default='source_alignment')
    args = parser.parse_args()
    project = args.project.resolve()
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip()
    if head != args.expected_head or dirty:
        raise RuntimeError('Checkout must be clean and match expected commit')
    case = project/'outputs/pilot_cases/008_asr_20261022T105518Z_946eac'
    if not (case/'case.json').is_file() or not (project/'.env').is_file():
        raise RuntimeError('Existing case or configuration unavailable')
    cycles = project/'outputs/optimization_cycles'
    cycles.mkdir(parents=True, exist_ok=True)
    lock = cycles/'active_generation.lock'
    if not args.worker_token:
        token = uuid.uuid4().hex
        round_id = {'hierarchy':'05','source_alignment':'04','placement':'06','typed_controls':'07','controlled':'08','relations':'09','partial_relations':'10','container_registry':'11','inline_registry':'12','visual_context':'13'}[args.trial]
        state = cycles/('round'+round_id+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+token[:6])
        # Exclusive global reservation: never silently clear an existing lock.
        with lock.open('x', encoding='utf-8') as f:
            json.dump({'token':token, 'state':str(state), 'head':head},f)
        try:
            state.mkdir(exist_ok=False)
            record = {'round':round_id,'status':'launching','head':head,'checkout':str(ROOT),
                'case':str(case),'result_root':str(state/'results'), 'token':token,
                'command_budget':{'max_calls':{'controlled':5,'relations':4,'partial_relations':4,'container_registry':4,'inline_registry':4,'visual_context':4}.get(args.trial,6),'max_tokens_per_stage':8192,'timeout_seconds':600,'automatic_retries':0},
                'goal':{'hierarchy':'Hierarchy and source contract','placement':'Compiled page-global placement contract','source_alignment':'Source identity correspondence','typed_controls':'Typed native component implementation','controlled':'Controlled component generation','relations':'Source-grounded containment ledger','partial_relations':'Isolate local relation source errors','container_registry':'Source-backed container registry and reference closure','inline_registry':'Compile source-backed containers from one node table','visual_context':'Retain original sketch image at architecture fusion'}[args.trial]}
            write(state/'run.json',record)
            with (state/'worker.log').open('ab', buffering=0) as log:
                child = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--project',str(project),
                    '--expected-head',head,'--trial',args.trial,'--state',str(state),'--worker-token',token],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            record.update(worker_pid=child.pid,status='launched')
            # Worker owns subsequent state changes; launcher stores PID separately.
            write(state/'launch.json',record)
            print(json.dumps({'worker_pid':child.pid,'state':str(state),'results':str(state/'results')},ensure_ascii=False))
        except Exception:
            if lock.exists() and json.loads(lock.read_text())['token'] == token:
                lock.unlink()
            raise
        return 0
    state = args.state.resolve()
    if not state.is_relative_to(cycles) or json.loads(lock.read_text())['token'] != args.worker_token:
        raise RuntimeError('Invalid worker reservation')
    record = json.loads((state/'run.json').read_text())
    command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
        '--cases',str(case),'--modes','baseline','--fusion-modes','exact_id','source_alignment_v1',
        '--output-root',str(state/'results')]
    if args.trial=='hierarchy':
        command = command[:command.index('--fusion-modes')] + ['--fusion-modes','source_alignment_v1','--structure-modes','baseline','hierarchy_v1','--output-root',str(state/'results')]
    if args.trial=='placement':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','baseline','placement_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_v1','--output-root',str(state/'results')]
    if args.trial=='typed_controls':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','placement_v1','typed_controls_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_v1','--output-root',str(state/'results')]
    if args.trial=='controlled':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','typed_controls_v1','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_v1','--output-root',str(state/'results')]
    if args.trial=='relations':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_v1','hierarchy_evidence_v1','--output-root',str(state/'results')]
    if args.trial=='partial_relations':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_evidence_v1','hierarchy_partial_evidence_v1','--output-root',str(state/'results')]
    if args.trial=='container_registry':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_partial_evidence_v1','hierarchy_registry_v1','--output-root',str(state/'results')]
    if args.trial=='inline_registry':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_registry_v1','hierarchy_registry_inline_v1','--output-root',str(state/'results')]
    if args.trial=='visual_context':
        command = [sys.executable,'-u',str(ROOT/'scripts/run_generation_comparison.py'),
            '--cases',str(case),'--modes','controlled_components_v1','--fusion-modes','source_alignment_v1',
            '--structure-modes','hierarchy_registry_inline_v1','hierarchy_registry_image_v1','--output-root',str(state/'results')]
    record.update(status='running',worker_pid=os.getpid(),command=command)
    write(state/'run.json',record)
    environment = dict(os.environ, MAVIS_ENV_FILE=str(project/'.env'))
    try:
        result = subprocess.run(command,cwd=ROOT,env=environment,check=False)
        record.update(status='finished' if result.returncode==0 else 'failed',exit_code=result.returncode,
                      evidence_archives=[str(p) for p in (state/'results').glob('*.zip')])
    except Exception as error:
        record.update(status='failed',error_type=type(error).__name__)
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        write(state/'run.json',record)
        if lock.exists() and json.loads(lock.read_text())['token']==args.worker_token:
            lock.unlink()
    return 0 if record['status']=='finished' else 1

if __name__=='__main__':
    raise SystemExit(main())
