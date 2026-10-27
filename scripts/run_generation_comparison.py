"""Fresh end-to-end M2 pairs; never reads saved HTML or annotation answers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_pilot_experiment import TracedClient, execute, load_inputs, write_json, sha256


class BudgetClient(TracedClient):
    def create(self, **kwargs):
        kwargs.update(max_tokens=8192, timeout=600)
        return super().create(**kwargs)


def artifact_status(code, calls):
    choices = calls[-1].get('response', {}).get('choices', []) if calls else []
    reason = choices[0].get('finish_reason') if choices else None
    if any(c.get('response', {}).get('choices', [{}])[0].get('finish_reason') == 'length'
           for c in calls if c.get('response', {}).get('choices')):
        return 'output_truncated', reason
    if not code or not re.search(r'<html\b', code, re.I) or not re.search(r'</html\s*>', code, re.I):
        return 'incomplete_html', reason
    return 'html_generated_pending_browser_validation', reason


def source_record():
    result = {}
    for label, command in [('git_head', ['git', 'rev-parse', 'HEAD']),
                           ('git_status', ['git', 'status', '--porcelain'])]:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        result[label] = proc.stdout.strip()
    paths = [p for folder in ('src', 'scripts') for p in (ROOT / folder).rglob('*')
             if p.is_file() and p.suffix in {'.py', '.md', '.json'}]
    result['source_sha256'] = {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(paths)}
    return result


def run_one(inputs, mode, folder, model, provider, provenance, fusion_mode='exact_id', structure_mode='baseline'):
    folder.mkdir(exist_ok=False)
    summary = dict(provenance, mode=mode, fusion_mode=fusion_mode, structure_mode=structure_mode, condition='M2', model=model, status='started',
                   behavior_evaluated=False, generation_kind='fresh_end_to_end',
                   output_html_repair=False, max_tokens_per_stage=8192,
                   timeout_seconds_per_stage=600, max_retries=0,
                   temperatures={'vision': 0, 'ui_architect': 0.3, 'coder': 0.2})
    write_json(folder / 'run_summary.json', summary)
    traced = BudgetClient(provider, folder)
    start = time.monotonic()
    # Set for each arm, do not inherit an accidental local repair/renderer setting.
    os.environ.update(UI_CODER_CONTRACT_MODE=mode, UI_INPUT_CONTRACT_MODE='off',
                      UI_FUSION_MODE=fusion_mode, UI_STRUCTURE_MODE=structure_mode,
                      UI_RENDERER_MODE='llm', LAYOUT_SOLVER_ENABLED='1',
                      VISION_MODEL=model, CODER_MODEL=model, CODER_PROD_MODEL=model)
    try:
        code = execute(inputs, 'M2', traced, folder, model)
        if isinstance(code, str):
            (folder / 'final_code.html').write_text(code, encoding='utf-8')
        status, reason = artifact_status(code, traced.calls)
        summary.update(status=status, finish_reason=reason)
    except Exception as exc:
        # Do not persist provider exception strings or headers.
        summary.update(status='failed', error_type=type(exc).__name__)
    finally:
        summary.update(elapsed_seconds=time.monotonic() - start,
                       call_count=len(traced.calls),
                       usage=[c.get('response', {}).get('usage') for c in traced.calls])
        for call in traced.calls:
            if call.get('stage') == 'coder' and call.get('response', {}).get('choices'):
                raw = call['response']['choices'][0]['message'].get('content') or ''
                (folder / 'coder_response.txt').write_text(raw, encoding='utf-8')
        summary['artifact_sha256'] = {p.relative_to(folder).as_posix(): sha256(p) for p in folder.rglob('*')
                                     if p.is_file() and p.name != 'run_summary.json'}
        write_json(folder / 'run_summary.json', summary)
        print(f"{mode}: {summary['status']}: {folder}", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', required=True, type=Path)
    parser.add_argument('--model', default='Qwen/Qwen3-VL-8B-Instruct')
    parser.add_argument('--output-root', type=Path, default=Path('outputs/optimization_generation'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--modes',nargs='+',choices=['baseline','native_controls_v1'],
                        default=['baseline','native_controls_v1'],help='Use baseline alone for trace collection, not an optimization comparison')
    parser.add_argument('--fusion-modes', nargs='+', choices=['exact_id', 'source_alignment_v1'],
                        default=['exact_id'], help='Compare a fusion mechanism with identical coder prompts')
    parser.add_argument('--structure-modes', nargs='+', choices=['baseline','hierarchy_v1'], default=['baseline'])
    args = parser.parse_args()
    if len(args.modes)!=len(set(args.modes)):
        parser.error('modes must be unique')
    if len(args.fusion_modes) != len(set(args.fusion_modes)):
        parser.error('fusion modes must be unique')
    if len(args.structure_modes)!=len(set(args.structure_modes)):
        parser.error('structure modes must be unique')
    # Validate every case before creating runs or making calls.
    loaded = [load_inputs(p.resolve(), 'M2') for p in args.cases]
    provenance = source_record()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    batch = args.output_root.resolve() / stamp
    batch.mkdir(parents=True, exist_ok=False)
    frozen = []
    for index, (path, inputs) in enumerate(zip(args.cases, loaded)):
        dest = batch / f'{index + 1:02d}_{path.name}'
        dest.mkdir()
        copied = dict(inputs, files={})
        for key, original in inputs['files'].items():
            target = dest / (key + original.suffix)
            shutil.copyfile(original, target)
            copied['files'][key] = target
            if key == 'image':
                copied['image'] = target
        hashes = {key: sha256(p) for key, p in copied['files'].items()}
        frozen.append((dest, copied, hashes))
    manifest = dict(provenance, status='dry_run_only' if args.dry_run else 'started',
                    model=args.model, call_limit=3 * len(args.modes) * len(args.fusion_modes) * len(args.structure_modes) * len(frozen), modes=args.modes,
                    fusion_modes=args.fusion_modes, structure_modes=args.structure_modes,
                    cases=[{'source_case': str(p.resolve()), 'folder': str(d), 'input_sha256': h}
                           for p, (d, _, h) in zip(args.cases, frozen)], runs=[])
    write_json(batch / 'batch.json', manifest)
    print('Batch:', batch, flush=True)
    if args.dry_run:
        print('Dry run only: inputs frozen, zero model calls.'); return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    # A separate checkout can reuse the existing project configuration without copying secrets.
    config = os.getenv('MAVIS_ENV_FILE')
    if config:
        load_dotenv(config, override=True)
    key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    endpoint = os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    if not key or not endpoint:
        raise ValueError('Existing API key and explicit base URL required; no calls made')
    from urllib.parse import urlsplit
    url = urlsplit(endpoint)
    if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Base URL must be HTTPS without embedded credentials/query')
    os.environ['SILICONFLOW_BASE_URL'] = endpoint
    from openai import OpenAI
    provider = OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=600)
    failed = False
    for index, (dest, inputs, hashes) in enumerate(frozen):
        arms = [(fusion, mode, structure) for fusion in args.fusion_modes for mode in args.modes for structure in args.structure_modes]
        order = arms if index % 2 == 0 else list(reversed(arms))
        for fusion_mode, mode, structure_mode in order:
            if hashes != {k: sha256(p) for k, p in inputs['files'].items()} or source_record() != provenance:
                raise RuntimeError('Inputs or code changed during batch; stopped')
            label = mode if len(args.fusion_modes) == 1 and fusion_mode == 'exact_id' else fusion_mode + '__' + mode
            if len(args.structure_modes)>1 or structure_mode!='baseline':
                label += '__' + structure_mode
            run = run_one(inputs, mode, dest / label, args.model, provider,
                          dict(provenance, input_sha256=hashes, endpoint=endpoint), fusion_mode=fusion_mode, structure_mode=structure_mode)
            manifest['runs'].append({'folder': str(dest / label), 'fusion_mode': fusion_mode, 'structure_mode': structure_mode, 'mode': mode, 'status': run['status']})
            failed |= run['status'] != 'html_generated_pending_browser_validation'
            write_json(batch / 'batch.json', manifest)
    manifest['status'] = 'generation_finished_with_failures' if failed else 'generation_finished_pending_browser_validation'
    archive = batch.with_suffix('.zip')
    manifest['archive'] = str(archive)
    write_json(batch / 'batch.json', manifest)
    shutil.make_archive(str(batch), 'zip', root_dir=batch)
    print('Evidence ZIP:', archive, flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
