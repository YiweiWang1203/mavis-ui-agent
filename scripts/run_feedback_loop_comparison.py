"""Run one shared-observation/shared-first-architect feedback comparison (<=3 calls)."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_generation_comparison import BudgetClient, source_record
from scripts.run_input_audit_comparison import CappedProvider
from scripts.run_pilot_experiment import load_inputs, sha256, write_json


def _head():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _archive(folder: Path, target: Path):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent).as_posix())


def _finalize_state(batch: Path, archive_path: Path, state_dir: Path, run: dict):
    manifest_path = batch / 'artifact_manifest.json'
    artifacts = {path.relative_to(batch).as_posix(): sha256(path)
                 for path in sorted(batch.rglob('*'))
                 if path.is_file() and path != manifest_path}
    write_json(manifest_path, {'hash_algorithm': 'sha256', 'self_included': False,
                               'artifacts': artifacts})
    _archive(batch, archive_path)
    run['archive_sha256'] = sha256(archive_path)
    write_json(state_dir / 'run.json', run)


def _clean_graph_result(value):
    return {key: item for key, item in value.items() if key not in {'messages'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path,
                        help='New directory receiving run.json, batch artifacts and results.zip')
    parser.add_argument('--model', default='Qwen/Qwen3-VL-8B-Instruct')
    parser.add_argument('--target-id', default='pc-1440x900')
    parser.add_argument('--target-width', type=int, default=1440)
    parser.add_argument('--target-height', type=int, default=900)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    state_dir = args.state.resolve()
    state_dir.mkdir(parents=True, exist_ok=False)
    batch = state_dir / ('batch_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                         + '_' + uuid.uuid4().hex[:8])
    batch.mkdir()
    archive_path = state_dir / 'results.zip'
    run = {'actual_batch': str(batch), 'worker_pid': os.getpid(), 'head': _head(),
           'status': 'dry_run' if args.dry_run else 'running',
           'expected_archive': str(archive_path), 'effect_round_counted': False,
           'call_limit': 3, 'api_auto_retries': 0, 'python_executable': sys.executable,
           'started_utc': datetime.now(timezone.utc).isoformat(),
           'comparison': 'same observation and first architect; baseline stops, candidate permits one repair'}
    write_json(state_dir / 'run.json', run)
    inputs = load_inputs(args.case.resolve(), 'M2')
    if args.target_width <= 0 or args.target_height <= 0:
        raise ValueError('Positive target viewport required')
    copied = batch / 'inputs'; copied.mkdir()
    local_files = {}
    for key, source in inputs['files'].items():
        target = copied / (key + source.suffix)
        shutil.copyfile(source, target); local_files[key] = target
    inputs = dict(inputs, files=local_files, image=local_files['image'])
    input_hashes = {key: sha256(path) for key, path in local_files.items()}
    run['input_sha256'] = input_hashes
    target_requirement = (
        f'目标设备：电脑网页；目标画布{args.target_width}×{args.target_height}。')
    effective_prompt = inputs['prompt'].rstrip() + '\n\n' + target_requirement
    intent = effective_prompt + '\n\n[Spoken transcript]\n' + inputs['transcript']
    (batch / 'effective_request.txt').write_text(intent, encoding='utf-8')
    run['effective_request_sha256'] = sha256(batch / 'effective_request.txt')
    write_json(batch / 'input_manifest.json', {'sha256': input_hashes,
        'transcript_source': inputs['transcript_source'], 'source': source_record()})
    if args.dry_run:
        run.update(status='dry_run_validated', actual_model_calls=0, usage=[])
        _finalize_state(batch, archive_path, state_dir, run); return

    try:
        from dotenv import load_dotenv
        load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT / '.env', override=True)
        key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
        endpoint = os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
        from urllib.parse import urlsplit
        url = urlsplit(endpoint or '')
        if not key or url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError('Existing credentials and credential-free HTTPS base URL required')
        from openai import OpenAI
        provider = CappedProvider(OpenAI(api_key=key, base_url=endpoint,
                                         max_retries=0, timeout=600), limit=3)
        client = BudgetClient(provider, batch)
        os.environ.update(VISION_MODEL=args.model, CODER_MODEL=args.model,
                          CODER_PROD_MODEL=args.model)
        from PIL import Image
        with Image.open(inputs['image']) as image:
            width, height = image.size
        trusted = {
            'observation_frame': {'id': 'frame-' + input_hashes['image'][:12],
                                  'width': width, 'height': height,
                                  'sha256': input_hashes['image']},
            'target_viewport': {'id': args.target_id, 'width': args.target_width,
                                'height': args.target_height},
        }
        from src.tools import vision_tool
        from src.utils.pipeline_trace import PipelineTrace
        client.stage = 'vision'
        with patch.object(vision_tool, 'OpenAI', return_value=client), PipelineTrace(
                batch / 'shared_trace', {'entrypoint': 'langgraph_feedback_shared_upstream',
                'physical_call_limit': 3, 'api_auto_retries': 0}):
            raw_vision = vision_tool.extract_ui_layout(
                str(inputs['image']), user_context=intent)
            vision, validation = vision_tool.validate_vision_layout(raw_vision, str(inputs['image']))
            write_json(batch / 'vision_raw.json', raw_vision)
            write_json(batch / 'vision_validation.json', validation.model_dump())
            write_json(batch / 'vision_validated.json', vision)
            if not validation.valid:
                raise RuntimeError('Shared vision failed validation; no architect request made')
            from src.agents.ui_architect import generate_target_layout_attempt
            client.stage = 'architect_first'
            first = generate_target_layout_attempt(intent, vision, trusted, client=client,
                                                   attempt_id='architect-0')
            write_json(batch / 'architect_first_attempt.json', first)

        from src.graph.ui_feedback_graph import build_ui_feedback_graph
        from src.renderers.controlled_components import render_controlled_components
        common = {'user_intent': intent, 'vision_elements': vision,
                  'trusted_coordinate_context': trusted, 'attempts': [copy.deepcopy(first)],
                  'feedback_history': [], 'quality_history': [], 'route_history': [],
                  'downstream_history': [], 'pending_feedback': None,
                  'ui_state_json': None, 'final_code': None, 'browser_audit': None,
                  'model_call_count': 0}

        def forbidden_first(**kwargs):
            raise RuntimeError('Shared first architect attempt must not be repeated')
        baseline_graph = build_ui_feedback_graph(forbidden_first, render_controlled_components,
                                                 allow_repair=False)
        with PipelineTrace(batch / 'baseline_trace', {'arm': 'baseline',
                           'shared_first_attempt_sha256': sha256(batch / 'architect_first_attempt.json')}):
            baseline = baseline_graph.invoke(dict(common, model_call_limit=0))
        baseline_dir = batch / 'baseline'; baseline_dir.mkdir()
        write_json(baseline_dir / 'state.json', _clean_graph_result(baseline))
        if baseline.get('final_code'):
            (baseline_dir / 'final_code.html').write_text(baseline['final_code'], encoding='utf-8')

        def repair_call(**kwargs):
            client.stage = 'architect_repair'
            return generate_target_layout_attempt(client=client, **kwargs)
        candidate_graph = build_ui_feedback_graph(repair_call, render_controlled_components,
                                                  allow_repair=True)
        with PipelineTrace(batch / 'candidate_trace', {'arm': 'candidate',
                           'shared_first_attempt_sha256': sha256(batch / 'architect_first_attempt.json')}):
            candidate = candidate_graph.invoke(dict(common, model_call_limit=1))
        candidate_dir = batch / 'candidate'; candidate_dir.mkdir()
        write_json(candidate_dir / 'state.json', _clean_graph_result(candidate))
        if candidate.get('final_code'):
            (candidate_dir / 'final_code.html').write_text(candidate['final_code'], encoding='utf-8')
        comparison = {
            'shared_call_count_before_branch': 2,
            'actual_physical_call_count': provider.count,
            'baseline_release_gate': baseline.get('release_gate'),
            'candidate_release_gate': candidate.get('release_gate'),
            'candidate_repair_triggered': len(candidate.get('attempts', [])) == 2,
            'first_attempt_same': baseline['attempts'][0] == candidate['attempts'][0],
            'baseline_error_downstream_deliveries': int(bool(
                baseline.get('final_code') and baseline.get('release_gate', {}).get('status') != 'coordinate_contract_passed')),
            'candidate_error_downstream_deliveries': int(bool(
                candidate.get('final_code') and candidate.get('release_gate', {}).get('status') != 'coordinate_contract_passed')),
            'semantic_correctness_evaluated': False, 'browser_behavior_evaluated': False,
        }
        write_json(batch / 'comparison.json', comparison)
        run.update(status='finished_pending_review', actual_model_calls=provider.count,
                   candidate_repair_triggered=comparison['candidate_repair_triggered'])
    except Exception as exc:
        calls = client.calls if 'client' in locals() else []
        run.update(status='failed', error_type=type(exc).__name__,
                   actual_model_calls=len(calls),
                   usage=[call.get('response', {}).get('usage') for call in calls])
        write_json(batch / 'failure.json', {'error_type': type(exc).__name__})
        raise
    finally:
        calls = client.calls if 'client' in locals() else []
        run.setdefault('actual_model_calls', len(calls))
        run.setdefault('usage', [call.get('response', {}).get('usage') for call in calls])
        run['finished_utc'] = datetime.now(timezone.utc).isoformat()
        _finalize_state(batch, archive_path, state_dir, run)


if __name__ == '__main__':
    main()
