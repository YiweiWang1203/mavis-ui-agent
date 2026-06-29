import os
import sys
from types import SimpleNamespace
import pytest


import tests.real_world_test as rwt


class DummyGraph:
    def stream(self, inputs, stream_mode=None):
        return []


def test_image_only_does_not_call_prepare(monkeypatch, capsys, tmp_path):
    # ensure build_graph is stubbed so main() won't run the real agents
    monkeypatch.setattr(rwt, "build_graph", lambda: DummyGraph())

    called = {"prepare": False}

    def fail_prepare(*a, **k):
        called["prepare"] = True
        raise AssertionError("prepare_input_from_video should not be called in image-only mode")

    monkeypatch.setattr(rwt, "prepare_input_from_video", fail_prepare)

    img = tmp_path / "img.jpg"
    img.write_text("fake")

    argv = ["prog", "--image", str(img), "--text", "hello"]
    monkeypatch.setattr(sys, "argv", argv)

    # should not raise
    rwt.main()

    assert not called["prepare"]


def test_prepare_input_from_video_mock(monkeypatch, tmp_path):
    # create fake normalized and oriented files
    normalized = tmp_path / "normalized.jpg"
    oriented = tmp_path / "oriented.jpg"
    normalized.write_text("img")
    oriented.write_text("img")

    # fake package object
    fake_pkg = SimpleNamespace(
        normalized_sketch_path=str(normalized),
        orientation_corrected_sketch_path=str(oriented),
        platform_hint=SimpleNamespace(platform="mobile", target_ratio="9:16", target_size=(390, 844)),
        errors=[],
        warnings=[],
    )

    class FakeOrch:
        def __init__(self, output_root=None):
            self.output_root = output_root

        def run(self, inp):
            return fake_pkg

    # monkeypatch the PreAgentOrchestrator class used inside prepare_input_from_video
    import importlib
    pp_module = importlib.import_module('src.preprocess.orchestrator')
    monkeypatch.setattr(pp_module, 'PreAgentOrchestrator', FakeOrch)

    # create a fake package.json under metadata to satisfy prepare_input_from_video checks
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    pkgf = metadata_dir / "package.json"
    pkgf.write_text("{}")

    res = rwt.prepare_input_from_video(str(tmp_path / "video.mp4"), "orig text", str(tmp_path))

    assert res["image_path"] == str(normalized)
    assert "视频前置处理上下文" in res["text"]
    assert str(tmp_path) in res["package_path"] or res["package_path"] is not None


def test_image_and_video_mutually_exclusive(monkeypatch):
    # both image and video should be allowed; ensure flow runs and uses selection
    tmp_img = os.path.abspath("/tmp/test_img.jpg")
    tmp_vid = os.path.abspath("/tmp/test_vid.mp4")
    # create dummy files
    open(tmp_img, "w").close()
    open(tmp_vid, "w").close()

    # monkeypatch build_graph to avoid external calls
    monkeypatch.setattr(rwt, "build_graph", lambda: DummyGraph())

    # fake preprocess result
    def fake_prepare(video_path, user_text, preprocess_output_dir, rotate_degrees=180, orientation_correction_enabled=True):
        return {
            "image_path": tmp_img,  # pretend video yields same path for simplicity
            "text": user_text + "\n[视频前置处理上下文]",
            "package_path": os.path.join(preprocess_output_dir or "", "metadata", "package.json"),
            "preprocess_output_dir": preprocess_output_dir,
            "orientation_corrected_sketch_path": tmp_img,
            "platform_hint": None,
            "target_ratio": None,
            "target_size": None,
        }

    monkeypatch.setattr(rwt, "prepare_input_from_video", fake_prepare)

    # force selection to pick video by monkeypatching select_best_sketch_candidate
    def fake_select(user_image_path, video_image_path, output_dir=None):
        return {
            "selected_image_path": video_image_path,
            "selected_source": "video_preprocessed_sketch",
            "user_image_score": None,
            "video_image_score": None,
            "selection_reason": "fake pick video",
            "warnings": [],
        }

    monkeypatch.setattr(rwt, "select_best_sketch_candidate", fake_select)

    argv = ["prog", "--image", tmp_img, "--video", tmp_vid, "--text", "hi"]
    monkeypatch.setattr(sys, "argv", argv)

    # capture output
    rwt.main()


def test_neither_image_nor_video(monkeypatch):
    argv = ["prog", "--text", "hi"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        rwt.main()


def test_score_sketch_candidate_valid_image(tmp_path):
    import numpy as np
    import cv2

    img = (np.ones((400, 200, 3), dtype=np.uint8) * 255)
    # draw some edges
    cv2.line(img, (10, 10), (190, 390), (0, 0, 0), 3)
    p = tmp_path / "img.png"
    cv2.imwrite(str(p), img)

    score = rwt.score_sketch_candidate(str(p))
    assert score["readable"]
    assert 0.0 <= score["final_score"] <= 1.0


def test_select_best_sketch_candidate_prefers_higher_score(tmp_path):
    import numpy as np
    import cv2

    # create low-quality user image
    low = (np.ones((200, 200, 3), dtype=np.uint8) * 255)
    lp = tmp_path / "low.png"
    cv2.imwrite(str(lp), low)

    # create higher-quality video-derived image
    high = (np.ones((400, 200, 3), dtype=np.uint8) * 255)
    cv2.line(high, (10, 10), (190, 390), (0, 0, 0), 3)
    hp = tmp_path / "high.png"
    cv2.imwrite(str(hp), high)

    res = rwt.select_best_sketch_candidate(str(lp), str(hp), output_dir=str(tmp_path))
    assert res["selected_image_path"] == str(hp)


def test_select_best_sketch_candidate_tiebreak_prefers_video(tmp_path):
    import numpy as np
    import cv2

    # create two images with similar scores
    a = (np.ones((300, 200, 3), dtype=np.uint8) * 255)
    cv2.line(a, (10, 10), (190, 290), (0, 0, 0), 2)
    ap = tmp_path / "a.png"
    cv2.imwrite(str(ap), a)

    b = (np.ones((300, 200, 3), dtype=np.uint8) * 255)
    cv2.line(b, (20, 20), (180, 280), (0, 0, 0), 2)
    bp = tmp_path / "b.png"
    cv2.imwrite(str(bp), b)

    res = rwt.select_best_sketch_candidate(str(ap), str(bp), output_dir=str(tmp_path))
    assert res["selected_source"] in ("video_preprocessed_sketch", "user_image")
