"""Offline only. Read saved planning JSON; never invokes a model or renderer."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.utils.region_plan_diagnostics import diagnose_region_plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('state','vision','intent','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    result=diagnose_region_plan(json.loads(a.state.read_text(encoding='utf-8')),
        json.loads(a.vision.read_text(encoding='utf-8')),a.intent.read_text(encoding='utf-8'))
    with a.out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
