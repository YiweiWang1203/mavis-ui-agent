import copy
from src.utils.spatial_line_retention import spatial_retention


def row(x,y,length=50,orientation='horizontal'):
    return dict(endpoints=[x,y,x+length,y] if orientation=='horizontal' else [x,y,x,y+length],
                length=length,orientation=orientation)


def test_spatial_cells_keep_sparse_evidence_without_exceeding_budget():
    rows=[row(0,i*6,100) for i in range(28)]+[row(600,600,50)]
    before=copy.deepcopy(rows);selected=spatial_retention(rows,800,800)
    assert rows==before and len(selected)==24
    assert any(r['endpoints']==[600,600,650,600] for r in selected)
    assert len({r['id'] for r in selected})==24


def test_near_midpoints_are_suppressed_and_orientation_budgets_separate():
    rows=[row(0,0,50),row(1,1,50)]+[row(i*6,100,50,'vertical') for i in range(27)]
    selected=spatial_retention(rows,800,800)
    assert sum(r['orientation']=='horizontal' for r in selected)==1
    assert sum(r['orientation']=='vertical' for r in selected)==24
