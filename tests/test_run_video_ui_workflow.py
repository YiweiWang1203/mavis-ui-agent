from scripts.run_video_ui_workflow import _apply_locale_override, _summary


def test_apply_locale_override_updates_prompt_and_state():
    prepared = {
        "preferred_locale": "zh-CN",
        "final_prompt": "User request: hi\n\n[PREPROCESS CONTEXT]\npreferred_locale: zh-CN\n[IMAGE]: x.png",
        "state": {
            "preferred_locale": "zh-CN",
            "messages": [{"role": "user", "content": "old"}],
        },
    }

    _apply_locale_override(prepared, "en")

    assert prepared["preferred_locale"] == "en"
    assert prepared["state"]["preferred_locale"] == "en"
    assert "preferred_locale: en" in prepared["final_prompt"]
    assert prepared["state"]["messages"][0]["content"] == prepared["final_prompt"]


def test_summary_reports_final_artifacts():
    prepared = {
        "selected_image_path": "sketch.jpg",
        "selected_source": "video_preprocessed_sketch",
        "audio_path": "audio.wav",
        "package_path": "package.json",
        "preferred_locale": "zh-CN",
    }
    final_state = {
        "vision_status": {"valid": True},
        "ui_state_json": {"page_meta": {}},
        "final_code": "<!DOCTYPE html>",
        "final_code_path": "/tmp/out.html",
    }

    summary = _summary(prepared, final_state, "deterministic")

    assert summary["final_code_present"] is True
    assert summary["final_code_length"] == len("<!DOCTYPE html>")
    assert summary["final_code_path"] == "/tmp/out.html"
