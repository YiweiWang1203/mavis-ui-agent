"""Round26: same frozen image, visible-paper crop, OpenCV LSD / official DeepLSD."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def infer(args):
    import cv2
    import numpy as np
    import torch
    from src.utils.paper_line_probe import visible_paper, line_records
    out = args.state/'results'
    out.mkdir(exist_ok=False)
    shutil.copyfile(args.image, out/'image.jpg')
    image = cv2.imread(str(out/'image.jpg'))
    if image is None:
        raise ValueError('Unreadable image')
    mask, paper = visible_paper(image)
    write(out/'paper.json', paper)
    views = {'full_photo': (image, (0, 0))}
    if mask is not None:
        cv2.imwrite(str(out/'visible_paper_mask.png'), mask)
        x1, y1, x2, y2 = paper['bbox_xyxy_exclusive']
        views['visible_paper_crop'] = (image[y1:y2, x1:x2].copy(), (x1, y1))
        preview = image.copy()
        preview[mask == 0] = preview[mask == 0]//3
        cv2.rectangle(preview, (x1, y1), (x2-1, y2-1), (0, 0, 255), 2)
        cv2.imwrite(str(out/'paper_overlay.jpg'), preview)
    sys.path.insert(0, str(args.state/'vendor/DeepLSD'))
    deep_error = None
    model = None
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    try:
        from deeplsd.models.deeplsd_inference import DeepLSD
        model = DeepLSD({'detect_lines': True}).eval().to(device)
        checkpoint = torch.load(args.state/'vendor/deeplsd_md.tar', map_location='cpu', weights_only=True)
        model.load_state_dict(checkpoint['model'], strict=True)
    except Exception as e:
        deep_error = {'error_type': type(e).__name__, 'reason': str(e)}
        write(out/'deeplsd_load_failure.json', deep_error)
    runs = []
    for view_name, (view, offset) in views.items():
        cv2.imwrite(str(out/(view_name+'.png')), view)
        gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
        for method in ['opencv_lsd', 'deeplsd_md']:
            folder = out/(view_name+'__'+method)
            folder.mkdir()
            record = {'method': method, 'view': view_name, 'offset_xy': offset,
                      'view_sha256': digest(out/(view_name+'.png')),
                      'raw_input_sha256': digest(out/'image.jpg'),
                      'status': 'failed', 'accuracy_evaluated': False}
            start = time.monotonic()
            try:
                if method == 'opencv_lsd':
                    raw = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
                    raw = [] if raw is None else raw
                else:
                    if model is None:
                        raise RuntimeError(str(deep_error))
                    tensor = torch.from_numpy(gray.astype(np.float32)/255)[None, None].to(device)
                    if device == 'cuda':
                        torch.cuda.synchronize()
                    with torch.inference_mode():
                        prediction = model({'image': tensor})
                    if device == 'cuda':
                        torch.cuda.synchronize()
                    raw = prediction['lines'][0]
                    np.savez_compressed(folder/'learned_fields.npz',
                        distance=prediction['df'][0].cpu().numpy(),
                        angle=prediction['line_level'][0].cpu().numpy())
                lines = line_records(raw, offset)
                write(folder/'lines.json', lines)
                preview = image.copy()
                for line in lines:
                    a = line['endpoints']
                    cv2.line(preview, (round(a[0]), round(a[1])), (round(a[2]), round(a[3])), (0, 0, 255), 1)
                cv2.imwrite(str(folder/'overlay.jpg'), preview)
                record.update(status='detected_pending_boundary_review', count=len(lines),
                              long_line_count=sum(r['length'] >= .12*min(image.shape[:2]) for r in lines))
            except Exception as e:
                record.update(error_type=type(e).__name__, reason=str(e))
            record['elapsed_seconds'] = time.monotonic()-start
            write(folder/'run_summary.json', record)
            runs.append(record)
    manifest = {'status': 'detected_pending_paper_and_boundary_review', 'runs': runs,
                'paper': paper, 'model_device': device, 'physical_llm_calls': 0,
                'checkpoint_sha256': digest(args.state/'vendor/deeplsd_md.tar'),
                'external_code_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                    cwd=args.state/'vendor/DeepLSD', text=True).strip(),
                'limits': 'Boundary-only development probe. No HTML or functionality scores; counts are not recall.'}
    manifest['artifact_sha256'] = {p.relative_to(out).as_posix(): digest(p)
        for p in out.rglob('*') if p.is_file()}
    write(out/'batch.json', manifest)
    shutil.make_archive(str(out), 'zip', root_dir=out)
    print('Evidence ZIP:', out.with_suffix('.zip'), flush=True)


def worker(args):
    state = args.state
    record = json.loads((state/'run.json').read_text())
    record.update(status='setting_up_isolated_inference', worker_pid=os.getpid())
    write(state/'run.json', record)
    log = state/'setup.log'
    def run(command, timeout=300):
        with log.open('ab') as f:
            subprocess.run(command, check=True, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    try:
        vendor = state/'vendor'
        vendor.mkdir()
        run(['git', 'clone', '--depth', '1', 'https://github.com/cvg/DeepLSD.git', str(vendor/'DeepLSD')])
        run([sys.executable, '-m', 'venv', '--system-site-packages', str(vendor/'venv')])
        python = vendor/'venv/bin/python'
        # Independent venv shares existing torch/cv2, never installs all training requirements.
        run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
             'scikit-image', 'pybind11', 'ninja', 'pytlsd'], timeout=600)
        url = 'https://cvg-data.inf.ethz.ch/DeepLSD/deeplsd_md.tar'
        request = urllib.request.Request(url, headers={'User-Agent': 'MAVIS-boundary-probe'})
        with urllib.request.urlopen(request, timeout=90) as source, (vendor/'deeplsd_md.tar').open('xb') as target:
            shutil.copyfileobj(source, target)
        record.update(status='running_detectors', weight_url=url)
        write(state/'run.json', record)
        run([str(python), str(Path(__file__).resolve()), '--infer', '--state', str(state),
             '--image', str(args.image)], timeout=600)
        record.update(status='finished_pending_review', archive=str(state/'results.zip'),
                      archive_sha256=digest(state/'results.zip'))
    except Exception as e:
        record.update(status='failed', error_type=type(e).__name__, reason=str(e))
    finally:
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write(state/'run.json', record)
        lock = args.project/'outputs/optimization_cycles/active_generation.lock'
        if lock.exists() and json.loads(lock.read_text()).get('state') == str(state):
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--infer', action='store_true')
    args = parser.parse_args()
    if args.infer:
        infer(args)
        return
    if args.worker:
        worker(args)
        return
    project = args.project.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise RuntimeError('Independent checkout must be clean')
    # Use the case's actual frozen image; never use human evaluation coordinates.
    from scripts.run_pilot_experiment import load_inputs
    inputs = load_inputs(project/'outputs/pilot_cases/002_chat_asr_v1', 'M2')
    image = Path(inputs['image']).resolve()
    cycles = project/'outputs/optimization_cycles'
    state = cycles/('round26_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6])
    lock = cycles/'active_generation.lock'
    with lock.open('x') as f:
        json.dump({'state': str(state), 'head': head}, f)
    state.mkdir()
    record = {'round': '26', 'status': 'launching', 'head': head, 'checkout': str(ROOT),
              'image': str(image), 'image_sha256': digest(image), 'case': '002_chat_asr_v1',
              'result_root': str(state/'results'), 'physical_llm_call_budget': 0,
              'expected_archive': str(state/'results.zip'), 'source': 'fresh frozen input detector probe'}
    write(state/'run.json', record)
    with (state/'worker.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker',
            '--project', str(project), '--state', str(state), '--image', str(image)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    record.update(worker_pid=child.pid)
    write(state/'launch.json', record)
    print(json.dumps(record))


if __name__ == '__main__':
    main()
