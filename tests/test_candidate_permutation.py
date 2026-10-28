import copy
import pytest
from src.utils.candidate_permutation import permutation_arms


def test_labels_and_positions_are_independently_changed():
    p={'candidates':[{'id':'c1','quad':[[0,0]],'evidence':'a'},
                     {'id':'c2','quad':[[1,1]],'evidence':'b'},
                     {'id':'c3','quad':[[2,2]],'evidence':'c'}]}
    before=copy.deepcopy(p);arms,maps=permutation_arms(p)
    assert p==before
    assert [r['id'] for r in arms['labels_reverse']['candidates']]==['c3','c2','c1']
    assert [r['quad'] for r in arms['labels_reverse']['candidates']]==[r['quad'] for r in p['candidates']]
    assert arms['order_reverse']['candidates']==list(reversed(p['candidates']))
    for name,arm in arms.items():
        for r in arm['candidates']:
            original=next(x for x in p['candidates'] if x['id']==maps[name][r['id']])
            assert {k:v for k,v in r.items() if k!='id'}=={k:v for k,v in original.items() if k!='id'}


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError):permutation_arms({'candidates':[{'id':'x'},{'id':'x'}]})
