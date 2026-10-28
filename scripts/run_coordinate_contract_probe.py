"""Bounded, zero-model D1 engineering probe; saves evidence, not page scores."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    results = root / 'results'
    results.mkdir()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    record = {'phase': 'D1-01', 'status': 'running', 'worker_pid': os.getpid(),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'head': revision,
              'result_root': str(results), 'physical_model_calls': 0, 'deep_network_forwards': 0,
              'input_kind': 'synthetic_contract_fixture_not_case_GT',
              'runtime': {'python': sys.executable, 'version': platform.python_version()},
              'user_effect_evaluated': False, 'html_expected': False}
    write(root / 'run.json', record)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'tests.test_coordinate_contract', 'tests.test_hierarchy_contract', 'tests.test_parent_geometry_guard'])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (results / 'tests.log').write_text(stream.getvalue(), encoding='utf-8')
    from tests.test_coordinate_contract import fixture
    from src.utils.hierarchy_contract import build_structure
    state, vision, contract = fixture()
    write(results / 'synthetic_inputs.json', {'state': state, 'vision': vision, 'contract': contract})
    baseline = build_structure(state, vision)
    candidate = build_structure(state, vision, coordinate_contract=contract)
    write(results / 'legacy_structure.json', baseline)
    write(results / 'explicit_structure.json', candidate)
    write(results / 'audit.json', {'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful(),
        'physical_model_calls': 0, 'engineering_only': True, 'user_page_gain': None,
        'legacy_editor_bbox': baseline['elements'][1]['spatial_info']['bbox'],
        'explicit_editor_bbox': candidate['elements'][1]['spatial_info']['bbox'],
        'interpretation': 'Distinct geometry ownership on synthetic fixture; no page-quality claim'})
    write(results / 'runtime.json', record['runtime'])
    source_paths = ['src/utils/hierarchy_contract.py', 'src/utils/coordinate_contract.py',
                    'tests/test_coordinate_contract.py', 'scripts/run_coordinate_contract_probe.py']
    write(results / 'source_sha256.json', {path: digest(ROOT / path) for path in source_paths})
    write(results / 'artifact_manifest.json', {p.relative_to(results).as_posix(): digest(p)
          for p in results.rglob('*') if p.is_file()})
    archive = root / 'results.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(results.rglob('*')):
            if path.is_file():
                zipped.write(path, path.relative_to(results))
    record.update(status='finished_pending_review' if result.wasSuccessful() else 'failed',
                  finished_utc=datetime.now(timezone.utc).isoformat(), tests_run=result.testsRun,
                  archive=str(archive), archive_sha256=digest(archive))
    write(root / 'run.json', record)
    print(json.dumps(record))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
