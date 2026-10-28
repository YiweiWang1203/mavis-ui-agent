import pytest
from src.utils.candidate_focus import focus_bounds


def test_window_keeps_every_candidate_and_margin():
    p={'candidates':[{'quad':[[30,40],[50,40],[50,70],[30,70]]},
                     {'quad':[[60,80],[80,80],[80,100],[60,100]]}]}
    assert focus_bounds(p,200,300)==[22,32,88,108]
    assert focus_bounds({'candidates':list(reversed(p['candidates']))},200,300)==[22,32,88,108]


def test_empty_and_edge_cases():
    assert focus_bounds({'candidates':[]},20,30)==[0,0,20,30]
    assert focus_bounds({'candidates':[{'quad':[[0,0],[19,0],[19,29],[0,29]]}]},20,30)==[0,0,20,30]
    with pytest.raises(ValueError):focus_bounds({'candidates':[{'quad':[[20,0]]}]},20,30)
