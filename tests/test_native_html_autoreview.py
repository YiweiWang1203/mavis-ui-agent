import base64
from io import BytesIO
import json

import pytest
from PIL import Image

from src.service.main_model_runtime import MODEL, NATIVE_HTML_AUTOREVIEW_PROFILE, MainModelRuntime
from src.service.native_html_autoreview import run_native_html_autoreview


ISSUE = {
    "source_quote": "Keep the label visible",
    "target_locator": ".label",
    "observation": "The label is clipped in the initial image.",
    "discrepancy": "Label is not fully visible.",
    "expected": "Show the full label.",
    "confidence": "high",
}


@pytest.mark.parametrize(("issues", "finish", "error"), [
    ([], "stop", None),
    ([ISSUE], "stop", None),
    ([ISSUE | {"source_quote": "invented"}], "stop", "NATIVE_AUTOREVIEW_SOURCE_QUOTE"),
    ([ISSUE | {"patch": "replace()"}], "stop", "extra_forbidden"),
    ([ISSUE] * 9, "stop", "too_long"),
    ([ISSUE], "length", "INCOMPLETE_MODEL_RESPONSE"),
])
def test_bounded_autoreview_only_sends_frozen_initial_evidence(tmp_path, issues, finish, error):
    source = {
        "original_user_request": "Build a test page", "asr_transcript": "Keep the label visible.",
        "target_viewport_hint": [391, 844], "preferred_locale": "en",
    }
    original_image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    original = {"messages": [{"role": "system", "content": "Not a review prompt"},
                             {"role": "user", "content": [
                                 {"type": "text", "text": json.dumps({**source, "untrusted_hint": "never sent"})},
                                 original_image,
                             ]}]}
    image_buffer = BytesIO()
    Image.new("RGB", (5, 7), "white").save(image_buffer, format="JPEG")
    screenshot = image_buffer.getvalue()
    model_html = "<html>Initial document</html>"
    captured = []

    def dispatch(request, *, deadline, diagnostics_directory):
        captured.append(request)
        assert deadline == 600
        return {"ok": True, "response": {"choices": [{
            "finish_reason": finish, "message": {"content": json.dumps({
                "issues": issues, "preserve": [], "uncertainty": [],
            })},
        }]}}

    with MainModelRuntime(tmp_path / "requests", dispatch, profile=NATIVE_HTML_AUTOREVIEW_PROFILE) as runtime:
        with pytest.raises(RuntimeError, match="MAIN_STAGE_ORDER_VIOLATION"):
            runtime.create("direct_coder", model=MODEL)
        if error is None:
            assert run_native_html_autoreview(original, model_html, screenshot)["issues"] == issues
        else:
            with pytest.raises((RuntimeError, ValueError), match=error):
                run_native_html_autoreview(original, model_html, screenshot)
        with pytest.raises(RuntimeError, match="UNAUTHORIZED|PRIOR_REQUEST_FAILED"):
            runtime.create("native_html_review", model=MODEL)
    assert len(captured) == 1
    request = captured[0]
    assert request["model"] == MODEL and request["max_tokens"] == 8192 and request["timeout"] == 600
    assert "price" not in request["messages"][0]["content"].lower()
    text, actual_original, actual_screenshot = request["messages"][1]["content"]
    assert json.loads(text["text"]) == {**source, "initial_html": model_html}
    assert actual_original == original_image
    prefix, content = actual_screenshot["image_url"]["url"].split(",", 1)
    assert prefix == "data:image/jpeg;base64"
    assert base64.b64decode(content, validate=True) == screenshot
