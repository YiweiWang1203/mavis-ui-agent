import ast
import copy
import os
from pathlib import Path
import pytest
from scripts.run_functional_content_pair import validate_requests, MODEL, PREFIX


def requests():
    root=Path(__file__).resolve().parents[1]
    base=(root/'src/prompts/coder.md').read_text(encoding='utf-8')
    contract=(root/'src/prompts/coder_functional_content.md').read_text(encoding='utf-8')
    a={'model':MODEL,'messages':[{'role':'system','content':base},{'role':'user','content':PREFIX+'{"interaction_groups":[]}'}],'temperature':.2,'max_tokens':8192}
    b=copy.deepcopy(a);b['messages'][0]['content']=base+'\n\n'+contract
    return {'control':a,'candidate':b}


def test_only_explicit_prompt_contract_difference():
    r=requests();validate_requests(r)
    r['candidate']['messages'][0]['content']+='wrong'
    with pytest.raises(ValueError):validate_requests(r)


def test_common_annotation_required():
    r=requests();r['candidate']['messages'][1]['content']=PREFIX+'{"interaction_groups":[{}]}'
    with pytest.raises(ValueError):validate_requests(r)


def test_coder_opt_in_prompt_matches_paid_request(monkeypatch):
    root=Path(__file__).resolve().parents[1];p=root/'src/agents/coder.py'
    node=next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='read_coder_prompt')
    env={'Path':Path,'os':os,'__file__':str(p)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),env)
    monkeypatch.setenv('UI_CODER_CONTRACT_MODE','baseline');assert env['read_coder_prompt']()==requests()['control']['messages'][0]['content']
    monkeypatch.setenv('UI_CODER_CONTRACT_MODE','functional_content_v1');assert env['read_coder_prompt']()==requests()['candidate']['messages'][0]['content']
