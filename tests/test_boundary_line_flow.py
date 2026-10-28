from scripts.audit_boundary_line_flow import trace_lines


def test_every_raw_line_has_one_decision_and_duplicate_provenance():
    r=trace_lines([[0,0,5,0],[0,0,80,80],[0,20,80,20],[0,21,80,21]],100,100)
    assert r['counts']=={'length':1,'direction':1,'retained':1,'midpoint_duplicate':1}
    assert r['rows'][3]['suppressed_by']=='raw_3'
    assert r['production'][0]['id']=='line_1'


def test_cap_is_recorded_without_losing_raw_rows():
    raw=[[0,i*10,100,i*10] for i in range(26)]
    r=trace_lines(raw,100,300)
    assert len(r['rows'])==26 and len(r['production'])==24
    assert r['counts']=={'retained':24,'direction_cap':2}
