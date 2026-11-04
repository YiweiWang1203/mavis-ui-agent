import base64
import hashlib
import json
import re
import sys
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from PIL import Image

from src.service.direct_multimodal_baseline import ASSET_RULES, DIRECT_ASSET_POLICY, save_direct_html
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
        assert request["messages"][0]["content"].endswith(ASSET_RULES)
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


def test_catalog_expands_only_the_exact_references(tmp_path):
    marker = '<span data-ui-icon="location"></span>'
    html = HTML.replace("<input>", '<button class="x" aria-label="位置">' + marker + "</button><input>")
    result = save_direct_html(html, "stop", tmp_path, compact_assets=True)
    rendered = (tmp_path / "final.html").read_bytes()
    assert rendered.count(b"<svg ") == 1
    assert b'width="1em" height="1em"' in rendered
    assert re.sub(rb"<svg [^>]*>.*?</svg>", b"", rendered) == html.encode("utf-8")
    assert result["expanded_icons"] == ["location"]
    assert result["model_html_sha256"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert result["html_sha256"] == hashlib.sha256(rendered).hexdigest()
    assert DIRECT_ASSET_POLICY in ASSET_RULES


@pytest.mark.parametrize(("markup", "error"), [
    ('<span data-ui-icon="unknown"></span>', "UNKNOWN_ICON"),
    ('<span data-ui-icon="location"><b>x</b></span>', "ICON_REFERENCE"),
    ('<span data-ui-icon="location" onclick="x()"></span>', "ICON_REFERENCE"),
    ('<span data-ui-icon="location">', "ICON_REFERENCE"),
    ('<svg><path d="M0 0"/></svg>', "AUTHORED_VECTOR"),
    ('<style>.icon path{d:"M0 0 0.01 0.02"}</style>', "CSS_VECTOR_DATA"),
    (r'<style>.icon {\64 :path("M0 0")}</style>', "CSS_VECTOR_DATA"),
    ('<img src="data:image/png;base64,A">', "OPAQUE_ASSET"),
    ('<script>let x="<svg></svg>"</script>', "AUTHORED_VECTOR"),
])
def test_catalog_rejects_authored_or_malformed_assets(tmp_path, markup, error):
    with pytest.raises(ValueError, match=error):
        save_direct_html(HTML.replace("<input>", markup), "stop", tmp_path, compact_assets=True)
    assert not (tmp_path / "final.html").exists()


def test_compatibility_preserves_original_css_svg_and_expands_catalog(tmp_path):
    uri = ('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
           'viewBox="0 0 100 100"><path d="M10 10 L90 90 M90 10 L10 90" stroke="%23999" '
           'stroke-width="2" fill="none"/></svg>')
    assert len(uri.encode("utf-8")) == 201
    css = f"<style>.placeholder::before{{background-image:url('{uri}')}}</style>"
    marker = '<span data-ui-icon="back"></span>'
    html = HTML.replace("</head>", css + "</head>").replace("<input>", marker)
    with pytest.raises(ValueError, match="OPAQUE_ASSET"):
        save_direct_html(html, "stop", tmp_path, compact_assets=True)
    result = save_direct_html(html, "stop", tmp_path, allow_bounded_css_svg=True)
    rendered = (tmp_path / "final.html").read_bytes()
    assert css.encode() in rendered
    assert re.sub(rb'<svg width="1em"[^>]*>.*?</svg>', b"", rendered) == html.encode("utf-8")
    assert result["expanded_icons"] == ["back"]
    assert result["asset_compatibility"] == "direct_bounded_css_svg_compatibility_v1"


@pytest.mark.parametrize("markup", [
    '<style>.a{background:url("data:image/svg+xml;base64,PHN2Zz4=")}</style>',
    '<style>.a{background:url("data:image/png,%00")}</style>',
    '<style>.a{background:url("data:image/svg+xml,' + quote('<svg><script>x()</script></svg>') + '")}</style>',
    '<style>.a{background:url("data:image/svg+xml,' + quote('<svg><use href="https://x.test"/></svg>') + '")}</style>',
    '<style>.a{background:url("data:image/svg+xml,' + quote('<svg><desc>' + 'x' * 2050 + '</desc></svg>') + '")}</style>',
    ('<style>.a{background:url("data:image/svg+xml,' + quote('<svg><desc>' + 'x' * 1700 + '</desc></svg>') + '")}</style>') * 5,
    '<img src="data:image/svg+xml,%3Csvg/%3E">',
    '<div style="background:url(data:image/svg+xml,%3Csvg/%3E)"></div>',
    '<script>let x="data:image/svg+xml,%3Csvg/%3E"</script>',
    '<style>.icon path{d:"M0 0 0.01 0.02"}</style>',
])
def test_compatibility_rejects_unbounded_or_out_of_scope_assets(tmp_path, markup):
    with pytest.raises(ValueError, match="SVG_URI|OPAQUE_ASSET|CSS_VECTOR_DATA"):
        save_direct_html(HTML.replace("<input>", markup), "stop", tmp_path, allow_bounded_css_svg=True)
    assert not (tmp_path / "final.html").exists()
