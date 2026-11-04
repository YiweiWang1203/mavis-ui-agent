import base64
from copy import deepcopy
from io import BytesIO
import json

import pytest
from PIL import Image

from src.service.main_model_runtime import (
    MODEL, NATIVE_HTML_AUTOREVIEW_PROFILE, NATIVE_HTML_RELATION_AUDIT_PROFILE, MainModelRuntime,
)
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


FINDING = {
    "source_requirement": {"source_segment_id": "s1", "subject": "label", "relation": "above",
                           "reference": "value", "scope": "card", "uncertainty": None},
    "observed": {"subject_locator": ".label", "reference_locator": ".value", "scope_locator": ".card",
                 "observed_relation": "below", "evidence_type": "screenshot_visible", "evidence": "The label is below."},
    "aspect": "layout", "verdict": "discrepancy", "explanation": "The vertical order is reversed.",
}


@pytest.mark.parametrize(("variant", "error"), [
    ("valid", None), ("other_aspect", None), ("missing_source", "UNKNOWN_SOURCE"),
    ("bad_quote", "SOURCE_QUOTE"), ("bad_evidence", "literal_error"), ("not_tested", "INCONSISTENT_SOURCE"),
    ("ambiguous", "INCONSISTENT_SOURCE"), ("preserve_conflict", "CONFLICTING_PRESERVE"),
    ("preserve_limit", "too_long"),
])
def test_relation_audit_checks_only_contract_and_frozen_source(tmp_path, variant, error):
    finding = deepcopy(FINDING)
    preserved = {"target_locator": ".label", "aspect": "layout",
                 "evidence_type": "static_dom", "evidence": "The element exists."}
    preserve = []
    if variant == "missing_source":
        finding["source_requirement"]["source_segment_id"] = "s99"
    if variant == "bad_quote":
        finding["source_requirement"]["exact_quote"] = "invented"
    if variant in {"bad_evidence", "not_tested"}:
        finding["observed"]["evidence_type"] = "clicked" if variant == "bad_evidence" else "not_tested"
    if variant == "ambiguous":
        finding["source_requirement"]["uncertainty"] = "Two possible meanings."
    if variant in {"preserve_conflict", "other_aspect", "preserve_limit"}:
        preserve = [preserved | {"aspect": "content" if variant == "other_aspect" else "layout"}]
        if variant == "preserve_limit":
            preserve *= 9
    source = {"original_user_request": "A test", "asr_transcript": "Label above value.\nKeep the card.",
              "target_viewport_hint": [391, 844], "preferred_locale": "en"}
    sketch = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    frozen = {"messages": [{"role": "system", "content": "Original"},
                           {"role": "user", "content": [{"type": "text", "text": json.dumps(source)}, sketch]}]}
    img = BytesIO()
    Image.new("RGB", (5, 7), "white").save(img, format="PNG")
    screenshot = img.getvalue()
    model_html = "<html>Frozen input</html>"
    calls = []

    def dispatch(request, **kwargs):
        calls.append(request)
        return {"ok": True, "response": {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            {"issues": [finding], "preserve": preserve, "uncertainty": []})}}]}}

    with MainModelRuntime(tmp_path / "requests", dispatch, profile=NATIVE_HTML_RELATION_AUDIT_PROFILE):
        if error:
            with pytest.raises(ValueError, match=error):
                run_native_html_autoreview(frozen, model_html, screenshot, relation_audit=True)
        else:
            review = run_native_html_autoreview(frozen, model_html, screenshot, relation_audit=True)
            assert review["resolved_sources"] == [{"text": "Label above value.", "start": 0, "end": 18}]
    assert len(calls) == 1
    request = calls[0]
    assert "price" not in request["messages"][0]["content"].lower()
    text, actual_sketch, actual_shot = request["messages"][1]["content"]
    assert json.loads(text["text"]) == {**source, "initial_html": model_html,
                                        "numbered_asr_segments": {"s1": "Label above value.", "s2": "Keep the card."}}
    assert actual_sketch == sketch
    assert base64.b64decode(actual_shot["image_url"]["url"].split(",")[1]) == screenshot
