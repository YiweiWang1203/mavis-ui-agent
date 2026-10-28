"""Resume before inference with explicit original-project dependency visibility."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_paper_line_probe import write, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--worker', action='store_true')
    a = p.parse_args()
    old = json.loads((a.previous/'run.json').read_text())
    state = a.previous.with_name(a.previous.name+'_environment_fix')
    lock = a.project/'outputs/optimization_cycles/active_generation.lock'
    if not a.worker:
        assert old['status'] == 'failed'
        assert not (a.previous/'results').exists(), 'Inference outputs exist: audit before any resume'
        assert digest(a.previous/'vendor/deeplsd_md.tar') == old['checkpoint_sha256']
        with lock.open('x') as f:
            json.dump({'state': str(state)}, f)
        state.mkdir(exist_ok=False)
        record = dict(old, status='launching_environment_fix', recovery_of=str(a.previous),
                      result_root=str(state/'results'), expected_archive=str(state/'results.zip'),
                      recovery_code_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        for key in ['error_type','reason','finished_utc','worker_pid']:
            record.pop(key, None)
        write(state/'run.json', record)
        with (state/'worker.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, __file__, '--worker', '--previous', str(a.previous),
                                      '--project', str(a.project)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        print(json.dumps({'state': str(state), 'worker_pid': child.pid}))
        return
    record = json.loads((state/'run.json').read_text())
    record.update(worker_pid=os.getpid(), status='running_detectors')
    write(state/'run.json', record)
    try:
        vendor = state/'vendor'
        vendor.mkdir()
        for name in ['DeepLSD','venv','deeplsd_md.tar']:
            (vendor/name).symlink_to(a.previous/'vendor'/name)
        project_sites = subprocess.check_output([str(a.project/'.venv/bin/python'), '-c',
            'import site,json; print(json.dumps(site.getsitepackages()))'],text=True).strip()
        # venv --system-site-packages exposes the base interpreter, not a parent venv.
        # Append project packages after isolated packages, without modifying either environment.
        bootstrap = ('import site,runpy,sys; '
                     f'[site.addsitedir(p) for p in {project_sites}]; '
                     f'sys.argv={[str(ROOT/"scripts/run_paper_line_probe.py"),"--infer","--state",str(state),"--image",old["image"]]!r}; '
                     f'runpy.run_path({str(ROOT/"scripts/run_paper_line_probe.py")!r},run_name="__main__")')
        with (state/'inference.log').open('wb') as log:
            subprocess.run([str(vendor/'venv/bin/python'),'-c',bootstrap],cwd=ROOT,stdout=log,
                           stderr=subprocess.STDOUT,check=True,timeout=600)
        record.update(status='finished_pending_review', archive_sha256=digest(state/'results.zip'))
    except Exception as e:
        record.update(status='failed',error_type=type(e).__name__,reason=str(e))
    finally:
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write(state/'run.json',record)
        if lock.exists() and json.loads(lock.read_text()).get('state') == str(state):
            lock.unlink()


if __name__ == '__main__':
    main()
