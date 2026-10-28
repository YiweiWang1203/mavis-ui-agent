import pytest
from src.utils.closed_page_candidates import closed_candidates,select_candidate,side_overlap


def line(key,points,orientation):
    return dict(id=key,endpoints=points,orientation=orientation)


def test_rectangle_closes_with_original_source_ids():
    rows=[line('a',[10,10,90,10],'horizontal'),line('b',[10,80,90,80],'horizontal'),
          line('c',[10,10,10,80],'vertical'),line('d',[90,10,90,80],'vertical')]
    p=closed_candidates(rows,100,100)
    assert len(p['candidates'])==1
    assert p['candidates'][0]['quad']==[[10,10],[90,10],[90,80],[10,80]]
    assert set(p['candidates'][0]['side_ids'].values())=={'a','b','c','d'}


def test_line_far_outside_side_is_not_support():
    assert side_overlap([110,0,180,0],[0,0],[100,0])==0


def test_missing_side_does_not_fabricate_closure():
    rows=[line('a',[10,10,90,10],'horizontal'),line('b',[10,80,90,80],'horizontal'),
          line('c',[10,10,10,80],'vertical')]
    assert closed_candidates(rows,100,100)['candidates']==[]


def test_unknown_selection_rejected_and_empty_can_abstain():
    with pytest.raises(ValueError):
        select_candidate({'candidates':[]},{'candidate_id':'made_up','unresolved_reason':None})
    assert select_candidate({'candidates':[]},{'candidate_id':None,'unresolved_reason':'no evidence'})['quad'] is None
