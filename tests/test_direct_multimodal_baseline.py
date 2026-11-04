import base64
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from src.service.direct_multimodal_baseline import save_direct_html
from src.service.main_model_runtime import DIRECT_MULTIMODAL_PROFILE, MODEL, MainModelRuntime
from src.service.main_ui_workflow import run_main_video


HTML = '<!doctype html>\n<html lang="en"><head><title>Example</title></head><body><input></body></html>\n'
FENCED = "```html\n" + HTML + "\n```"


@pytest.mark.parametrize(("finish", "reply", "success"), [
    ("stop", HTML, True),
    ("length", HTML[:-9], False),
    ("stop", HTML[:-9], False),
    ("stop", FENCED, True),
])
def test_video_service_dispatches_frame_and_saves_only_complete_html(tmp_path, monkeypatch, finish, reply, success):
    from src.service import input_adapter, main_model_runtime, main_ui_workflow

    video = tmp_path / "video.mp4"
    video.write_bytes(b"test video identity")
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (5, 7), "#263a6b").save(frame)
    source = frame.read_bytes()
    transcript = "保留完整口述。\n  Keep the whitespace.  "
    original_request = "Build the requested UI."
    output = tmp_path / "run"
    calls = []

    def preprocess(**kwargs):
        assert kwargs["video_path"] == video
        assert kwargs["image_path"] is None
        assert kwargs["enable_asr"] is True
        assert kwargs["vision_image_mode"] == "recognition"
        return {
            "recognition_image_path": str(frame), "selected_source": "video_preprocessed_sketch",
            "vision_image_mode": "recognition", "state": {
                "image_path": str(frame), "asr_transcript": transcript, "original_user_request": original_request,
                "preprocess_platform_hint": {"target_size": {"width": 800, "height": 600}},
                "preferred_locale": "zh-CN",
            },
        }

    def dispatch(request, *, deadline, diagnostics_directory):
        calls.append(request)
        assert deadline == 600
        assert request["model"] == MODEL
        assert request["max_tokens"] == 8192 and request["timeout"] == 600
        assert "response_format" not in request
        text, image = request["messages"][1]["content"]
        assert json.loads(text["text"]) == {
            "asr_transcript": transcript, "original_user_request": original_request,
            "target_viewport_hint": {"width": 800, "height": 600}, "preferred_locale": "zh-CN",
        }
        scheme, encoded = image["image_url"]["url"].split(",", 1)
        assert scheme == "data:image/jpeg;base64"
        assert base64.b64decode(encoded, validate=True) == source
        return {"ok": True, "response": {"choices": [{"finish_reason": finish, "message": {"content": reply}}]}}

    monkeypatch.setattr(input_adapter, "prepare_workflow_input", preprocess)
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
    monkeypatch.setattr(main_model_runtime, "isolated_sdk_call", dispatch)
    monkeypatch.setattr(main_ui_workflow.subprocess, "check_output", lambda args, **kwargs: "commit\n" if args[1] == "rev-parse" else "")
    result = run_main_video(video_path=video, user_prompt=original_request, output_dir=output, run_id="offline",
                            direct_multimodal_baseline=True)
    assert len(calls) == 1
    assert result["config"]["runtime_profile"] == DIRECT_MULTIMODAL_PROFILE
    assert result["model_calls"] == ["direct_coder"]
    assert result["html_generated"] is success
    assert (output / "final.html").exists() is success
    if success:
        assert (output / "final.html").read_bytes() == HTML.encode("utf-8")
        assert result["input_frame"]["sha256"] == hashlib.sha256(source).hexdigest()
        assert result["html_contract_scope"] == "document_boundary"
    request = json.loads((output / "requests/direct_coder_request.json").read_text(encoding="utf-8"))
    assert request == calls[0]
    raw = json.loads((output / "requests/direct_coder_response.json").read_text(encoding="utf-8"))
    assert raw["response"]["choices"][0]["message"]["content"] == reply
    terminal = json.loads((output / "requests/direct_coder_terminal.json").read_text(encoding="utf-8"))
    assert terminal["finish_reason"] == finish
    assert terminal["automatic_retries"] == 0


def test_direct_profile_excludes_other_stages_and_second_request(tmp_path):
    calls = []

    def dispatch(request, **kwargs):
        calls.append(request)
        return {"ok": True, "response": {"choices": [{"finish_reason": "stop", "message": {"content": HTML}}]}}

    with MainModelRuntime(tmp_path / "requests", dispatch, profile=DIRECT_MULTIMODAL_PROFILE) as runtime:
        for stage in ("vision", "architect", "coder", "semantic_audit"):
            with pytest.raises(RuntimeError, match="MAIN_STAGE_ORDER_VIOLATION"):
                runtime.create(stage, model=MODEL)
        runtime.create("direct_coder", model=MODEL)
        with pytest.raises(RuntimeError, match="MAIN_STAGE_ALREADY_CONSUMED_OR_UNAUTHORIZED"):
            runtime.create("direct_coder", model=MODEL)
    assert len(calls) == 1


def test_exact_envelope_bytes_and_offsets(tmp_path):
    html = HTML.replace("Example", "页面").replace("\n", "\r\n")
    raw = " \n```HTML\t\r\n" + html + "\r\n```\t\n"
    result = save_direct_html(raw, "stop", tmp_path)
    actual = (tmp_path / "final.html").read_bytes()
    assert actual == html.encode("utf-8")
    assert actual == raw.encode("utf-8")[result["response_utf8_start"]:result["response_utf8_end"]]
    assert result["response_envelope"] == "single_html_fence"


@pytest.mark.parametrize(("raw", "finish"), [
    (FENCED, "length"), (FENCED + "\n" + FENCED, "stop"),
    ("Here is the page.\n" + FENCED, "stop"), (FENCED + "\nA note.", "stop"),
    (FENCED[:-3], "stop"), (FENCED.replace("</body>", ""), "stop"),
    (FENCED.replace("```html", "```xml"), "stop"),
    (FENCED.replace("<input>", "<!--\n```\n-->"), "stop"),
])
def test_rejects_incomplete_and_ambiguous_envelopes(tmp_path, raw, finish):
    with pytest.raises(ValueError, match="DIRECT_BASELINE_"):
        save_direct_html(raw, finish, tmp_path)
    assert not (tmp_path / "final.html").exists()
