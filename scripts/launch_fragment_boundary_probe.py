"""Launch one round29 boundary-only comparison in project UV Python."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_pilot_experiment import write_json,sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--state',type=Path)
    p.add_argument('--worker',action='store_true')
    p.add_argument('--comparison',choices=['fragments','retention','identity','recruitment','chain_identity'],default='fragments')
    a=p.parse_args()
    cycles=a.project/'outputs/optimization_cycles'
    lock=cycles/'active_generation.lock'
    if not a.worker:
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
            raise ValueError('Independent checkout must be clean')
        round_id={'retention':'31','identity':'32','fragments':'29','recruitment':'33','chain_identity':'36'}[a.comparison]
        state=cycles/('round'+round_id+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        with lock.open('x') as f:json.dump({'state':str(state)},f)
        state.mkdir(exist_ok=False)
        record=dict(round=round_id,comparison=a.comparison,status='launching',head=head,checkout=str(ROOT),
                    physical_llm_call_budget=2,deep_network_forward_cap=0,
                    result_root=str(state/'results'),case='002_chat_asr_v1',
                    python_executable=sys.executable,source='fresh frozen-image boundary comparison')
        write_json(state/'run.json',record)
        with (state/'worker.log').open('ab') as log:
            child=subprocess.Popen([sys.executable,__file__,'--project',str(a.project),'--state',str(state),'--worker','--comparison',a.comparison],
                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
        record['worker_pid']=child.pid
        write_json(state/'launch.json',record)
        print(json.dumps(dict(state=str(state),worker_pid=child.pid,head=head)))
        return
    state=a.state
    r=json.loads((state/'run.json').read_text())
    r.update(status='running',worker_pid=os.getpid())
    write_json(state/'run.json',r)
    try:
        env=os.environ.copy()
        env['MAVIS_ENV_FILE']=str(a.project/'.env')
        with (state/'experiment.log').open('wb') as log:
            subprocess.run([sys.executable,str(ROOT/'scripts/run_fragment_boundary_comparison.py'),
                '--case',str(a.project/'outputs/pilot_cases/002_chat_asr_v1'),
                '--output-root',str(state/'results'),'--comparison',a.comparison],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                check=True,timeout=1250)
        packages=list((state/'results').glob('*.zip'))
        if len(packages)!=1:raise ValueError('Expected one original evidence ZIP')
        r.update(status='finished_pending_review',archive=str(packages[0]),archive_sha256=sha256(packages[0]))
    except Exception as e:
        r.update(status='failed',error_type=type(e).__name__,reason=str(e))
    finally:
        r['finished_utc']=datetime.now(timezone.utc).isoformat()
        write_json(state/'run.json',r)
        if lock.exists() and json.loads(lock.read_text()).get('state')==str(state):lock.unlink()


if __name__=='__main__':main()
