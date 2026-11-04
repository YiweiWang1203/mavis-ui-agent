from src.agents.coder import read_coder_prompt


def test_main_coder_placement_contract_is_local_and_legacy_is_unchanged(monkeypatch):
    monkeypatch.setenv("UI_CODER_CONTRACT_MODE", "main_system_v1")
    prompt = read_coder_prompt()
    assert "position:relative" in prompt
    assert "position:absolute;left:109px;top:32px;width:64px;height:30px;box-sizing:border-box" in prompt
    assert "never rely on an external stylesheet" in prompt
    assert "overrides generic template advice" in prompt
    monkeypatch.setenv("UI_CODER_CONTRACT_MODE", "baseline")
    assert "left:109px" not in read_coder_prompt()
