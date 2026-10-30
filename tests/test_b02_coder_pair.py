import copy
import pytest
from scripts.run_b02_coder_pair import compile_candidate, execute
from src.utils.layout_solver import solve_ui_layout


def test_failed_layout_cannot_produce_state_or_reach_request_submission(tmp_path):
    source = {'page_meta': {'page_kind': 'mobile_product_detail',
                           'viewport': {'width': 150, 'height': 812}},
              'elements': [{'id': str(i), 'type': 'text', 'text': 'x',
                            'spatial_info': {'bbox': [i*20,100,i*20+16,120]}}
                           for i in range(4)]}
    frozen = copy.deepcopy(source)
    submitted = []
    with pytest.raises(ValueError, match='product_detail_columns_insufficient_capacity'):
        state = compile_candidate(source, solve_ui_layout)
        submitted.append(state)
    assert submitted == [] and source == frozen
    # No frozen request manifest exists after compilation failed. Execution
    # refuses admission before importing/constructing a provider client.
    with pytest.raises(FileNotFoundError):
        execute(tmp_path/'absent_frozen', tmp_path/'never_started', 'not-approved', tmp_path)
    assert not (tmp_path/'never_started').exists()


def test_mutating_solver_is_rejected():
    def bad_solver(state):
        state['elements'].append({'id':'extra'})
        return state
    with pytest.raises(ValueError, match='SOLVER_MUTATED_SOURCE'):
        compile_candidate({'elements':[]}, bad_solver)
