"""Activate stage snapshots for an existing entrypoint without changing its arguments."""
import argparse
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.utils.pipeline_trace import PipelineTrace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace-dir',required=True,type=Path)
    parser.add_argument('--entry',required=True,type=Path)
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    rest=args.arguments[1:] if args.arguments[:1]==['--'] else args.arguments
    entry=args.entry.resolve()
    # This is a local entrypoint wrapper, not an external code downloader.
    if not entry.is_relative_to(ROOT) or not entry.is_file():
        parser.error('entry must be an existing script in this checkout')
    sys.argv=[str(entry),*rest]
    with PipelineTrace(args.trace_dir,{'entrypoint':str(entry),'kind':'live_workflow_trace'}):
        try:
            runpy.run_path(str(entry),run_name='__main__')
        except SystemExit as exc:
            if exc.code not in (None,0):
                raise
    return 0


if __name__=='__main__':
    raise SystemExit(main())
