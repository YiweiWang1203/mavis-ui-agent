import copy
import pytest
from src.utils.fragment_boundary import union_intervals,support_on_side,aggregate_fragments,validate_fragment_sides
from src.utils.closed_page_candidates import closed_candidates


def row(key,coords,orientation):return dict(id=key,endpoints=coords,orientation=orientation)


def test_union_does_not_double_count_or_fill_gaps():
    assert union_intervals([[0,30],[10,40],[60,100]])==[[0,40],[60,100]]
    r=dict(endpoints=[0,0,100,0],source_segments=[[0,0,40,0],[60,0,100,0]])
    d=support_on_side(r,[0,0],[100,0])
    assert d['fraction']==.8 and d['max_internal_gap']==20


def test_parallel_nearby_frames_not_merged_and_input_unchanged():
    rows=[row('a',[10,10,90,10],'horizontal'),row('b',[10,20,90,20],'horizontal')]
    before=copy.deepcopy(rows);g=aggregate_fragments(rows,100,100)
    assert rows==before
    assert all(len(r['source_line_ids'])==1 for r in g['lines'])


def test_fragment_rectangle_can_close_with_real_support():
    rows=[row('t1',[10,10,48,10],'horizontal'),row('t2',[52,10,90,10],'horizontal'),
          row('b',[10,90,90,90],'horizontal'),row('l',[10,10,10,90],'vertical'),row('r',[90,10,90,90],'vertical')]
    g=aggregate_fragments(rows,100,100)
    result=closed_candidates(g['lines'],100,100,fragment_mode=True)
    assert result['candidates']
    assert any(c['observed_support_details']['top']['fraction']==.95 for c in result['candidates'])


def test_large_corner_extrapolation_rejected():
    rows=[dict(id=k,endpoints=c,source_line_ids=[k],source_segments=[c]) for k,c in
          [('t',[25,10,90,10]),('r',[90,10,90,90]),('b',[10,90,90,90]),('l',[10,10,10,90])]]
    result=dict(quad=[[10,10],[90,10],[90,90],[10,90]],side_ids=dict(top='t',right='r',bottom='b',left='l'))
    with pytest.raises(ValueError,match='Corner extension'):
        validate_fragment_sides(rows,result,100,100)
