"""Verify an isolated Ubuntu checkout and launch one bounded UI feedback run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess


REMOTE = r'''
import hashlib,json,os,pathlib,subprocess,sys
cfg=json.loads(sys.stdin.readline())
root=pathlib.Path('/wyw/meeting_agent_workspace/my_agent')
old=json.loads((pathlib.Path(cfg['previous_state'])/'run.json').read_text())
if old.get('status') not in ('finished','finished_pending_review','failed'):
    raise RuntimeError('Previous run is not terminal')
pid=old.get('worker_pid')
cmd=pathlib.Path('/proc')/str(pid)/'cmdline'
if cmd.is_file() and cfg['previous_state'].encode() in cmd.read_bytes():
    raise RuntimeError('Previous worker is still active')
bundle=root/'outputs/optimization_cycles/round66_feedback_full.bundle'
if hashlib.sha256(bundle.read_bytes()).hexdigest()!=cfg['bundle_sha256']:
    raise RuntimeError('Bundle hash mismatch')
checkout=root.parent/('my_agent_feedback_loop_'+cfg['head'][:10])
if checkout.exists():
    raise RuntimeError('Checkout already exists; inspect instead of relaunching')
subprocess.run(['git','clone','--no-checkout',str(bundle),str(checkout)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
subprocess.run(['git','-C',str(checkout),'checkout','--detach',cfg['head']],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
if actual!=cfg['head']:
    raise RuntimeError('Checked-out revision differs')
python=root/'.venv/bin/python'
env=os.environ.copy()
env.update(MAVIS_ENV_FILE=str(root/'.env'),PYTHONPATH=str(checkout),PYTHONIOENCODING='utf-8')
test_log=root/('outputs/optimization_cycles/round66_'+cfg['head'][:10]+'_tests.log')
with test_log.open('w') as f:
    subprocess.run([str(python),'-m','unittest',*cfg['test_modules']],cwd=checkout,env=env,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
if 'skipped=' in test_log.read_text():
    raise RuntimeError('Native graph checks were skipped')
case=root/'outputs/optimization_cycles/round49_20261028T172145Z/full_frame_case'
manifest=json.loads((case/'case.json').read_text())
hashes={k:hashlib.sha256((case/manifest[k]).read_bytes()).hexdigest() for k in ('image','transcript','prompt')}
if hashes!=cfg['input_sha256']:
    raise RuntimeError('Frozen input identity changed')
state=root/('outputs/optimization_cycles/round66_'+cfg['stamp']+'_langgraph_feedback')
if state.exists():
    raise RuntimeError('Run directory exists')
log=pathlib.Path(str(state)+'.worker.log')
with log.open('wb') as f:
    proc=subprocess.Popen([str(python),'scripts/run_feedback_loop_comparison.py','--case',str(case),'--state',str(state)],cwd=checkout,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
print(json.dumps({'worker_pid':proc.pid,'remote_checkout':str(checkout),'remote_state':str(state),'log':str(log),'head':actual,'expected_archive':str(state/'results.zip'),'engineering_test_log':str(test_log),'python_executable':str(python),'input_sha256':hashes,'status':'process_started_pending_worker_receipt','actual_batch':None}))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--head',required=True)
    parser.add_argument('--bundle-sha256',required=True)
    parser.add_argument('--test-module',action='append',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    previous=json.loads((root/'outputs/optimization_cycles/current_remote.json').read_text(encoding='utf-8'))
    cfg={'head':args.head,'bundle_sha256':args.bundle_sha256,
         'previous_state':previous['remote_state'],'input_sha256':previous['input_sha256'],
         'test_modules':args.test_module,'stamp':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','wangyiwei_2204',
                           'python3 -c '+shlex.quote(REMOTE)],input=json.dumps(cfg)+'\n',
                          encoding='utf-8',capture_output=True,timeout=160)
    if result.returncode:
        raise RuntimeError('Remote engineering gate or launch failed: '+result.stderr[-1400:])
    receipt=json.loads(result.stdout)
    (root/'outputs/optimization_cycles/round66_started_remote.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':
    main()
