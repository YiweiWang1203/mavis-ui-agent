"""Record every existing LSD filter decision without changing production detection."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.page_line_boundary import detect_line_candidates


def trace_lines(raw, width, height):
    rows = []
    for i, coords in enumerate(raw):
        x1, y1, x2, y2 = map(float, coords)
        dx, dy = x2-x1, y2-y1
        length = math.hypot(dx, dy)
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180
        orientation = ('horizontal' if min(angle, 180-angle) < 20 else
                       'vertical' if abs(angle-90) < 20 else None)
        reason = ('length' if length < .12*min(width, height) else
                  'direction' if orientation is None else None)
        rows.append(dict(raw_id=f'raw_{i+1}', endpoints=[x1,y1,x2,y2],
                         length=length, angle=angle, orientation=orientation,
                         first_rejection=reason))
    accepted = []
    for row in sorted((r for r in rows if r['first_rejection'] is None),
                      key=lambda r: -r['length']):
        a = row['endpoints']; mid = [(a[0]+a[2])/2, (a[1]+a[3])/2]
        duplicate = next((q for q in accepted if q['orientation']==row['orientation']
            and math.dist(mid, [(q['endpoints'][0]+q['endpoints'][2])/2,
                               (q['endpoints'][1]+q['endpoints'][3])/2]) < 5), None)
        if duplicate is not None:
            row.update(first_rejection='midpoint_duplicate', suppressed_by=duplicate['raw_id'])
        elif sum(q['orientation']==row['orientation'] for q in accepted) >= 24:
            row['first_rejection']='direction_cap'
        else:
            row['production_id']='line_'+str(len(accepted)+1)
            accepted.append(row)
    production = [dict(endpoints=r['endpoints'], length=r['length'],
                       orientation=r['orientation'], id=r['production_id']) for r in accepted]
    return dict(rows=rows, production=production,
        counts=dict(Counter(r['first_rejection'] or 'retained' for r in rows)),
        thresholds=dict(length_min=.12*min(width,height), direction_degrees=20,
                        midpoint_distance=5, cap_per_direction=24),
        limits='Filter accounting only. No page-side labels, semantic correctness or recall.')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import cv2
    import numpy as np
    from scripts.run_pilot_experiment import load_inputs
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    args=p.parse_args(); project=args.project.resolve()
    inputs=load_inputs(project/'outputs/pilot_cases/002_chat_asr_v1','M2')
    cycles=project/'outputs/optimization_cycles'
    state=cycles/('round30_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    lock=cycles/'active_generation.lock'
    with lock.open('x') as f: json.dump({'state':str(state)},f)
    state.mkdir(); result=state/'results';result.mkdir()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    record=dict(round='30',status='running',head=head,checkout=str(ROOT),worker_pid=os.getpid(),
                result_root=str(result),physical_llm_call_budget=0,deep_network_forward_cap=0,
                python_executable=sys.executable,source='fresh frozen-image filter accounting')
    save(state/'run.json',record)
    try:
        image=cv2.imread(str(inputs['image']))
        if image is None: raise ValueError('Frozen image unreadable')
        h,w=image.shape[:2]
        raw=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY))[0]
        rows=[] if raw is None else [list(map(float,r[0])) for r in raw]
        trace=trace_lines(rows,w,h)
        class FrozenDetector:
            def detect(self, gray): return (raw,)
        with patch.object(cv2,'createLineSegmentDetector',return_value=FrozenDetector()):
            production=detect_line_candidates(image)
        if production != trace['production']: raise ValueError('Trace differs from production; no interpretation allowed')
        save(result/'raw_lines.json',rows);save(result/'line_flow.json',trace)
        save(result/'line_candidates.json',production)
        shutil.copyfile(inputs['image'],result/'image.jpg')
        colors={'length':(150,150,150),'direction':(0,165,255),
                'midpoint_duplicate':(255,0,255),'direction_cap':(0,0,255),None:(0,160,0)}
        for stage in ['all','length','direction','midpoint_duplicate','direction_cap','retained']:
            overlay=image.copy()
            subset=[r for r in trace['rows'] if stage=='all' or (r['first_rejection'] or 'retained')==stage]
            for r in subset:
                a=r['endpoints'];a1=(round(a[0]),round(a[1]));a2=(round(a[2]),round(a[3]))
                cv2.line(overlay,a1,a2,colors[r['first_rejection']],1)
                if stage!='all': cv2.putText(overlay,r['raw_id'],a1,cv2.FONT_HERSHEY_SIMPLEX,.22,colors[r['first_rejection']],1)
            cv2.imwrite(str(result/(stage+'_overlay.jpg')),overlay)
        manifest=dict(status='diagnostic_finished_pending_visual_review',generation_kind='fresh_filter_accounting',
            actual_total_calls=0,deep_network_forward_count=0,counts=trace['counts'],production_parity=True,
            input_sha256={k:digest(v) for k,v in inputs['files'].items()},
            runtime=dict(python_executable=sys.executable,python_version=sys.version,cv2_path=cv2.__file__,numpy_path=np.__file__),
            code=head,runs=[],limits=trace['limits'],
            artifact_sha256={p.name:digest(p) for p in result.iterdir() if p.is_file()})
        save(result/'batch.json',manifest)
        archive=Path(shutil.make_archive(str(result),'zip',root_dir=result))
        record.update(status='finished_pending_review',archive=str(archive),archive_sha256=digest(archive))
        print(json.dumps(dict(state=str(state),archive=str(archive),archive_sha256=digest(archive),
                             head=head,worker_pid=os.getpid(),counts=trace['counts']),ensure_ascii=True))
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__,reason=str(exc));raise
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat();save(state/'run.json',record)
        if lock.exists() and json.loads(lock.read_text()).get('state')==str(state): lock.unlink()


if __name__=='__main__':main()
