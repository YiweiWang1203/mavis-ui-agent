import copy
from src.utils.bounded_fragment_chains import recruit_fragment_chains


def test_two_hop_limit_preserves_sources_and_input():
    g=dict(lines=[dict(id='s1',orientation='horizontal',endpoints=[10,20,70,20],source_segments=[[10,20,70,20]],source_line_ids=['line_1'])])
    raw=[[71,20,81,20.2],[82,20.2,92,20.5],[93,20.5,99,20.7]];before=copy.deepcopy(g)
    result=recruit_fragment_chains(g,[],raw,100,100)
    assert g==before
    assert result['recruitment_log'][0]['chains'][1]['raw_ids']==['raw_1','raw_2']
    assert result['lines'][0]['source_segments'][-2:]==raw[:2]
    assert 'raw_3' not in result['lines'][0]['source_line_ids']


def test_parallel_neighbor_does_not_bridge_large_gap():
    g=dict(lines=[dict(id='s1',orientation='horizontal',endpoints=[10,20,70,20],source_segments=[[10,20,70,20]],source_line_ids=['line_1'])])
    result=recruit_fragment_chains(g,[],[[71,24,80,24],[90,20,99,20]],100,100)
    assert result['lines']==g['lines'] and result['unique_added_raw_count']==0
