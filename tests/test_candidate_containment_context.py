import copy
import pytest
from src.utils.candidate_containment_context import area,convex_intersection,containment_context,shared_candidate_order


def square(x,y,n):return [[x,y],[x+n,y],[x+n,y+n],[x,y+n]]


def test_intersection_winding_partial_overlap_and_disjoint():
    assert area(convex_intersection(square(0,0,10),square(5,0,10)))==pytest.approx(50)
    assert area(convex_intersection(square(0,0,10),list(reversed(square(5,0,10)))) )==pytest.approx(50)
    assert area(convex_intersection(square(0,0,10),square(20,20,10)))==0


def test_context_does_not_prune_or_label_whole_page():
    p=dict(candidates=[dict(id='big',quad=square(0,0,10)),dict(id='small',quad=square(1,1,2))]);old=copy.deepcopy(p)
    c=containment_context(p)
    assert p==old and c['rows'][1]['possible_covering_candidates'][0]['candidate_id']=='big'
    assert c['rows'][0]['possible_covering_candidates']==[]


def test_shared_order_is_input_order_independent_and_preserves_geometry():
    p=dict(candidates=[dict(id='a',quad=square(0,0,10)),dict(id='b',quad=square(20,20,10))])
    a,m=shared_candidate_order(p);b,_=shared_candidate_order(dict(candidates=list(reversed(p['candidates']))))
    assert a==b and len(m)==2 and {json_quad(r) for r in a['candidates']}=={json_quad(r) for r in p['candidates']}


def json_quad(r):return tuple(tuple(p) for p in r['quad'])
