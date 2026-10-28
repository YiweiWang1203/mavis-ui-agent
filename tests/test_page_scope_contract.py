import pytest
from src.utils.page_scope_contract import select_with_scope


def assessment(scope='internal_region',outside=None):
    return dict(candidate_id='c1',scope=scope,outside_ui_evidence=outside or [],boundary_evidence='visible region boundary')


def test_internal_region_cannot_be_selected_as_whole_page():
    with pytest.raises(ValueError,match='whole-page scope'):
        select_with_scope({'candidates':[{'id':'c1'}]},dict(candidate_id='c1',unresolved_reason=None,assessments=[assessment()]))


def test_visible_outside_content_blocks_even_whole_page_claim():
    with pytest.raises(ValueError,match='whole-page scope'):
        select_with_scope({'candidates':[{'id':'c1'}]},dict(candidate_id='c1',unresolved_reason=None,
            assessments=[assessment('whole_ui_page',['chat panel outside'])]))


def test_rejection_preserves_reason_and_requires_all_candidates_assessed():
    p={'candidates':[{'id':'c1'}]}
    result=select_with_scope(p,dict(candidate_id=None,unresolved_reason='only sidebar',assessments=[assessment()]))
    assert result['status']=='unresolved' and result['quad'] is None
    with pytest.raises(ValueError,match='Missing'):
        select_with_scope(p,dict(candidate_id=None,unresolved_reason='unknown',assessments=[]))
