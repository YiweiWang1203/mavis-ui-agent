import copy
from collections import Counter
from scripts.audit_boundary_closure_flow import trace_combinations
from src.utils.closed_page_candidates import closed_candidates


def fixture():
    segments=[('horizontal',[10,10,90,10]),('horizontal',[10,90,90,90]),('vertical',[10,10,10,90]),('vertical',[90,10,90,90])]
    return [dict(id=str(i),orientation=o,endpoints=s,source_segments=[s[:]],source_line_ids=['raw_'+str(i)]) for i,(o,s) in enumerate(segments)]


def test_accepted_trace_matches_production_without_mutation():
    lines=fixture();before=copy.deepcopy(lines);rows=list(trace_combinations(lines,100,100))
    assert lines==before and len(rows)==1 and rows[0]['first_rejection'] is None
    assert rows[0]['outside_distances']==[0,0,0,0]
    assert closed_candidates(lines,100,100,fragment_mode=True)['valid_combinations']==1


def test_rejected_trace_keeps_observable_intersections():
    lines=fixture();lines[-1]['endpoints']=[110,10,110,90];lines[-1]['source_segments']=[[110,10,110,90]]
    rows=list(trace_combinations(lines,100,100));production=closed_candidates(lines,100,100,fragment_mode=True)
    counts=Counter(r['first_rejection'] for r in rows)
    assert dict(counts)==production['rejection_reasons']
    assert rows[0]['quad'][1][0]==110 and rows[0]['outside_distances'][1]>0
