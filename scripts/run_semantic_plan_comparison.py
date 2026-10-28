"""Fresh shared vision, old architect vs SemanticPagePlan; at most 3 physical calls."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_pilot_experiment import execute, load_inputs, write_json, sha256
from scripts.run_generation_comparison import BudgetClient, source_record
from scripts.run_input_audit_comparison import CappedProvider


def realized_accounting(upstream, candidate, frozen):
    """Attempt counts are not successful stages or known billed tokens."""
    shared = len(upstream) if frozen else min(1, len(upstream))
    baseline = 0 if frozen else max(0, len(upstream) - shared)
    calls = upstream + candidate
    usage_known = all(isinstance(c.get('response', {}).get('usage', {}).get('total_tokens'), int) for c in calls)
    return {'physical_attempts': len(calls), 'returned_calls': sum(c.get('status') == 'returned' for c in calls),
        'shared_attempts': shared, 'baseline_exclusive_attempts': baseline,
        'candidate_exclusive_attempts': len(candidate), 'baseline_effective_attempts': shared + baseline,
        'candidate_effective_attempts': shared + len(candidate),
        'candidate_stage_attempted': bool(candidate), 'usage_complete': usage_known,
        'known_reported_tokens': sum(c.get('response', {}).get('usage', {}).get('total_tokens', 0) or 0 for c in calls),
        'total_tokens_if_known': sum(c['response']['usage']['total_tokens'] for c in calls) if usage_known else None,
        'billing_cost_known': False}


def main():
    from dotenv import load_dotenv
    from openai import OpenAI
    from PIL import Image
    from urllib.parse import urlsplit
    from src.agents.semantic_page_planner import generate_semantic_page_plan
    from src.renderers.controlled_components import render_controlled_components
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--candidate-mode', choices=('semantic-page-v1', 'frozen-regions-v1', 'symbolic-flow-v1', 'symbolic-flat-v1', 'projection-flow-v1'), default='semantic-page-v1')
    args = parser.parse_args()
    projection = args.candidate_mode == 'projection-flow-v1'
    cap = 2 if projection else 3
    inputs = load_inputs(args.case.resolve(), 'M2')
    state_dir = args.state.resolve()
    state_dir.mkdir(parents=True, exist_ok=False)
    results = state_dir / 'results'
    batch = results / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    shared, baseline, candidate = [batch / name for name in ('shared_upstream', 'baseline_absolute', 'candidate_semantic_regions')]
    for directory in (shared, baseline, candidate):
        directory.mkdir()
    for key, path in inputs['files'].items():
        shutil.copyfile(path, batch / (key + path.suffix))
    # Explicit device information already supplied by the human, equal in both arms.
    inputs['prompt'] += '\n目标设备：电脑网页；目标画布1440×900。'
    (batch / 'effective_request.txt').write_text(inputs['prompt'], encoding='utf-8')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    record = {'status': 'running', 'worker_pid': os.getpid(), 'head': revision,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'result_root': str(results),
        'actual_batch': str(batch), 'python_executable': sys.executable,
        'expected_archive': str(state_dir / 'results.zip'), 'physical_call_cap': cap,
        'input_sha256': {k: sha256(v) for k, v in inputs['files'].items()},
        'candidate_mode': args.candidate_mode, 'engineering_only': False, 'behavior_evaluated': False}
    write_json(state_dir / 'run.json', record)
    print(json.dumps(record), flush=True)
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT / '.env', override=True)
    endpoint = os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    url = urlsplit(endpoint or '')
    if not key or url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credential-free HTTPS endpoint and credentials required')
    model = 'Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(SILICONFLOW_BASE_URL=endpoint, VISION_MODEL=model, CODER_MODEL=model, CODER_PROD_MODEL=model,
        UI_STRUCTURE_MODE='hierarchy_v1', UI_FUSION_MODE='source_alignment_v1',
        UI_CODER_CONTRACT_MODE='controlled_components_v1', UI_RENDERER_MODE='controlled_components_v1',
        UI_RELATION_SPECIALIST_MODE='off', UI_RELATION_AGGREGATION_MODE='off', UI_SEMANTIC_TYPE_MODE='off',
        UI_INPUT_SEMANTIC_AUDIT_MODE='off', UI_INPUT_CONTRACT_MODE='off', UI_HIERARCHY_LAYOUT_MODE='baseline',
        LAYOUT_SOLVER_ENABLED='1')
    provider = CappedProvider(OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=600), limit=cap)
    upstream, planned = BudgetClient(provider, shared), BudgetClient(provider, candidate)
    manifest = {**source_record(), 'status': 'started', 'model': model, 'candidate_mode': args.candidate_mode,
        'input_sha256': record['input_sha256'], 'runtime': {'python': sys.executable, 'version': sys.version},
        'call_accounting': {'physical_cap': 3, 'shared_vision': 1, 'baseline_exclusive': 1,
                            'candidate_exclusive': 1, 'effective_each': 2},
        'max_tokens_per_stage': 8192, 'timeout_seconds': 600, 'max_retries': 0,
        'baseline_status': 'not_generated', 'candidate_status': 'not_generated',
        'device_request_added_equally': True, 'output_html_repair': False, 'behavior_evaluated': False}
    if args.candidate_mode in {'frozen-regions-v1', 'symbolic-flow-v1', 'symbolic-flat-v1', 'projection-flow-v1'}:
        manifest['call_accounting'] = {'physical_cap': cap, 'shared_vision_and_architecture': 2,
            'baseline_exclusive': 0, 'candidate_exclusive': 0 if projection else 1, 'baseline_effective': 2, 'candidate_effective': 2 if projection else 3}
    write_json(batch / 'batch.json', manifest)
    try:
        try:
            code = execute(inputs, 'M2', upstream, shared, model)
            if isinstance(code, str) and '<html' in code.lower() and '</html' in code.lower():
                shutil.copyfile(shared / 'ui_state.json', baseline / 'ui_state.json')
                (baseline / 'final_code.html').write_text(code, encoding='utf-8')
                manifest['baseline_status'] = 'html_generated_pending_browser_review'
            else:
                manifest['baseline_status'] = 'generation_failed'
        except Exception as exc:
            manifest['baseline_status'] = 'generation_failed'
            manifest['baseline_error_type'] = type(exc).__name__
            if isinstance(exc, ValueError):
                manifest['baseline_validation_reason'] = str(exc)
        if len(upstream.calls) != 2 or not (shared / 'vision_validated.json').is_file():
            raise ValueError('Two bounded baseline calls and a new validated vision are required')
        vision_path = shared / 'vision_validated.json'
        vision = json.loads(vision_path.read_text(encoding='utf-8'))
        image_path = shared / 'effective_image.jpg'
        image_url = 'data:image/jpeg;base64,' + base64.b64encode(image_path.read_bytes()).decode('ascii')
        image_hash = hashlib.sha256(image_url.encode()).hexdigest()
        if upstream.calls[0]['request_image_url_sha256'] != [image_hash]:
            raise ValueError('Candidate image differs from fresh vision request')
        with Image.open(image_path) as image:
            width, height = image.size
        frame = {'id': 'fresh_frame', 'sha256': sha256(image_path), 'width': width, 'height': height}
        viewport = {'id': 'desktop_target_v1', 'width': 1440, 'height': 900}
        manifest['shared_vision_sha256'] = sha256(vision_path)
        manifest['same_image_url_sha256'] = image_hash
        planned.stage = args.candidate_mode
        if args.candidate_mode in {'frozen-regions-v1', 'symbolic-flow-v1', 'symbolic-flat-v1', 'projection-flow-v1'}:
            from src.agents.frozen_region_planner import generate_frozen_region_plan, frozen_inventory, inventory_hash
            if not (baseline / 'ui_state.json').is_file():
                raise ValueError('Fresh baseline semantic inventory required; no historical fallback')
            baseline_state = json.loads((baseline / 'ui_state.json').read_text(encoding='utf-8'))
            manifest['immutable_inventory_sha256'] = inventory_hash(frozen_inventory(baseline_state))
            planner = generate_frozen_region_plan
            if args.candidate_mode in {'symbolic-flow-v1', 'symbolic-flat-v1'}:
                from src.agents.symbolic_flow_planner import generate_symbolic_flow
                planner = generate_symbolic_flow
            extra = {'flat_program': True} if args.candidate_mode == 'symbolic-flat-v1' else {}
            if projection:
                from src.utils.projection_flow_layout import compile_projection_flow
                state = compile_projection_flow(baseline_state, vision, request=inputs['prompt'], speech=inputs['transcript'], frame=frame, viewport=viewport)
                write_json(candidate / 'projection_diagnostics.json', state['page_meta']['projection_flow'])
                write_json(candidate / 'ui_state.json', state)
            else:
                state = planner(baseline_state, vision, **extra, request=inputs['prompt'], speech=inputs['transcript'],
                    frame=frame, viewport=viewport, image_data_url=image_url, client=planned, model=model, output=candidate)
            manifest['call_accounting'] = {'physical_cap': 3, 'shared_vision_and_architecture': 2,
                'baseline_exclusive': 0, 'candidate_exclusive': 1, 'baseline_effective': 2, 'candidate_effective': 3}
        else:
            state = generate_semantic_page_plan(vision, request=inputs['prompt'], speech=inputs['transcript'],
                frame=frame, viewport=viewport, image_data_url=image_url, client=planned, model=model, output=candidate)
        if len(planned.calls) != (0 if projection else 1):
            raise ValueError('Candidate call count differs from declared mode')
        (candidate / 'final_code.html').write_text(render_controlled_components(state), encoding='utf-8')
        manifest['candidate_status'] = 'html_generated_pending_semantic_and_browser_review'
        manifest['semantic_plan_status'] = state['page_meta'].get('semantic_plan', state['page_meta'].get('frozen_inventory_layout', {}))['status']
        manifest['region_layout_status'] = state['page_meta']['region_layout']['status']
    except Exception as exc:
        manifest['candidate_status'] = 'validation_or_generation_failed' if planned.calls else 'not_evaluated_upstream_failed'
        manifest['candidate_error_type'] = type(exc).__name__
        if isinstance(exc, ValueError):
            manifest['candidate_validation_reason'] = str(exc)
    calls = upstream.calls + planned.calls
    manifest.update(status='finished_pending_review', physical_calls=provider.count,
        total_tokens=sum(c.get('response', {}).get('usage', {}).get('total_tokens', 0) for c in calls),
        request_elapsed_seconds=sum(c['elapsed_seconds'] for c in calls),
        finished_utc=datetime.now(timezone.utc).isoformat(),
        runs=[{'folder': str(baseline)}, {'folder': str(candidate)}])
    frozen = args.candidate_mode in {'frozen-regions-v1', 'symbolic-flow-v1', 'symbolic-flat-v1', 'projection-flow-v1'}
    if projection:
        manifest['call_accounting'] = {'physical_cap': 2, 'shared_vision_and_architecture': 2, 'baseline_exclusive': 0, 'candidate_exclusive': 0, 'baseline_effective': 2, 'candidate_effective': 2}
    manifest['planned_call_accounting'] = manifest['call_accounting']
    manifest['realized_call_accounting'] = realized_accounting(upstream.calls, planned.calls, frozen)
    shared_count = len(upstream.calls) if frozen else min(1, len(upstream.calls))
    for folder, arm, exclusive in [(baseline, 'baseline', 0 if frozen else max(0, len(upstream.calls) - 1)), (candidate, 'candidate', len(planned.calls))]:
        write_json(folder / 'run_summary.json', {'status': manifest[arm + '_status'],
            'shared_vision_sha256': manifest.get('shared_vision_sha256'), 'shared_call_count': shared_count,
            'exclusive_call_count': exclusive, 'effective_calls': shared_count + exclusive,
            'call_counts_are_attempts': True,
            'candidate_stage_attempted': bool(planned.calls),
            'behavior_evaluated': False, 'html_exists': (folder / 'final_code.html').is_file()})
    write_json(batch / 'batch.json', manifest)
    write_json(batch / 'artifact_manifest.json', {p.relative_to(batch).as_posix(): sha256(p)
        for p in batch.rglob('*') if p.is_file() and p.name != 'artifact_manifest.json'})
    archive = Path(shutil.make_archive(str(results), 'zip', root_dir=results))
    record.update(status='finished_pending_review', finished_utc=manifest['finished_utc'],
        physical_calls=provider.count, archive=str(archive), archive_sha256=sha256(archive))
    write_json(state_dir / 'run.json', record)
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
