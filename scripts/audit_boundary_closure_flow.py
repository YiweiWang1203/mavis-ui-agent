"""Fresh closure telemetry with strict parity to the unchanged production rules."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_boundary_line_flow import save,digest
from src.utils.page_line_boundary import detect_line_candidates,compile_boundary,intersection
from src.utils.fragment_boundary import aggregate_fragments,validate_fragment_sides,support_on_side
from src.utils.endpoint_fragment_recruitment import recruit_endpoint_fragments
from src.utils.closed_page_candidates import closed_candidates


def trace_combinations(lines,width,height):
    horizontal=[r for r in lines if r['orientation']=='horizontal']
    vertical=[r for r in lines if r['orientation']=='vertical']
    if len(horizontal)>24 or len(vertical)>24:raise ValueError('Production cap exceeded')
    for hs,vs in itertools.product(itertools.combinations(horizontal,2),itertools.combinations(vertical,2)):
        top,bottom=sorted(hs,key=lambda r:(r['endpoints'][1]+r['endpoints'][3])/2)
        left,right=sorted(vs,key=lambda r:(r['endpoints'][0]+r['endpoints'][2])/2)
        sides=dict(top=top,right=right,bottom=bottom,left=left)
        ids={k:v['id'] for k,v in sides.items()}
        row=dict(side_ids=ids,source_ids={k:v['source_line_ids'] for k,v in sides.items()})
        try:
            q=[intersection(top['endpoints'],left['endpoints']),intersection(top['endpoints'],right['endpoints']),
               intersection(bottom['endpoints'],right['endpoints']),intersection(bottom['endpoints'],left['endpoints'])]
            row['quad']=q
            row['outside_distances']=[max(0,-x,x-width,-y,y-height) for x,y in q]
            row['corners_inside']=[0<=x<width and 0<=y<height for x,y in q]
            crosses=[]
            for i in range(4):
                a,b,c=q[i],q[(i+1)%4],q[(i+2)%4]
                crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
            row['convex']=all(v>0 for v in crosses) or all(v<0 for v in crosses)
            row['ordered']=q[0][1]<q[3][1] and q[1][1]<q[2][1] and q[0][0]<q[1][0]
            row['area_fraction']=abs(sum(q[i][0]*q[(i+1)%4][1]-q[(i+1)%4][0]*q[i][1] for i in range(4)))/2/(width*height)
            row['side_observations']={}
            for i,(role,source) in enumerate(sides.items()):
                a,b=q[i],q[(i+1)%4];length=math.dist(a,b)
                d=support_on_side(source,a,b)
                d.update(side_length=length,extension_cap=min(.12*length,.05*min(width,height)),
                         internal_gap_cap=.15*length,source_span_ratio=math.dist(source['endpoints'][:2],source['endpoints'][2:])/length)
                row['side_observations'][role]=d
        except (ValueError,ZeroDivisionError) as exc:
            row['telemetry_error']=str(exc)
        try:
            result=compile_boundary(lines,dict(side_ids=ids,unresolved_reason=None),width,height)
            result['side_ids']=ids
            validate_fragment_sides(lines,result,width,height)
            row['first_rejection']=None
        except ValueError as exc:
            row['first_rejection']=str(exc)
        yield row


def main():
    import cv2
    import numpy as np
    from scripts.run_pilot_experiment import load_inputs
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);args=p.parse_args()
    project=args.project.resolve();cycles=project/'outputs/optimization_cycles'
    state=cycles/('round34_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    lock=cycles/'active_generation.lock'
    with lock.open('x') as f:json.dump({'state':str(state)},f)
    state.mkdir();out=state/'results';out.mkdir()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    record=dict(round='34',status='running',head=head,checkout=str(ROOT),worker_pid=os.getpid(),result_root=str(out),physical_llm_call_budget=0,deep_network_forward_cap=0,python_executable=sys.executable)
    save(state/'run.json',record)
    try:
        inputs=load_inputs(project/'outputs/pilot_cases/002_chat_asr_v1','M2');image=cv2.imread(str(inputs['image']));h,w=image.shape[:2]
        raw=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY))[0]
        coords=[] if raw is None else [list(map(float,r[0])) for r in raw]
        class FrozenDetector:
            def detect(self,gray):return (raw,)
        with patch.object(cv2,'createLineSegmentDetector',return_value=FrozenDetector()):
            selected=detect_line_candidates(image,selection='spatial_v1')
        original=aggregate_fragments(selected,w,h);recruited=recruit_endpoint_fragments(original,selected,coords,w,h)
        save(out/'raw_lines.json',coords);save(out/'selected_lines.json',selected);shutil.copyfile(inputs['image'],out/'image.jpg')
        summaries={}
        for name,support in [('existing_support',original),('endpoint_recruitment_v1',recruited)]:
            save(out/(name+'_support.json'),support)
            production=closed_candidates(support['lines'],w,h,fragment_mode=True);save(out/(name+'_candidates.json'),production)
            counts=Counter();near=[];n=0
            with (out/(name+'_closure.jsonl')).open('w',encoding='utf-8') as f:
                for row in trace_combinations(support['lines'],w,h):
                    n+=1;counts[row['first_rejection'] or 'accepted']+=1
                    f.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n')
                    if row.get('convex') and row.get('ordered') and row.get('side_observations'):
                        row['diagnostic_rank']=row['area_fraction']*min(d['fraction'] for d in row['side_observations'].values())
                        near.append(row);near=sorted(near,key=lambda r:-r['diagnostic_rank'])[:64]
            expected=dict(production['rejection_reasons'])
            if production['valid_combinations']:expected['accepted']=production['valid_combinations']
            if dict(counts)!=expected:raise ValueError('Closure telemetry differs from production')
            summaries[name]=dict(combinations=n,counts=dict(counts),production_parity=True,candidates=len(production['candidates']))
            save(out/(name+'_near_misses.json'),dict(rows=near,limits='Diagnostic rejected or accepted combinations, not eligible page candidates; no semantic truth labels.'))
        manifest=dict(status='diagnostic_finished_pending_review',actual_total_calls=0,deep_network_forward_count=0,code=head,runs=[],summaries=summaries,
            input_sha256={k:digest(v) for k,v in inputs['files'].items()},runtime=dict(python_executable=sys.executable,python_version=sys.version,cv2_path=cv2.__file__,numpy_path=np.__file__),
            artifact_sha256={p.name:digest(p) for p in out.iterdir() if p.is_file()})
        save(out/'batch.json',manifest);archive=Path(shutil.make_archive(str(out),'zip',root_dir=out));record.update(status='finished_pending_review',archive=str(archive),archive_sha256=digest(archive))
        print(json.dumps(dict(state=str(state),head=head,worker_pid=os.getpid(),archive=str(archive)),ensure_ascii=True))
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__,reason=str(exc));raise
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat();save(state/'run.json',record)
        if lock.exists() and json.loads(lock.read_text()).get('state')==str(state):lock.unlink()


if __name__=='__main__':main()
