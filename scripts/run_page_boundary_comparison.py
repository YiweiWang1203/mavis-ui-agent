"""Two fresh boundary-only calls; no HTML, ASR, element or region generation."""
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


def main():
    import cv2
    import numpy as np
    from dotenv import load_dotenv
    from openai import OpenAI
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,required=True);parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args();inputs=load_inputs(args.case.resolve(),'M2')
    batch=args.output_root.resolve()/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    image_path=batch/'image.jpg';shutil.copyfile(inputs['image'],image_path)
    image=cv2.imread(str(image_path));h,w=image.shape[:2]
    lines=detect_line_candidates(image);write_json(batch/'line_candidates.json',lines)
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
        input_sha256={k:sha256(v) for k,v in inputs['files'].items()},max_calls=2,model=model,
        max_tokens_per_stage=8192,timeout_seconds=600,max_retries=0,
        limits='Boundary localization only; no HTML, task functionality or whole-layout improvement scores.')
    write_json(batch/'batch.json',manifest)
    print('Batch:',batch,flush=True)
    for arm in ['direct_boundary','line_supported_boundary']:
        out=batch/arm;out.mkdir();client=BudgetClient(provider,out);client.stage=arm
        summary=dict(model=model,status='failed',html_expected=False,behavior_evaluated=False)
        common='Locate the OUTER HAND-DRAWN UI PAGE, not paper, desk, photo border, sidebar or input box. Portrait photograph can contain landscape desktop page. Observe original image; do not assume whole-image bounds. If uncertain return unresolved, never invent closure. No elements or regions in this call. '
        if arm=='direct_boundary':
            prompt=common+'Return only {"bbox":[xmin,ymin,xmax,ymax],"unresolved_reason":null}, normalized to full image. If uncertain bbox:null and explain reason.'
            content=[{'type':'text','text':intent},image_part(image_path)]
        else:
            prompt=common+'Choose four distinct observed line IDs for top/right/bottom/left page sides. Code computes intersections, so NEVER generate coordinates. Do not choose paper edges, desk texture or smaller internal boxes. Return only {"side_ids":{"top":"line_N","right":"line_N","bottom":"line_N","left":"line_N"},"unresolved_reason":null}. If no supported complete page, side_ids:null with reason. Original image is first; annotated line-ID overlay second. Long segment extensions or weak side support will be rejected.'
            content=[{'type':'text','text':json.dumps({'intent':intent,'image_size':[w,h],'line_candidates':lines},ensure_ascii=False)},image_part(image_path),image_part(batch/'line_overlay.jpg')]
        try:
            response=client.chat.completions.create(model=model,temperature=0,max_tokens=8192,timeout=600,
                response_format={'type':'json_object'},messages=[{'role':'system','content':prompt},{'role':'user','content':content}])
            if response.choices[0].finish_reason=='length':raise ValueError('Truncated; no retry')
            declaration=parse_spatial_response(response.choices[0].message.content);write_json(out/'proposal.json',declaration)
            if arm=='direct_boundary':
                if set(declaration)!={'bbox','unresolved_reason'}:raise ValueError('Invalid direct boundary schema')
                if declaration['bbox'] is None:result={'status':'unresolved','quad':None,'reason':declaration['unresolved_reason']}
                else:
                    from src.utils.global_spatial_contract import normalized_box
                    b=normalized_box(declaration['bbox']);x1,y1,x2,y2=b
                    result={'status':'candidate_requires_visual_review','bbox':b,'quad':[[x1*w,y1*h],[x2*w,y1*h],[x2*w,y2*h],[x1*w,y2*h]]}
            else:result=compile_boundary(lines,declaration,w,h)
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
