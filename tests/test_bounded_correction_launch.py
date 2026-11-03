"""No-client package/release tests. All input plans are synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from scripts.launch_bounded_plan_correction import NODES, verify_approval, verify_deployment
from src.utils.bounded_plan_correction import MODEL, correction_request
from test_bounded_plan_correction import fixture


def prepared(tmp_path):
    old, v, intent, envelope, request=fixture()
    root=tmp_path/'package';folder=root/'prepared_inputs';folder.mkdir(parents=True)
    answer=json.dumps(old);preview,feedback=correction_request(request,answer,v,intent)
    values={'original_state.json':old,'vision.json':v,'original_request.json':request,
            'correction_request.json':preview,'machine_feedback.json':feedback}
    for name,value in values.items():(folder/name).write_text(json.dumps(value),encoding='utf-8')
    (folder/'original_answer.txt').write_text(answer,encoding='utf-8')
    (folder/'intent.txt').write_text(intent,encoding='utf-8')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    binding=dict(source_run='synthetic_historical',input_sha256={p.name:sha(p) for p in folder.iterdir()})
    (folder/'binding.json').write_text(json.dumps(binding),encoding='utf-8')
    manifest=dict(experiment='historical_answer_once_correction_v1',commit='synthetic_commit',files=[],
                  supporting_files=[{'path':p.relative_to(root).as_posix(),'sha256':sha(p)} for p in folder.iterdir()])
    path=root/'deployment_manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    return root,manifest,binding,sha(path)


def approval(root,manifest,binding,digest):
    return dict(status='APPROVED_NEW_BATCH',commit=manifest['commit'],manifest_sha256=digest,
                input_sha256=copy.deepcopy(binding['input_sha256']),source_run=binding['source_run'],
                nodes=copy.deepcopy(NODES),max_real_requests=2,model=MODEL,deploy_to=str(root),
                run_id='correction002_20261103T000000Z',authorization_source='SYNTHETIC TEST NOT LIVE APPROVAL')


def test_package_binds_preview_inputs_and_raw_answer(tmp_path):
    root,m,b,d=prepared(tmp_path)
    assert verify_deployment(root)==(m,b,d)
    (root/'prepared_inputs/original_answer.txt').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='HASH_MISMATCH'):verify_deployment(root)


@pytest.mark.parametrize('field,value',[
    ('status','PENDING_COORDINATOR_RELEASE'),('commit','other'),('manifest_sha256','other'),
    ('input_sha256',{}),('source_run','other'),('nodes',[]),('max_real_requests',4),
    ('max_real_requests',True),('model','other'),('deploy_to','other'),('run_id','other'),
    ('authorization_source','')])
def test_release_must_match_exact_reviewed_package(tmp_path,field,value):
    root,m,b,d=prepared(tmp_path);record=approval(root,m,b,d)
    verify_approval(record,record['run_id'],root,m,b,d)
    record[field]=value
    with pytest.raises(ValueError):verify_approval(record,'correction002_20261103T000000Z',root,m,b,d)


def test_no_python_optimized_away_launch_guards():
    path=Path(__file__).resolve().parents[1]/'scripts/launch_bounded_plan_correction.py'
    assert 'assert ' not in path.read_text(encoding='utf-8')
