"""Artifact-only CLI. Prepares requests but has no API client or transport.

Every output uses exclusive creation, retaining original artifacts. Browser
capture is provided by an external operator/tool and explicitly labeled.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.bounded_correction import initialize, observe, build_correction_request, record_correction_response


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command', required=True)
    init=sub.add_parser('init')
    for arg in ('run-id','request','projection','html','out'):init.add_argument('--'+arg, required=True)
    init.add_argument('--origin',choices=['unverified','historical_diagnostic','fresh_generation'],default='unverified')
    check=sub.add_parser('observe')
    for arg in ('session','envelope','capture-root','out'):check.add_argument('--'+arg, required=True)
    prepare=sub.add_parser('prepare-request')
    for arg in ('session','initial-html','out'):prepare.add_argument('--'+arg, required=True)
    register=sub.add_parser('register-response')
    for arg in ('session','request','initial-html','response','finish-reason','out'):register.add_argument('--'+arg, required=True)
    args=parser.parse_args()
    if args.command=='init':value=initialize(args.run_id, read(args.request), read(args.projection), Path(args.html).read_bytes(),args.origin)
    elif args.command=='observe':value=observe(read(args.session), read(args.envelope), Path(args.capture_root))
    elif args.command=='prepare-request':value={'status':'PREPARED_NOT_SENT_REQUIRES_SEPARATE_AUTHORIZATION', 'request':build_correction_request(read(args.session),Path(args.initial_html).read_bytes()), 'physical_calls':0}
    else:
        prepared=read(args.request)
        value=record_correction_response(read(args.session),prepared.get('request',prepared),Path(args.response).read_bytes(),args.finish_reason,Path(args.initial_html).read_bytes())
    write(args.out,value)
    print(json.dumps({'status':'OFFLINE_ARTIFACT_WRITTEN','physical_calls':0,'phase':value.get('phase',value.get('status'))}))


if __name__=='__main__':main()
