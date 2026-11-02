import copy, json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_region_tree_contract import sample
from test_region_tree_contract_v2 import add_region
from test_region_tree_review_fixes import runner
from src.utils.region_tree_contract import compile_region_tree, RegionStructureError


def test_six_missing_root_exempt_immutable():
    s,v=sample(); first=add_region(s); second=copy.deepcopy(first)
    second.update(id='region_other',order=1);s['region_contract']['regions'].append(second)
    for r in (first,second):
        for f in ('relation_status','order','sizing'):r.pop(f)
    before=copy.deepcopy(s)
    with pytest.raises(RegionStructureError) as caught:compile_region_tree(s,v,'')
    d=caught.value.diagnostics
    assert str(caught.value)=='INVALID_RELATION_STATUS'
    assert len(d)==6 and s==before
    assert {(x['node_id'],x['field']) for x in d}=={(r,f) for r in ('region_group','region_other') for f in ('relation_status','order','sizing')}


def test_prompt_example_same_compiler():
    p=(Path(__file__).resolve().parents[1]/'src/prompts/ui_architect_region_tree_v1.md').read_text(encoding='utf-8')
    s,_=json.JSONDecoder().raw_decode(p[p.index('{'):]);e=s['elements'][0]
    v={'elements':[{k:e[k] for k in ('id','type','text')}]};before=copy.deepcopy(s)
    out=compile_region_tree(s,v,'')
    assert out['region_layout']['children']['region_group']==['original_visual_id'] and s==before
    assert not {'order','sizing','relation_status'} & s['region_contract']['regions'][0].keys()


@pytest.mark.parametrize('invalid',[True,False])
def test_real_entry_details_and_mock_coder(tmp_path,invalid):
    s,v=sample();add_region(s);bad=copy.deepcopy(s);calls=[]
    for f in ('relation_status','order','sizing'):bad['region_contract']['regions'][1].pop(f)
    def transport(arm,node,request):
        calls.append((arm,node));content=json.dumps(bad if invalid and arm=='candidate' else s) if node=='architect' else '<html><body>SYNTHETIC OFFLINE FIXTURE</body></html>'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),finish_reason='stop')])
    out=runner().run_pair(v,'','SYNTHETIC_MODEL',tmp_path/'pair',transport,transport_identity='SYNTHETIC_ZERO_NETWORK')
    t=out['results'][1]
    assert t['html_exists'] is False and t['coder_dispatched'] is (not invalid)
    if invalid:
        assert t['reason']=='ARCHITECT_CONTRACT_FAILED' and t['original_error']=='INVALID_RELATION_STATUS'
        assert t['error_node']=='architect.finalize.region_tree' and len(t['error_details'])==3
        assert calls==[('control','architect'),('control','coder'),('candidate','architect')]
    else:assert t['status']=='PIPELINE_RETURNED_NOT_ACCEPTED' and calls[-1]==('candidate','coder')
