"""Two fresh vision calls isolating photo observation context; no HTML or retries."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_pilot_experiment import load_inputs, write_json, sha256
from scripts.run_generation_comparison import BudgetClient, source_record
from scripts.run_input_audit_comparison import CappedProvider
from src.utils.pipeline_trace import PipelineTrace


def main():
    from dotenv import load_dotenv
    from openai import OpenAI
    from PIL import Image, ImageDraw
    from urllib.parse import urlsplit
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--candidate-mode', choices=['photo_observation_v1'], default='photo_observation_v1')
    args = parser.parse_args()
    inputs = load_inputs(args.case.resolve(), 'M2')
    state = args.state.resolve(); state.mkdir(parents=True, exist_ok=False)
    result = state/'results'; batch = result/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    for key, path in inputs['files'].items():
        shutil.copyfile(path, batch/(key+path.suffix))
    request = inputs['prompt']+'\n目标设备：电脑网页；目标画布1440×900。'
    intent = request+'\n\n[Spoken transcript]\n'+inputs['transcript']
    (batch/'effective_request.txt').write_text(request, encoding='utf-8')
    manifest = {**source_record(), 'status':'running','runs':[], 'candidate_mode':args.candidate_mode,
        'input_sha256':{k:sha256(p) for k,p in inputs['files'].items()},'physical_call_cap':2,
        'max_tokens_per_stage':8192,'timeout_seconds':600,'max_retries':0,'html_generated':False,
        'runtime':{'python':sys.executable,'version':sys.version},
        'scope':'fresh photo observation stage only; no target layout or usability gain inferred'}
    record = {'status':'running','worker_pid':os.getpid(),'head':manifest['git_head'],
        'started_utc':datetime.now(timezone.utc).isoformat(),'result_root':str(result),'actual_batch':str(batch),
        'python_executable':sys.executable,'expected_archive':str(state/'results.zip'),
        'input_sha256':manifest['input_sha256'],'physical_call_cap':2}
    write_json(state/'run.json',record); write_json(batch/'batch.json',manifest)
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env',override=True)
    key=os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY')
    endpoint=os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    url=urlsplit(endpoint or '')
    if not key or url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing configured HTTPS credentials required')
    model='Qwen/Qwen3-VL-8B-Instruct'
    os.environ.update(VISION_MODEL=model,SILICONFLOW_BASE_URL=endpoint)
    provider=CappedProvider(OpenAI(api_key=key,base_url=endpoint,max_retries=0,timeout=600),limit=2)
    spec=importlib.util.spec_from_file_location('native_observation_vision',ROOT/'src/tools/vision_tool.py')
    vision=importlib.util.module_from_spec(spec);spec.loader.exec_module(vision)
    with Image.open(inputs['image']) as img:
        image_url,width,height=vision._encode_image_to_data_url(img.convert('RGB'))
    expected_image_hash=hashlib.sha256(image_url.encode()).hexdigest()
    (batch/'effective_image.jpg').write_bytes(base64.b64decode(image_url.split(',',1)[1]))
    all_calls=[]
    for arm,mode in [('baseline_context','legacy'),('candidate_photo_observation','photo_observation_v1')]:
        folder=batch/arm;folder.mkdir();traced=BudgetClient(provider,folder);traced.stage='vision'
        summary={'status':'not_generated','context_mode':mode,'shared_call_count':0,'exclusive_call_count':1,
            'effective_calls':1,'behavior_evaluated':False,'html_exists':False}
        try:
            with patch.object(vision,'OpenAI',return_value=traced), PipelineTrace(folder/'pipeline_trace',{'context_mode':mode}):
                raw=vision.extract_ui_layout(str(inputs['image']),user_context=intent,context_mode=mode)
                write_json(folder/'vision_raw.json',raw)
                if raw.get('error'):
                    raise ValueError('Vision extraction failed')
                validated,validation=vision.validate_vision_layout(raw,str(inputs['image']))
                write_json(folder/'vision_validated.json',validated)
                write_json(folder/'validation.json',validation.model_dump())
                if not validation.valid:
                    raise ValueError('Vision validation failed')
            if traced.calls[0]['request_image_url_sha256']!=[expected_image_hash]:
                raise ValueError('Vision image differs between arms')
            # A diagnostic overlay, not a generated UI or modified observation.
            overlay=Image.open(batch/'effective_image.jpg').convert('RGB');draw=ImageDraw.Draw(overlay)
            for e in validated['elements']:
                b=e['bbox'];xy=[b['x_min']*width,b['y_min']*height,b['x_max']*width,b['y_max']*height]
                draw.rectangle(xy,outline='red',width=2);draw.text((xy[0],xy[1]),e['id'],fill='blue')
            overlay.save(folder/'observation_overlay.png')
            summary.update(status='observations_generated_pending_geometry_review',element_count=len(validated['elements']))
        except Exception as exc:
            summary.update(status='failed',error_type=type(exc).__name__)
            if isinstance(exc,ValueError):summary['validation_reason']=str(exc)
        all_calls.extend(traced.calls)
        write_json(folder/'run_summary.json',summary);manifest['runs'].append({'folder':str(folder)})
    if len(all_calls)==2:
        systems=[c['request']['messages'][0]['content'] for c in all_calls]
        manifest['system_equal_except_current_time']=re.sub(r'CURRENT_TIME:[^\n]*','CURRENT_TIME:[recorded]',systems[0])==re.sub(r'CURRENT_TIME:[^\n]*','CURRENT_TIME:[recorded]',systems[1])
        if not manifest['system_equal_except_current_time']:
            raise ValueError('Unexpected vision system difference')
    manifest.update(status='finished_pending_review',physical_calls=provider.count,
        total_tokens=sum(c.get('response',{}).get('usage',{}).get('total_tokens',0) for c in all_calls),
        request_elapsed_seconds=sum(c['elapsed_seconds'] for c in all_calls),
        same_image_url_sha256=expected_image_hash,finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(batch/'batch.json',manifest)
    write_json(batch/'artifact_manifest.json',{p.relative_to(batch).as_posix():sha256(p) for p in batch.rglob('*') if p.is_file() and p.name!='artifact_manifest.json'})
    archive=Path(shutil.make_archive(str(result),'zip',root_dir=result))
    record.update(status='finished_pending_review',finished_utc=manifest['finished_utc'],physical_calls=provider.count,
        archive=str(archive),archive_sha256=sha256(archive))
    write_json(state/'run.json',record);print(json.dumps(record),flush=True)


if __name__=='__main__':
    main()
