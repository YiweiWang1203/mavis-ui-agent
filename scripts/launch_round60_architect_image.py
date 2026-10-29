"""One checked independent checkout and one bounded round60 launch; no retries."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


REMOTE = r'''
import hashlib, json, os, pathlib, subprocess, sys
cfg = json.loads(sys.stdin.readline())
root = pathlib.Path('/wyw/meeting_agent_workspace/my_agent')
previous = json.loads((pathlib.Path(cfg['previous_state'])/'run.json').read_text())
if previous['status'] not in ('finished','finished_pending_review','failed'):
    raise RuntimeError('Previous run not terminal; no launch')
checkout = pathlib.Path('/wyw/meeting_agent_workspace/my_agent_' + cfg['checkout_name'] + '_' + cfg['head'][:7])
if checkout.exists():
    raise RuntimeError('Independent checkout already exists; inspect before any relaunch')
bundle = root/('outputs/optimization_cycles/round' + str(cfg['round']) + '_full.bundle')
if hashlib.sha256(bundle.read_bytes()).hexdigest() != cfg['bundle_sha256']:
    raise RuntimeError('Bundle hash mismatch')
subprocess.run(['git','clone','--no-checkout',str(bundle),str(checkout)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
subprocess.run(['git','-C',str(checkout),'checkout','--detach',cfg['head']], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
python = root/'.venv/bin/python'
tests = ['tests.test_architect_image_context','tests.test_desktop_chat_scaffold','tests.test_projection_flow_layout',
         'tests.test_hierarchy_contract','tests.test_realized_comparison_accounting'] + cfg['extra_tests']
test_log = root/('outputs/optimization_cycles/round' + str(cfg['round']) + '_' + cfg['head'][:7] + '_tests.log')
env = os.environ.copy()
env.update(MAVIS_ENV_FILE=str(root/'.env'), PYTHONPATH=str(checkout))
with test_log.open('w') as f:
    subprocess.run([str(python),'-m','unittest',*tests],cwd=checkout,env=env,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
if 'skipped=' in test_log.read_text():
    raise RuntimeError('Ubuntu engineering gate skipped native checks')
case = root/'outputs/optimization_cycles/round49_20261028T172145Z/full_frame_case'
manifest = json.loads((case/'case.json').read_text())
inputs = {k: hashlib.sha256((case/manifest[k]).read_bytes()).hexdigest() for k in ('image','transcript','prompt')}
if inputs != cfg['input_sha256']:
    raise RuntimeError('Frozen input hash mismatch')
stamp = cfg['stamp']
state = root/('outputs/optimization_cycles/round' + str(cfg['round']) + '_' + stamp + '_' + cfg['checkout_name'])
if state.exists():
    raise RuntimeError('State path already exists')
log = state.with_suffix('.worker.log')
with log.open('wb') as f:
    proc = subprocess.Popen([str(python),cfg['worker'],'--case',str(case),
        '--state',str(state),'--candidate-mode',cfg['candidate_mode']],cwd=checkout,env=env,
        stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
print(json.dumps({'worker_pid':proc.pid,'remote_checkout':str(checkout),'remote_state':str(state),
    'log':str(log),'expected_archive':str(state/'results.zip'),'head':cfg['head'],
    'input_sha256':inputs,'engineering_test_log':str(test_log),
    'python_executable':str(python),'status':'process_started_pending_run_receipt'}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--head', required=True)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--round', type=int, default=60)
    parser.add_argument('--worker', choices=['scripts/run_semantic_plan_comparison.py','scripts/run_vision_observation_comparison.py'], default='scripts/run_semantic_plan_comparison.py')
    parser.add_argument('--candidate-mode', default='architect-same-frame-v1')
    parser.add_argument('--checkout-name', choices=['architect_same_frame','photo_observation','target_layout','full_frame_requirements'],default='architect_same_frame')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    previous = json.loads((root/'outputs/optimization_cycles/current_remote.json').read_text(encoding='utf-8'))
    cfg = {'head': args.head, 'bundle_sha256': args.bundle_sha256,
           'round': args.round,'worker':args.worker,'candidate_mode':args.candidate_mode,'checkout_name':args.checkout_name,
           'previous_state':previous['remote_state'],'extra_tests':(['tests.test_vision_observation_context'] if args.round==61 else ['tests.test_architect_target_layout','tests.test_coordinate_contract'] if args.round==62 else ['tests.test_input_requirement_binder','tests.test_requirement_recovery_guard'] if args.round==63 else []),
           'stamp': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
           'input_sha256': {k: previous['input_'+k+'_sha256'] for k in ('image','transcript','prompt')}}
    # The first stdin line is configuration; the remaining script is executable source.
    command = "python3 -c " + __import__('shlex').quote(REMOTE)
    result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','wangyiwei_2204',command],
        input=json.dumps(cfg)+'\n',encoding='utf-8',capture_output=True,timeout=160)
    if result.returncode:
        raise RuntimeError('Remote engineering gate or launch failed: '+result.stderr[-1600:])
    receipt = json.loads(result.stdout)
    (root/('outputs/optimization_cycles/round'+str(args.round)+'_started_remote.json')).write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
