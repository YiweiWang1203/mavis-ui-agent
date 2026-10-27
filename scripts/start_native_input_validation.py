"""Locate existing frozen cases in the original Ubuntu project and launch fresh pairs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def select_cases(project):
    folder = project / 'outputs/pilot_cases'
    cases = []
    for number, pattern in [('002', '002_chat_asr_v1'), ('003', '003_asr_*'), ('008', '008_asr_*')]:
        matches = sorted(p for p in folder.glob(pattern) if (p / 'case.json').is_file())
        if len(matches) != 1:
            raise ValueError(f'{number}: expected exactly one case matching {folder / pattern}; found {len(matches)}. Use run_generation_comparison.py --cases with explicit paths.')
        cases.append(matches[0])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    project = args.project.resolve()
    cases = select_cases(project)
    config = project / '.env'
    if not config.is_file():
        raise ValueError('Original project .env missing; no calls made')
    os.environ['MAVIS_ENV_FILE'] = str(config)
    script = Path(__file__).with_name('run_generation_comparison.py')
    command = [sys.executable, str(script), '--cases', *map(str, cases),
               '--output-root', str(project / 'outputs/optimization_generation')]
    if args.dry_run:
        command.append('--dry-run')
    return subprocess.call(command, cwd=script.parents[1])


if __name__ == '__main__':
    raise SystemExit(main())
