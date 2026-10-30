import copy
import json
import pytest
from scripts.run_preserve_target_pair import validate_requests, validate_extension, MODEL, PREFIX, sha


def requests():
    r={'model':MODEL,'messages':[{'role':'system','content':'frozen'},{'role':'user','content':PREFIX+'{}'}],
       'temperature':.2,'max_tokens':8192}
    return {'control':r,'candidate':copy.deepcopy(r)}


def test_shared_request_contract():
    r=requests(); validate_requests(r)
    r['candidate']['messages'][0]['content']='changed'
    with pytest.raises(ValueError,match='SYSTEM_MESSAGE_CHANGED'):validate_requests(r)


@pytest.mark.parametrize('field,value',[('model','other'),('max_tokens',16384),('temperature',.3)])
def test_budget_cannot_expand(field,value):
    r=requests();r['candidate'][field]=value
    with pytest.raises(ValueError):validate_requests(r)


def test_002_requires_c_and_coordinator(tmp_path):
    validate_extension('001')
    with pytest.raises(ValueError): validate_extension('002')
    p=tmp_path/'gate.json'
    gate={'allow_002_pair':True,'net_layout_improvement':True,'input_regression':False,
          'c_browser_evidence':'independent report'}
    p.write_text(json.dumps(gate))
    with pytest.raises(ValueError):validate_extension('002',p,sha(p))
    gate.update(coordinator_approved_002=True,coordinator_approval_evidence='explicit approval after B/C')
    p.write_text(json.dumps(gate));validate_extension('002',p,sha(p))
