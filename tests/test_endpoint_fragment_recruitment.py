import copy
import pytest
from src.utils.endpoint_fragment_recruitment import recruit_endpoint_fragments


def fixture():
    coords=[10,30,10,90]
    return dict(lines=[dict(id='support_1',endpoints=coords,orientation='vertical',source_line_ids=['line_1'],source_segments=[coords],length=60,observed_union_length=60)]),[dict(endpoints=coords)]


def test_only_observed_short_extension_recruited_and_originals_unchanged():
    support,selected=fixture();before=copy.deepcopy(support)
    r=recruit_endpoint_fragments(support,selected,[[10,20,10,29],[10,90,10,99]],100,100)
    assert support==before and len(r['lines'][0]['source_segments'])==3
    assert r['unique_added_raw_count']==2
    assert r['lines'][0]['endpoints']==pytest.approx([10.0,20.0,10.0,99.0])


def test_distant_parallel_stroke_and_non_short_stroke_not_added():
    support,selected=fixture()
    r=recruit_endpoint_fragments(support,selected,[[20,20,20,29],[10,0,10,25]],100,100)
    assert r['unique_added_raw_count']==0 and r['lines']==support['lines']
