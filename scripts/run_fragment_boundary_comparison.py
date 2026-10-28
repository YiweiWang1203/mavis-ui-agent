"""Fresh same-line comparison: single segments versus observed fragment union and bounded corner extension."""
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_pilot_experiment import load_inputs,write_json,sha256
from scripts.run_generation_comparison import BudgetClient,source_record
from scripts.run_input_audit_comparison import CappedProvider
from src.agents.global_spatial_planner import parse_spatial_response
from src.utils.page_line_boundary import detect_line_candidates,compile_boundary
from src.utils.closed_page_candidates import closed_candidates,select_candidate
from src.utils.fragment_boundary import aggregate_fragments


def main():
    import cv2
    import numpy as np
    from dotenv import load_dotenv
    from openai import OpenAI
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,required=True);parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--comparison',choices=['fragments','retention','identity'],default='fragments')
    args=parser.parse_args();inputs=load_inputs(args.case.resolve(),'M2')
    batch=args.output_root.resolve()/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    image_path=batch/'image.jpg';shutil.copyfile(inputs['image'],image_path)
    image=cv2.imread(str(image_path));h,w=image.shape[:2]
    if args.comparison in {'retention','identity'}:
        from unittest.mock import patch
        raw=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY))[0]
        write_json(batch/'raw_lines.json',[] if raw is None else raw.tolist())
        class FrozenDetector:
            def detect(self,gray):return (raw,)
        with patch.object(cv2,'createLineSegmentDetector',return_value=FrozenDetector()):
            lines=detect_line_candidates(image)
            spatial=detect_line_candidates(image,selection='spatial_v1')
        if any(sum(r['orientation']==o for r in lines)!=sum(r['orientation']==o for r in spatial)
               for o in ['horizontal','vertical']):
            raise ValueError('Retention comparison requires equal actual orientation counts')
        arms={}
        for name,source in [('length_retention',lines),('spatial_retention_v1',spatial)]:
            write_json(batch/(name+'_lines.json'),source)
            support=aggregate_fragments(source,w,h)
            write_json(batch/(name+'_support.json'),support)
            arms[name]=closed_candidates(support['lines'],w,h,fragment_mode=True)
            overlay=image.copy()
            for line in source:
                a=line['endpoints'];cv2.line(overlay,(round(a[0]),round(a[1])),(round(a[2]),round(a[3])),(0,0,255),1)
            cv2.imwrite(str(batch/(name+'_lines_overlay.jpg')),overlay)
        if args.comparison=='identity':
            # Both semantic arms see this one freshly generated candidate state.
            shared=arms['spatial_retention_v1']
            write_json(batch/'shared_identity_candidates.json',shared)
            arms={'free_page_selection':shared,'page_scope_v1':shared}
    else:
        lines=detect_line_candidates(image)
        support=aggregate_fragments(lines,w,h);write_json(batch/'fragment_support.json',support)
        arms={'single_segment_boundary':closed_candidates(lines,w,h),
              'fragment_union_boundary':closed_candidates(support['lines'],w,h,fragment_mode=True)}
    write_json(batch/'line_candidates.json',lines)
    for arm,proposals in arms.items():
        write_json(batch/(arm+'_candidates.json'),proposals)
        tiles=[]
        for r in proposals['candidates']:
            tile=image.copy();cv2.polylines(tile,[np.round(np.array(r['quad'])).astype(np.int32)],True,(0,0,255),2)
            tile=cv2.resize(tile,(203,360));cv2.putText(tile,r['id'],(3,20),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,255),1);tiles.append(tile)
        if tiles:
            while len(tiles)%4:tiles.append(np.full((360,203,3),255,dtype=np.uint8))
            sheet=np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)])
            cv2.imwrite(str(batch/(arm+'_sheet.jpg')),sheet)
    annotated=image.copy()
    for line in lines:
        a=line['endpoints'];p=(round(a[0]),round(a[1]));q=(round(a[2]),round(a[3]))
        cv2.line(annotated,p,q,(0,0,255),1)
        cv2.putText(annotated,line['id'],((p[0]+q[0])//2,(p[1]+q[1])//2),cv2.FONT_HERSHEY_SIMPLEX,.3,(255,0,0),1)
    cv2.imwrite(str(batch/'line_overlay.jpg'),annotated)
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env',override=True)
    endpoint=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    key=os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    from urllib.parse import urlsplit
    url=urlsplit(endpoint or '')
    if not key or url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credential-free HTTPS endpoint required')
    provider=CappedProvider(OpenAI(api_key=key,base_url=endpoint,max_retries=0,timeout=600),limit=2)
    model='Qwen/Qwen3-VL-8B-Instruct';provenance=source_record()
    intent=inputs['prompt']+'\n'+inputs['transcript']
    def image_part(path):return {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii')}}
    manifest=dict(provenance,status='started',generation_kind='fresh_boundary_only_comparison',runs=[],
        input_sha256={k:sha256(v) for k,v in inputs['files'].items()},comparison=args.comparison,max_calls=2,model=model,empty_candidate_precondition='Skip equally for both groups; no semantic score when no candidates',
        runtime={'python_executable':sys.executable,'python_version':sys.version,'cv2_path':cv2.__file__,'numpy_path':np.__file__},
        max_tokens_per_stage=8192,timeout_seconds=600,max_retries=0,
        limits='Boundary localization only; no HTML, task functionality or whole-layout improvement scores.')
    write_json(batch/'batch.json',manifest)
    print('Batch:',batch,flush=True)
    for arm,proposals in arms.items():
        out=batch/arm;out.mkdir();client=BudgetClient(provider,out);client.stage=arm
        summary=dict(model=model,status='failed',html_expected=False,behavior_evaluated=False)
        common='Locate the OUTER HAND-DRAWN UI PAGE, not paper, desk, photo border, sidebar or input box. Portrait photograph can contain landscape desktop page. Observe original image; do not assume whole-image bounds. If uncertain return unresolved, never invent closure. No elements or regions in this call. '
        prompt=common+'Choose exactly one proposed closed quadrilateral that is the outer HAND-DRAWN UI PAGE. Red quadrilaterals are geometry proposals, not answers; ranking does not prove identity. Reject paper/table edges and smaller internal regions. Never invent or edit coordinates or combine candidates. Return only {"candidate_id":"page_candidate_N","unresolved_reason":null}, or candidate_id:null with a concrete reason if none is correct. First image original; second contact sheet of proposals.'
        if arm=='page_scope_v1':
            prompt=common+('Evaluate the SCOPE of every candidate before selecting. A closed sidebar, message box, input box or subregion is not the page. '
                'Compare the original image and all quadrilaterals. For each candidate identify any visible major UI content outside it. '
                'No candidate containing only one region may be selected as the whole page. Paper and table are different targets. '
                'Return {"candidate_id":string|null,"unresolved_reason":string|null,"assessments":['
                '{"candidate_id":string,"scope":"whole_ui_page|internal_region|paper_or_background|uncertain",'
                '"outside_ui_evidence":["describe actual visible UI outside this candidate, or empty if none"],'
                '"boundary_evidence":"describe its visible boundary and why it belongs to this scope"}]}. '
                'Assess every supplied ID exactly once. Select only whole_ui_page with empty outside_ui_evidence. '
                'If no full-page candidate exists, candidate_id:null and explain; do not choose the least bad candidate. '
                'Do not edit coordinates, create a new ID or infer hidden lines. First image original; second candidate sheet.')
        compact=[{k:r[k] for k in ['id','side_ids','area_fraction','projected_support']} for r in proposals['candidates']]
        content=[{'type':'text','text':json.dumps({'intent':intent,'image_size':[w,h],'candidates':compact},ensure_ascii=False)},image_part(image_path)]
        if compact:content.append(image_part(batch/(arm+'_sheet.jpg')))
        try:
            if not compact:
                declaration={'candidate_id':None,'unresolved_reason':'No geometrically supported candidate; model call skipped'}
            else:
                response=client.chat.completions.create(model=model,temperature=0,max_tokens=8192,timeout=600,
                    response_format={'type':'json_object'},messages=[{'role':'system','content':prompt},{'role':'user','content':content}])
                if response.choices[0].finish_reason=='length':raise ValueError('Truncated; no retry')
                declaration=parse_spatial_response(response.choices[0].message.content)
            write_json(out/'proposal.json',declaration)
            if arm=='page_scope_v1':
                from src.utils.page_scope_contract import select_with_scope
                result=select_with_scope(proposals,declaration)
            else:
                result=select_candidate(proposals,declaration)
            write_json(out/'boundary.json',result);summary['status']=result['status']
            if result.get('quad'):
                preview=image.copy();quad=np.array(result['quad'],dtype=np.float32)
                cv2.polylines(preview,[np.round(quad).astype(np.int32)],True,(0,0,255),2)
                cv2.imwrite(str(out/'boundary_overlay.jpg'),preview)
                # Diagnostic page mapping, not a generated UI or perspective-accuracy assertion.
                dst=np.array([[0,0],[1439,0],[1439,899],[0,899]],dtype=np.float32)
                mapped=cv2.warpPerspective(image,cv2.getPerspectiveTransform(quad,dst),(1440,900))
                cv2.imwrite(str(out/'mapped_page_1440x900.jpg'),mapped)
        except Exception as error:
            write_json(out/'failure.json',{'error_type':type(error).__name__,'reason':str(error)})
        summary.update(call_count=len(client.calls),usage=[c.get('response',{}).get('usage') for c in client.calls],
            artifact_sha256={p.relative_to(out).as_posix():sha256(p) for p in out.rglob('*') if p.is_file() and p.name!='run_summary.json'})
        write_json(out/'run_summary.json',summary);manifest['runs'].append({'folder':str(out),'status':summary['status']})
    manifest.update(status='boundary_experiment_finished_pending_visual_review',actual_total_calls=provider.count,
        artifact_sha256={p.relative_to(batch).as_posix():sha256(p) for p in batch.rglob('*') if p.is_file() and p.name!='batch.json'})
    write_json(batch/'batch.json',manifest);shutil.make_archive(str(batch),'zip',root_dir=batch)
    print('Evidence ZIP:',batch.with_suffix('.zip'),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
