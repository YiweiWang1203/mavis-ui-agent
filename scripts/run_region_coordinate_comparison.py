"""One fresh shared source inventory; paired decimal and native-scale grounding."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_pilot_experiment import load_inputs, write_json, sha256
from scripts.run_generation_comparison import BudgetClient, source_record
from scripts.run_input_audit_comparison import CappedProvider
from scripts.run_source_region_comparison import INVENTORY, GROUND
from src.agents.global_spatial_planner import parse_spatial_response
from src.utils.source_region_slots import inventory_slots, bind_regions, decode_region_coordinates


def main():
    import cv2
    import numpy as np
    from dotenv import load_dotenv
    from openai import OpenAI
    from urllib.parse import urlsplit
    p = argparse.ArgumentParser(); p.add_argument('--case', type=Path, required=True)
    p.add_argument('--output-root', type=Path, required=True); a = p.parse_args()
    inputs = load_inputs(a.case.resolve(), 'M2')
    batch = a.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]); batch.mkdir(parents=True)
    for source in inputs['files'].values(): shutil.copyfile(source, batch/source.name)
    image = cv2.imread(str(inputs['image'])); h, w = image.shape[:2]
    load_dotenv(os.getenv('MAVIS_ENV_FILE') or ROOT/'.env', override=True)
    endpoint = os.getenv('SILICONFLOW_BASE_URL') or os.getenv('VISION_BASE_URL')
    key = os.getenv('SILICONFLOW_API_KEY') or os.getenv('OPENAI_API_KEY'); url = urlsplit(endpoint or '')
    if not key or url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('Existing credentials and credential-free HTTPS endpoint required')
    provider = CappedProvider(OpenAI(api_key=key, base_url=endpoint, max_retries=0, timeout=600), limit=3)
    image_part = {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,'+base64.b64encode(inputs['image'].read_bytes()).decode('ascii')}}
    manifest = {**source_record(), 'status': 'started', 'model': 'Qwen/Qwen3-VL-8B-Instruct',
        'input_sha256': {k: sha256(v) for k,v in inputs['files'].items()},
        'physical_call_cap': 3, 'call_accounting': {'shared_inventory': 1, 'exclusive_per_arm': 1, 'effective_per_arm': 2},
        'max_tokens_per_stage': 8192, 'timeout_seconds': 600, 'max_retries': 0,
        'runtime': {'python': sys.executable, 'version': sys.version, 'cv2': cv2.__file__, 'numpy': np.__file__},
        'html_expected': False, 'limits': 'Region grounding coordinate contract probe; no HTML or user-function scores', 'runs': []}
    write_json(batch/'batch.json', manifest); print('Batch:',batch,flush=True)

    def call(client, stage, system, payload, with_image):
        client.stage = stage
        content = [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}]
        if with_image: content.append(image_part)
        response = client.create(model=manifest['model'], temperature=0, response_format={'type': 'json_object'},
            messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}])
        if response.choices[0].finish_reason != 'stop': raise ValueError('Non-stop response; no retry')
        proposal = parse_spatial_response(response.choices[0].message.content)
        write_json(client.output/(stage+'_proposal.json'), proposal)
        return proposal

    shared = batch/'shared_inventory'; shared.mkdir(); client = BudgetClient(provider, shared)
    try:
        proposal = call(client, 'inventory', INVENTORY, {'transcript': inputs['transcript']}, False)
        slots = inventory_slots(proposal, inputs['transcript']); write_json(shared/'source_slots.json', slots)
        manifest['shared_inventory_sha256'] = sha256(shared/'source_slots.json')
        if not slots:
            manifest['inventory_status'] = 'empty_not_evaluable_no_grounding_calls'
        else:
            manifest['inventory_status'] = 'validated_pending_semantic_review'
            for arm, scale in [('decimal_1',1), ('native_1000',1000)]:
                folder = batch/arm; folder.mkdir(); arm_client = BudgetClient(provider, folder)
                shutil.copyfile(shared/'source_slots.json', folder/'source_slots.json')
                summary = {'arm': arm, 'coordinate_scale': scale, 'status': 'failed', 'shared_inventory_sha256': sha256(folder/'source_slots.json')}
                try:
                    prompt = GROUND if scale == 1 else GROUND.replace('image-normalized', 'Qwen3 native normalized').replace('in 0..1', 'in 0..1000')
                    raw = call(arm_client, 'grounding', prompt, {'immutable_slots': slots, 'image_size': [w,h]}, True)
                    normalized = decode_region_coordinates(raw, scale); write_json(folder/'normalized_bindings.json',normalized)
                    state = bind_regions(slots, normalized); write_json(folder/'region_evidence.json',state)
                    overlay = image.copy()
                    for row in state['regions']:
                        if row['bbox'] is None: continue
                        x0,y0,x1,y1=row['bbox'];lo=(round(x0*w),round(y0*h));hi=(round(x1*w),round(y1*h))
                        cv2.rectangle(overlay,lo,hi,(0,0,255),1);cv2.putText(overlay,row['id'],lo,cv2.FONT_HERSHEY_SIMPLEX,.4,(255,0,0),1)
                    cv2.imwrite(str(folder/'regions_overlay.jpg'),overlay)
                    summary.update(status='compiled_pending_semantic_review',proposed_count=state['proposed_count'],localized_count=state['localized_count'],unresolved_count=state['unresolved_count'])
                except Exception as exc:
                    summary.update(error_type=type(exc).__name__)
                    if isinstance(exc,ValueError): summary['validation_reason']=str(exc)
                summary.update(actual_calls=len(arm_client.calls),total_tokens=sum(c.get('response',{}).get('usage',{}).get('total_tokens',0) for c in arm_client.calls),elapsed_seconds=sum(c['elapsed_seconds'] for c in arm_client.calls))
                write_json(folder/'run_summary.json',summary);manifest['runs'].append(summary)
    except Exception as exc:
        manifest.update(inventory_status='failed_no_grounding_calls',inventory_error_type=type(exc).__name__)
        if isinstance(exc,ValueError): manifest['inventory_validation_reason']=str(exc)
    manifest.update(status='finished_pending_review',physical_calls=provider.count)
    write_json(batch/'batch.json',manifest)
    write_json(batch/'artifact_manifest.json',{x.relative_to(batch).as_posix():sha256(x) for x in batch.rglob('*') if x.is_file() and x.name!='artifact_manifest.json'})


if __name__=='__main__':main()
