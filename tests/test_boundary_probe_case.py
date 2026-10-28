import pytest
from scripts.launch_fragment_boundary_probe import resolve_probe_case


def test_only_existing_case_directory_is_allowed(tmp_path):
    case=tmp_path/'outputs/pilot_cases/mobile_008';case.mkdir(parents=True);(case/'case.json').write_text('{}')
    assert resolve_probe_case(tmp_path,'mobile_008')==case
    for name in ['../mobile_008','mobile/008','missing','.','/tmp/case']:
        with pytest.raises(ValueError):resolve_probe_case(tmp_path,name)
