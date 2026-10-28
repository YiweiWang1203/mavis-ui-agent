"""Read authoritative Ubuntu state and artifacts; never starts a generation job."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def snapshot(state_dir):
    state_dir = Path(state_dir).resolve()
    record = read_json(state_dir/'run.json')
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(),
              'state_dir': str(state_dir), 'worker_status': record.get('status'),
              'finished_utc': record.get('finished_utc'), 'exit_code': record.get('exit_code'),
              'runs': [], 'archives': [], 'issues': []}
    root = Path(record['result_root']).resolve()
    if not root.is_relative_to(state_dir):
        raise ValueError('Result root is outside the recorded round')
    manifests = sorted(root.glob('*/batch.json'))
    if (root/'batch.json').is_file():
        manifests.append(root/'batch.json')
    if len(manifests) > 1:
        result['issues'].append('multiple_batches_require_explicit_review')
    for path in manifests:
        batch = read_json(path)
        result['batch_status'] = batch.get('status')
        result['batch_path'] = str(path)
        for entry in batch.get('runs', []):
            folder = Path(entry['folder']).resolve() if 'folder' in entry else (
                root/(entry['view']+'__'+entry['method'])).resolve()
            if not folder.is_relative_to(root):
                raise ValueError('Arm folder outside result root')
            summary = read_json(folder/'run_summary.json')
            calls = [read_json(p) for p in sorted(folder.glob('call_*.json'))]
            failures = [{'stage':c.get('stage'), 'error_type':c.get('error_type'),
                         'http_status':c.get('http_status')} for c in calls if c.get('status')=='failed']
            result['runs'].append({'folder':str(folder),'status':summary.get('status'),
                'fusion_mode':summary.get('fusion_mode'),'call_count':summary.get('call_count'),
                'call_failures':failures,'unresolved_relation_count':summary.get('unresolved_relation_count',0),
                'relation_validation_status':summary.get('relation_validation_status'),'html_exists':(folder/'final_code.html').is_file()})
    archives = list(root.glob('*.zip'))
    if root.with_suffix('.zip').is_file():
        archives.append(root.with_suffix('.zip'))
    for path in sorted(archives):
        result['archives'].append({'path':str(path),'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    if record.get('status') in {'finished','finished_pending_review','failed'}:
        result['status'] = 'finished_with_failures' if record.get('status')=='failed' or any(r['call_failures'] for r in result['runs']) else 'finished_pending_review'
        if not result['archives']:
            result['issues'].append('terminal_state_without_archive')
    else:
        result['status']='running'
        if result['archives'] or str(result.get('batch_status','')).startswith('generation_finished'):
            result['status']='completed_artifacts_worker_state_stale'
            result['issues'].append('worker_state_lags_completed_artifacts')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--record',type=Path)
    args=parser.parse_args()
    if args.snapshot:
        print(json.dumps(snapshot(args.snapshot),ensure_ascii=True));return 0
    if not args.record:
        parser.error('Use --snapshot remotely or --record locally')
    record=read_json(args.record)
    command='python3 - --snapshot '+shlex.quote(record['remote_state'])
    proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',record['ssh_alias'],command],
        input=Path(__file__).read_text(encoding='utf-8'),encoding='utf-8',capture_output=True,timeout=45)
    if proc.returncode:
        raise RuntimeError('Remote probe failed; prior state is unverified, not running')
    actual=json.loads(proc.stdout)
    record.update(status=actual['status'],last_checked_utc=actual['checked_utc'],remote_snapshot=actual)
    target=args.record.with_suffix('.tmp')
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');target.replace(args.record)
    print(json.dumps(actual,ensure_ascii=True,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
