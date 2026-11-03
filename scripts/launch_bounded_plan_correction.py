"""No default launch: requires separately released, hash-bound two-slot approval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile

from src.utils.bounded_plan_correction import MODEL, require, correction_request
from scripts.region_tree_paired_runner import write

NODES = ['candidate_architect_once_correction', 'candidate_coder_if_all_gates_pass']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_deployment(root):
    root = Path(root)
    require(root.resolve(strict=True) == root and not root.is_symlink(), 'DEPLOYMENT_ROOT_MISMATCH')
    manifest_path = root/'deployment_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    require(manifest.get('experiment') == 'historical_answer_once_correction_v1', 'WRONG_EXPERIMENT_MANIFEST')
    seen = set()
    for row in manifest['files'] + manifest['supporting_files']:
        name = row['path']
        require(name not in seen, 'DUPLICATE_MANIFEST_PATH')
        seen.add(name)
        path = root/name
        require(path.resolve(strict=True).is_relative_to(root) and not path.is_symlink(), 'UNSAFE_PACKAGE_PATH')
        require(sha(path) == row['sha256'], 'DEPLOYMENT_HASH_MISMATCH')
    binding = json.loads((root/'prepared_inputs/binding.json').read_text(encoding='utf-8'))
    for name, digest in binding['input_sha256'].items():
        path = root/'prepared_inputs'/name
        require(path.resolve(strict=True).is_relative_to(root/'prepared_inputs') and sha(path) == digest,
                'FROZEN_INPUT_HASH_MISMATCH')
    base = json.loads((root/'prepared_inputs/original_request.json').read_text(encoding='utf-8'))
    answer = (root/'prepared_inputs/original_answer.txt').read_text(encoding='utf-8')
    vision = json.loads((root/'prepared_inputs/vision.json').read_text(encoding='utf-8'))
    intent = (root/'prepared_inputs/intent.txt').read_text(encoding='utf-8')
    require(json.loads(answer) == json.loads((root/'prepared_inputs/original_state.json').read_text(encoding='utf-8')),
            'RAW_ANSWER_AND_STATE_MISMATCH')
    request, feedback = correction_request(base, answer, vision, intent)
    require(request == json.loads((root/'prepared_inputs/correction_request.json').read_text(encoding='utf-8')),
            'PREVIEW_ACTUAL_REQUEST_MISMATCH')
    require(feedback == json.loads((root/'prepared_inputs/machine_feedback.json').read_text(encoding='utf-8')),
            'PREVIEW_MACHINE_FEEDBACK_MISMATCH')
    return manifest, binding, sha(manifest_path)


def verify_approval(approval, run_id, root, manifest, binding, digest):
    require(isinstance(approval, dict) and approval.get('status') == 'APPROVED_NEW_BATCH', 'RELEASE_REQUIRED')
    require(approval.get('commit') == manifest['commit'], 'APPROVAL_COMMIT_MISMATCH')
    require(approval.get('manifest_sha256') == digest, 'APPROVAL_PACKAGE_MISMATCH')
    require(approval.get('input_sha256') == binding['input_sha256'], 'APPROVAL_INPUT_MISMATCH')
    require(approval.get('source_run') == binding['source_run'], 'APPROVAL_ORIGINAL_RUN_MISMATCH')
    require(approval.get('nodes') == NODES, 'APPROVAL_NODE_MISMATCH')
    require(type(approval.get('max_real_requests')) is int and approval['max_real_requests'] == 2,
            'APPROVAL_BUDGET_MISMATCH')
    require(approval.get('model') == MODEL and approval.get('deploy_to') == str(root), 'APPROVAL_TARGET_MISMATCH')
    require(isinstance(run_id, str) and re.fullmatch(r'correction002_[0-9]{8}T[0-9]{6}Z', run_id) is not None and
            approval.get('run_id') == run_id, 'APPROVAL_RUN_MISMATCH')
    require(isinstance(approval.get('authorization_source'), str) and bool(approval['authorization_source'].strip()),
            'COORDINATOR_RELEASE_SOURCE_REQUIRED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--approval-record', required=True, type=Path)
    args = parser.parse_args()
    root = args.root
    require(re.fullmatch(r'/wyw/meeting_agent_workspace/my_agent_bounded_correction_[a-f0-9]{7,40}_v1', str(root)) is not None,
            'ISOLATED_UBUNTU_ROOT_REQUIRED')
    manifest, binding, digest = verify_deployment(root)
    approval = json.loads(args.approval_record.read_text(encoding='utf-8'))
    verify_approval(approval, args.run_id, root, manifest, binding, digest)
    # No credentials/client/process/network before all hashes and concrete release pass.
    batch = root/'runs'/args.run_id
    batch.mkdir(parents=True, exist_ok=False)
    (batch/'inputs').mkdir()
    for name in binding['input_sha256']:
        with (batch/'inputs'/name).open('xb') as stream:
            stream.write((root/'prepared_inputs'/name).read_bytes())
    write(batch/'binding.json', binding)
    write(batch/'approval_record.json', approval)
    write(batch/'run_manifest.json', dict(run_id=args.run_id, commit=manifest['commit'],
        deployment_manifest_sha256=digest, experiment=manifest['experiment'], input_sha256=binding['input_sha256'],
        source_run=binding['source_run'], same_original_answer_not_new_initial_plan=True,
        max_new_requests=2, max_tokens_each=8192, timeout_each=600, retries=0, model=MODEL,
        first_plan_success=False, fair_paired_comparison=False,
        original_costs=binding['historical_costs'], new_costs='recorded separately; unknown currency is not zero'))
    write(batch/'pid.json', dict(pid=os.getpid(), run_id=args.run_id, executable=sys.executable, python=sys.version))

    def status(value, **extra):
        record = dict(status=value, run_id=args.run_id, pid=os.getpid(),
                      updated_utc=datetime.now(timezone.utc).isoformat(), **extra)
        with (batch/'status_events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record)+'\n')
        temporary = batch/'status.next.json'
        temporary.write_text(json.dumps(record), encoding='utf-8')
        os.replace(temporary, batch/'status.json')

    status('RUNNING_NOT_ACCEPTED')
    try:
        from dotenv import load_dotenv
        load_dotenv('/wyw/meeting_agent_workspace/my_agent/.env', override=False)
        os.environ.pop('OPENAI_LOG', None)
        from scripts.run_bounded_plan_correction import correction_transport, run_correction
        t = correction_transport(batch/'transport', args.run_id)
        result = run_correction(
            json.loads((batch/'inputs/original_request.json').read_text(encoding='utf-8')),
            (batch/'inputs/original_answer.txt').read_text(encoding='utf-8'),
            json.loads((batch/'inputs/vision.json').read_text(encoding='utf-8')),
            (batch/'inputs/intent.txt').read_text(encoding='utf-8'), batch/'results', t, export_html=True)
        new_usage = []
        for node in ('architect', 'coder'):
            terminal = batch/'transport'/('candidate_'+node+'_terminal.json')
            if terminal.exists():
                row = json.loads(terminal.read_text(encoding='utf-8'))
                new_usage.append(dict(node=node, status=row['status'], usage=row.get('usage'),
                                      currency_cost=None, missing_cost_is_not_zero=True))
        write(batch/'cost_accounting.json', dict(historical=binding['historical_costs'], new=new_usage,
              counts_are_new_requests_not_replacement_slots=True, currency_total=None,
              historical_candidate_first_failure_preserved=True))
        status(result['status'], result=result)
    except BaseException as exc:
        status('FAILED_NO_RETRY', error_type=type(exc).__name__)
    finally:
        hashes = {str(p.relative_to(batch)):sha(p) for p in batch.rglob('*') if p.is_file() and
                  p.name not in {'run.log','artifact_sha256.json','results.zip','results_zip_sha256.json'}}
        write(batch/'artifact_sha256.json', hashes)
        with zipfile.ZipFile(batch/'results.zip', 'x', compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(hashes):
                z.write(batch/name, name)
            z.write(batch/'artifact_sha256.json', 'artifact_sha256.json')
        write(batch/'results_zip_sha256.json', {'sha256':sha(batch/'results.zip')})


if __name__ == '__main__':
    main()
