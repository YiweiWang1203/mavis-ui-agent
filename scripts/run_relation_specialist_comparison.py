"""Fresh shared vision/planner, then matched relation-only branches; <=3 calls."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_pilot_experiment import execute, load_inputs, write_json, sha256
from scripts.run_generation_comparison import BudgetClient, source_record, artifact_status
from src.utils.pipeline_trace import PipelineTrace


class CappedProvider:
    def __init__(self, provider, limit=3):
        self.provider, self.limit, self.count = provider, limit, 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        if self.count >= self.limit:
            raise RuntimeError('Whole trial model call cap reached')
        self.count += 1
        return self.provider.chat.completions.create(**kwargs)


def persist_arm(folder, state, code, metadata, calls):
    folder.mkdir(exist_ok=True)
    write_json(folder / 'ui_state.json', state)
    if code:
        (folder / 'final_code.html').write_text(code, encoding='utf-8')
    relation = state.get('page_meta', {}).get('relation_evidence')
    status, reason = artifact_status(code, calls)
    summary = dict(metadata, status=status if code else 'failed', finish_reason=reason,
        call_count=len(calls), effective_call_count=metadata['shared_call_count'] + len(calls),
        relation_validation_status=relation.get('validation_status') if relation else None,
        unresolved_relation_count=relation.get('unresolved_count') if relation else None,
        usage=[c.get('response', {}).get('usage') for c in calls],
        source_nodes_edited_by_specialist=False, coder_model_called=False,
        max_tokens_per_stage=8192, timeout_seconds_per_stage=600, max_retries=0,
        generation_kind='fresh_shared_upstream_relation_branches', output_html_repair=False)
    summary['artifact_sha256'] = {p.relative_to(folder).as_posix(): sha256(p) for p in folder.rglob('*') if p.is_file() and p.name != 'run_summary.json'}
    write_json(folder / 'run_summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--specialist-mode', choices=['source_ledger_v1', 'container_slots_v1'], default='source_ledger_v1')
    args = parser.parse_args()
    inputs = load_inputs(args.case.resolve(), 'M2')
    provenance = source_record()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    batch = args.output_root.resolve() / stamp
    dest = batch / ('01_' + args.case.name)
    shared = dest / 'shared_upstream'
    shared.mkdir(parents=True)
    inputs = dict(inputs, files=dict(inputs['files']))
    for key, path in list(inputs['files'].items()):
        target = dest / (key + path.suffix)
        shutil.copyfile(path, target); inputs['files'][key] = target
        if key == 'image':
            inputs['image'] = target
    hashes = {k: sha256(v) for k, v in inputs['files'].items()}
    from dotenv import load_dotenv
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT / '.env', override=True)
    key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    endpoint = os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    from urllib.parse import urlsplit
    url = urlsplit(endpoint or '')
    if not key or url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credentials and credential-free HTTPS base URL required')
    model = 'Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(SILICONFLOW_BASE_URL=endpoint, VISION_MODEL=model, CODER_MODEL=model, CODER_PROD_MODEL=model,
        UI_STRUCTURE_MODE='hierarchy_registry_image_v1', UI_FUSION_MODE='source_alignment_v1',
        UI_CODER_CONTRACT_MODE='controlled_components_v1', UI_RENDERER_MODE='controlled_components_v1',
        UI_RELATION_SPECIALIST_MODE='off', UI_HIERARCHY_LAYOUT_MODE='baseline', UI_INPUT_CONTRACT_MODE='off', LAYOUT_SOLVER_ENABLED='1')
    from openai import OpenAI
    gate = CappedProvider(OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=600))
    client = BudgetClient(gate, shared)
    manifest = dict(provenance, status='started', specialist_mode=args.specialist_mode, call_limit=3, shared_calls=2,
        effective_calls={'baseline': 2, 'relation_specialist': 3},
        budget_note='shared new vision+architect; candidate adds one evidence call; not equal-call arms',
        input_sha256=hashes, runs=[])
    write_json(batch / 'batch.json', manifest)
    print('Batch:', batch, flush=True)
    started = time.monotonic()
    baseline_state = {'error': 'shared_upstream_failed'}; baseline_code = None
    try:
        baseline_code = execute(inputs, 'M2', client, shared, model)
    except Exception as error:
        write_json(shared / 'failure.json', {'error_type': type(error).__name__})
    if (shared / 'ui_state.json').exists():
        baseline_state = json.loads((shared / 'ui_state.json').read_text(encoding='utf-8'))
    shared_elapsed = time.monotonic() - started
    common = dict(provenance, model=model, input_sha256=hashes,
        condition='M2', fusion_mode='source_alignment_v1', structure_mode='hierarchy_registry_image_v1',
        renderer='controlled_components_v1', behavior_evaluated=False,
        shared_request_path=str(shared), shared_call_count=len(client.calls), shared_usage=[c.get('response', {}).get('usage') for c in client.calls],
        shared_elapsed_seconds=shared_elapsed, shared_artifact_sha256={p.relative_to(shared).as_posix():sha256(p) for p in shared.rglob('*') if p.is_file()})
    baseline = persist_arm(dest / 'baseline', baseline_state, baseline_code, dict(common, arm='baseline'), [])
    manifest['runs'].append({'folder': str(dest / 'baseline'), 'status': baseline['status']})
    candidate_folder = dest / 'relation_specialist'; candidate_folder.mkdir()
    candidate_client = BudgetClient(gate, candidate_folder)
    candidate_state = {'error': 'shared_upstream_unavailable'}; candidate_code = None
    candidate_start = time.monotonic()
    try:
        planner = next(c for c in client.calls if c['stage'] == 'ui_architect')
        raw = json.loads(planner['response']['choices'][0]['message']['content'])
        vision = json.loads((shared / 'vision_validated.json').read_text(encoding='utf-8'))
        if hashes != {k:sha256(v) for k,v in inputs['files'].items()} or source_record() != provenance:
            raise RuntimeError('Source or inputs changed during generation')
        from src.agents.relation_specialist import refine_relation_state
        from src.agents.ui_architect import finalize_ui_state
        from src.renderers.controlled_components import render_controlled_components
        intent = inputs['prompt'] + '\n\n[Spoken transcript]\n' + inputs['transcript']
        with PipelineTrace(candidate_folder / 'pipeline_trace', {'entrypoint': 'fresh_shared_upstream_relation_split', 'preprocessing': 'not_executed_frozen_assets'}):
            proposal = refine_relation_state(copy.deepcopy(raw), intent, model, candidate_client, mode=args.specialist_mode)
            if proposal['elements'] != raw['elements']:
                raise RuntimeError('Specialist changed source nodes')
            write_json(candidate_folder / 'specialist_proposal.json', proposal)
            candidate_state = finalize_ui_state(proposal, intent, vision, 'hierarchy_registry_image_v1')
            candidate_code = render_controlled_components(candidate_state)
    except Exception as error:
        candidate_state = {'error': type(error).__name__}
        write_json(candidate_folder / 'failure.json', {'error_type': type(error).__name__})
    candidate = persist_arm(candidate_folder, candidate_state, candidate_code,
        dict(common, arm='relation_specialist', extra_elapsed_seconds=time.monotonic()-candidate_start), candidate_client.calls)
    manifest['runs'].append({'folder': str(candidate_folder), 'status': candidate['status']})
    manifest.update(actual_total_calls=gate.count, shared_actual_calls=len(client.calls), candidate_additional_calls=len(candidate_client.calls),
        status='generation_finished_pending_browser_validation' if baseline_code and candidate_code else 'generation_finished_with_failures')
    write_json(batch / 'batch.json', manifest)
    shutil.make_archive(str(batch), 'zip', root_dir=batch)
    print('Evidence ZIP:', batch.with_suffix('.zip'), flush=True)
    return 0 if baseline_code and candidate_code else 1


if __name__ == '__main__':
    raise SystemExit(main())
