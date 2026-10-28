"""One explicit bounded HTTP Range recovery; preserve failed run and inference protocol."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_paper_line_probe import write, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--worker', action='store_true')
    args = p.parse_args()
    old = args.previous.resolve()
    previous = json.loads((old/'run.json').read_text())
    state = old.with_name(old.name+'_recovery01')
    lock = args.project/'outputs/optimization_cycles/active_generation.lock'
    if not args.worker:
        if previous['status'] != 'failed':
            raise ValueError('Recovery requires preserved failed run')
        with lock.open('x') as f:
            json.dump({'state': str(state)}, f)
        state.mkdir(exist_ok=False)
        write(state/'run.json', dict(previous, status='launching_recovery', recovery_of=str(old),
            result_root=str(state/'results'), expected_archive=str(state/'results.zip'),
            recovery_code_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
        with (state/'worker.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker',
                '--previous', str(old), '--project', str(args.project)], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print(json.dumps({'state':str(state),'worker_pid':child.pid}))
        return
    record = json.loads((state/'run.json').read_text())
    record.update(status='recovering_weight', worker_pid=os.getpid())
    write(state/'run.json', record)
    try:
        vendor = state/'vendor'
        vendor.mkdir()
        for name in ['DeepLSD','venv']:
            (vendor/name).symlink_to(old/'vendor'/name, target_is_directory=True)
        source = old/'vendor/deeplsd_md.tar'
        target = vendor/'deeplsd_md.tar'
        shutil.copyfile(source, target)
        start = target.stat().st_size
        url = 'https://cvg-data.inf.ethz.ch/DeepLSD/deeplsd_md.tar'
        began = time.monotonic()
        request = urllib.request.Request(url, headers={'Range': f'bytes={start}-',
            'If-Range':'Mon, 30 Oct 2023 16:19:55 GMT'})
        with urllib.request.urlopen(request, timeout=15) as response:
            span = response.headers.get('Content-Range','')
            if response.status != 206 or not span.startswith(f'bytes {start}-'):
                raise ValueError('Server did not honor exact resume offset')
            total = int(span.split('/')[-1])
            record.update(resume_start_bytes=start, content_range=span,
                          partial_source_sha256=digest(source), download_total_deadline_seconds=120)
            write(state/'run.json', record)
            with target.open('ab') as f:
                while True:
                    if time.monotonic()-began > 120:
                        raise TimeoutError('Whole recovery download deadline exceeded')
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        if target.stat().st_size != total:
            raise ValueError('Weight size does not match authoritative range total')
        record.update(status='running_detectors', checkpoint_sha256=digest(target))
        write(state/'run.json', record)
        python = vendor/'venv/bin/python'
        with (state/'inference.log').open('wb') as log:
            subprocess.run([str(python), str(ROOT/'scripts/run_paper_line_probe.py'), '--infer',
                '--state', str(state), '--image', previous['image']],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
        record.update(status='finished_pending_review', archive_sha256=digest(state/'results.zip'))
    except Exception as e:
        record.update(status='failed', error_type=type(e).__name__, reason=str(e))
    finally:
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write(state/'run.json', record)
        if lock.exists() and json.loads(lock.read_text()).get('state') == str(state):
            lock.unlink()


if __name__ == '__main__':
    main()
