import json

import pytest

from src.service.main_model_runtime import DIRECT_MULTIMODAL_PROFILE, MODEL, MainModelRuntime
from src.service.native_html_localized_repair import REPAIR_INSTRUCTION, run_native_html_localized_repair


HTML = '<!doctype html><html><head></head><body><span data-ui-icon="back"></span><p>initial</p></body></html>'
FROZEN_USER = {"asr_transcript": "口述 full", "original_user_request": "Build UI", "target_viewport_hint": [391, 844]}
FROZEN_IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_production_repair_serializes_frozen_evidence_and_never_retries(tmp_path, finish):
    output = tmp_path / "out"
    output.mkdir()
    requests = []
    feedback = {"target": "test", "observed": "wrong order", "expected": "correct order"}
    request = {"model": MODEL, "temperature": 0.2, "max_tokens": 8192, "timeout": 600, "messages": [
        {"role": "system", "content": "original system"},
        {"role": "user", "content": [{"type": "text", "text": json.dumps(FROZEN_USER)}, FROZEN_IMAGE]},
    ]}
    candidate = HTML.replace("initial", "repaired")

    def dispatch(actual, **kwargs):
        requests.append(actual)
        assert kwargs["deadline"] == 600
        return {"ok": True, "response": {"choices": [
            {"finish_reason": finish, "message": {"content": candidate}}]}}

    with MainModelRuntime(output / "requests", dispatch, profile=DIRECT_MULTIMODAL_PROFILE):
        if finish == "stop":
            result = run_native_html_localized_repair(request, HTML, feedback, output)
            assert result["expanded_icons"] == ["back"]
            assert "repaired" in (output / "final.html").read_text(encoding="utf-8")
        else:
            with pytest.raises(RuntimeError, match="INCOMPLETE_MODEL_RESPONSE"):
                run_native_html_localized_repair(request, HTML, feedback, output)
            assert not (output / "final.html").exists()
    assert len(requests) == 1
    actual = requests[0]
    assert {k: v for k, v in actual.items() if k != "messages"} == {
        k: v for k, v in request.items() if k != "messages"}
    assert actual["messages"][0]["content"] == "original system\n\n" + REPAIR_INSTRUCTION
    text, image = actual["messages"][1]["content"]
    assert image == FROZEN_IMAGE
    assert json.loads(text["text"]) == {**FROZEN_USER, "initial_html": HTML, "human_browser_feedback": feedback}
