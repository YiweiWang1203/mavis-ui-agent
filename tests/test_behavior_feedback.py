import copy
import json
from pathlib import Path
import pytest
from src.agents.coder import read_coder_prompt, build_coder_user_content
from scripts.run_behavior_feedback_pair import validate_requests, MODEL, PREFIX, EVIDENCE_SEPARATOR

def pair(monkeypatch):
    user=build_coder_user_content({'interaction_groups':[],'elements':[]},'原始口述证据')
    result={}
    for arm,mode in [('control','functional_content_v1'),('candidate','behavior_feedback_v1')]:
        monkeypatch.setenv('UI_CODER_CONTRACT_MODE',mode)
        result[arm]={'model':MODEL,'messages':[{'role':'system','content':read_coder_prompt()},{'role':'user','content':user}],'temperature':.2,'max_tokens':8192}
    return result

def test_real_consumer_resolves_conflict_and_preserves_geometry(monkeypatch):
    r=pair(monkeypatch);validate_requests(r)
    a,b=[r[x]['messages'][0]['content'] for x in ('control','candidate')]
    assert 'Do not add business behavior' in a and 'mock click handler' in a
    assert 'Do not add business behavior' not in b and 'mock click handler' not in b
    geometry=Path('src/prompts/coder_functional_content.md').read_text(encoding='utf-8').splitlines()[1:-1]
    for line in geometry: assert line in b

def test_same_raw_evidence_and_state_required(monkeypatch):
    r=pair(monkeypatch);r['candidate']['messages'][1]['content']+=' extra answer'
    with pytest.raises(ValueError,match='UNEQUAL'):validate_requests(r)

def test_budget_drift_rejected(monkeypatch):
    r=pair(monkeypatch);r['candidate']['max_tokens']=16384
    with pytest.raises(ValueError,match='BUDGET'):validate_requests(r)

def test_prompt_drift_rejected(monkeypatch):
    r=pair(monkeypatch);r['candidate']['messages'][0]['content']+=' rule'
    with pytest.raises(ValueError,match='CONSUMER'):validate_requests(r)

def test_default_request_unchanged_and_evidence_explicit():
    state={'elements':[]};before=copy.deepcopy(state)
    assert build_coder_user_content(state)==PREFIX+json.dumps(state,ensure_ascii=False,indent=2)
    assert build_coder_user_content(state,'raw')==build_coder_user_content(state)+EVIDENCE_SEPARATOR+'raw'
    assert state==before
    with pytest.raises(ValueError):build_coder_user_content(state,'')
