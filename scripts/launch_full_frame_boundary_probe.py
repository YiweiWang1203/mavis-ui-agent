"""Round38: same selected frame, frozen crop versus provenance-checked full frame."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.launch_fragment_boundary_probe import resolve_probe_case
from scripts.run_pilot_experiment import write_json, sha256
from src.utils.full_frame_input import recover_full_frame


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--state', type=Path)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--experiment', choices=['input','focus','permutation'], default='input')
    a = p.parse_args()
    case = resolve_probe_case(a.project, '008_asr_20261022T105518Z_946eac')
    cycles = a.project / 'outputs/optimization_cycles'
    lock = cycles / 'active_generation.lock'
    if not a.worker:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
            raise ValueError('Independent checkout must be clean')
        round_id={'input':'38','focus':'39','permutation':'40'}[a.experiment]
        state = cycles / ('round'+round_id+'_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        with lock.open('x') as f:
            json.dump({'state': str(state)}, f)
        state.mkdir(exist_ok=False)
        r = dict(round=round_id, experiment=a.experiment, status='launching', head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                 checkout=str(ROOT), physical_llm_call_budget=3 if a.experiment=='permutation' else 2, deep_network_forward_cap=0,
                 result_root=str(state/'results'), python_executable=sys.executable)
        write_json(state/'run.json', r)
        with (state/'worker.log').open('ab') as log:
            child = subprocess.Popen([sys.executable,__file__,'--project',str(a.project),'--state',str(state),'--worker','--experiment',a.experiment],
                                     cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        r['worker_pid'] = child.pid
        write_json(state/'launch.json',r)
        print(json.dumps(dict(state=str(state),worker_pid=child.pid,head=r['head'])))
        return
    state = a.state
    r = json.loads((state/'run.json').read_text())
    r.update(status='running',worker_pid=os.getpid())
    write_json(state/'run.json',r)
    try:
        full = state/'full_frame_case'
        provenance = recover_full_frame(case, full)
        original = json.loads((case/'case.json').read_text(encoding='utf-8'))
        for key in ['prompt','transcript']:
            src = (case/original[key]).resolve()
            if not src.is_relative_to(case):raise ValueError('Unsafe case asset')
            shutil.copyfile(src, full/(key+'.txt'))
        write_json(full/'case.json',dict(prompt='prompt.txt',transcript='transcript.txt',image='image.jpg',transcript_source=original['transcript_source']))
        write_json(state/'provenance.json',provenance)
        evidence = state/'results/input_evidence'
        evidence.mkdir(parents=True)
        shutil.copyfile(provenance['raw_source'], evidence/'original_selected_frame.jpg')
        shutil.copyfile(provenance['historical_crop'], evidence/'historical_crop.jpg')
        shutil.copyfile(case/'preprocess/metadata/package.json', evidence/'historical_package.json')
        shutil.copyfile(full/'image.jpg', evidence/'full_frame_oriented.jpg')
        write_json(evidence/'provenance.json',provenance)
        env=os.environ.copy();env['MAVIS_ENV_FILE']=str(a.project/'.env')
        executions=[('full_frame',full)] if a.experiment!='input' else [('frozen_crop',case),('full_frame',full)]
        comparison={'input':'chain_regression','focus':'chain_focus','permutation':'chain_permutation'}[a.experiment]
        for name, source in executions:
            with (state/(name+'.log')).open('wb') as log:
                subprocess.run([sys.executable,str(ROOT/'scripts/run_fragment_boundary_comparison.py'),
                                '--case',str(source),'--output-root',str(state/'results'/name),
                                '--comparison',comparison],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                               timeout={'input':680,'focus':1250,'permutation':1900}[a.experiment],check=True)
        artifacts={x.relative_to(state).as_posix():sha256(x) for x in state.rglob('*')
                   if x.is_file() and x.suffix not in ['.log'] and x.name not in ['run.json','launch.json']}
        write_json(state/'evidence_manifest.json',dict(head=r['head'],artifact_sha256=artifacts,
                   scope=('same fresh candidates, independently reversed labels and positions' if a.experiment=='permutation' else
                          'same fresh candidates and full frame, paired candidate-sheet field of view' if a.experiment=='focus' else
                          'input correction, same historical selected frame; not new frame selection or HTML evaluation')))
        write_json(state/'results/input_evidence/artifact_manifest.json',
                   {x.relative_to(evidence).as_posix():sha256(x) for x in evidence.iterdir() if x.is_file()})
        archive=shutil.make_archive(str(state/'results'), 'zip',root_dir=state,base_dir='results')
        r.update(status='finished_pending_review',archive=archive,archive_sha256=sha256(Path(archive)))
    except Exception as e:
        r.update(status='failed',error_type=type(e).__name__,reason=str(e))
    finally:
        r['finished_utc']=datetime.now(timezone.utc).isoformat()
        write_json(state/'run.json',r)
        if lock.exists() and json.loads(lock.read_text()).get('state')==str(state):lock.unlink()


if __name__ == '__main__':main()
