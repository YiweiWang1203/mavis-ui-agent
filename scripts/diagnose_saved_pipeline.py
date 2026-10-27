"""Zero-API reconstruction of deterministic transformations, not generation evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.agents import ui_architect
from src.utils.pipeline_trace import PipelineTrace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    run=args.run.resolve()
    original={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    call=read(run/'call_02.json')
    if call.get('stage')!='ui_architect':
        raise ValueError('Expected recorded architect call_02.json')
    content=call['response']['choices'][0]['message']['content']
    user=next(m['content'] for m in call['request']['messages'] if m['role']=='user')
    intent=user.split('[User Intent]\n',1)[1].split('\n\n[Preferred Locale]',1)[0]
    vision=read(run/'vision_validated.json')
    expected=read(run/'ui_state.json')
    fake=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))]))))
    with PipelineTrace(args.out,{'kind':'diagnostic_reconstruction_not_live_generation',
                                  'source_run':str(run),'new_model_calls':0}) as trace:
        with patch.object(ui_architect,'_get_openai_client',return_value=fake):
            actual=ui_architect.generate_ui_state(intent,vision)
        trace.record('reconstruction.check',matches_recorded_ui_state=actual==expected,
                     limitation='Only deterministic post-architect stages reconstructed; no new HTML generated or repaired.')
    if any(hashlib.sha256(p.read_bytes()).hexdigest()!=h for p,h in original.items()):
        raise RuntimeError('Original evidence changed')
    print(json.dumps({'matches_recorded_ui_state':actual==expected,'new_model_calls':0,'trace':str(args.out.resolve())}))
    return 0 if actual==expected else 1


if __name__=='__main__':
    raise SystemExit(main())
