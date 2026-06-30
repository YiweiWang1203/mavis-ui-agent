from types import SimpleNamespace

from PIL import Image

from src.service import input_adapter


def test_prepare_workflow_input_from_video(monkeypatch, tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fake video")
    sketch = tmp_path / "normalized.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGB", (390, 844), "white").save(sketch)
    audio.write_bytes(b"fake audio")

    def fake_prepare_input_from_video(**kwargs):
        return {
            "image_path": str(sketch),
            "audio_path": str(audio),
            "text": kwargs["user_text"],
            "package_path": str(tmp_path / "metadata" / "package.json"),
            "platform_hint": {"platform": "mobile", "target_ratio": "9:16"},
            "transcript_text": "",
            "warnings": ["ffmpeg_audio_mocked"],
            "errors": [],
        }

    monkeypatch.setattr(input_adapter, "prepare_input_from_video", fake_prepare_input_from_video)

    prepared = input_adapter.prepare_workflow_input(
        text="make a Taobao product page",
        video_path=str(video),
        preprocess_output_dir=str(tmp_path),
    )

    assert prepared["selected_image_path"] == str(sketch)
    assert prepared["audio_path"] == str(audio)
    assert prepared["selected_source"] == "video_preprocessed_sketch"
    assert f"[IMAGE]: {sketch}" in prepared["final_prompt"]
    assert f"[AUDIO FILE]: {audio}" in prepared["final_prompt"]
    assert prepared["state"]["messages"][0]["content"] == prepared["final_prompt"]
    assert prepared["state"]["vision_retry_count"] == 0


def test_prepare_workflow_input_selects_better_video_sketch(monkeypatch, tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fake video")
    user_img = tmp_path / "user.png"
    video_img = tmp_path / "video.png"
    Image.new("RGB", (100, 100), "white").save(user_img)
    Image.new("RGB", (390, 844), "white").save(video_img)

    monkeypatch.setattr(
        input_adapter,
        "prepare_input_from_video",
        lambda **kwargs: {
            "image_path": str(video_img),
            "audio_path": None,
            "text": kwargs["user_text"],
            "package_path": None,
            "platform_hint": None,
            "transcript_text": "",
            "warnings": [],
            "errors": [],
        },
    )

    monkeypatch.setattr(
        input_adapter,
        "select_best_sketch_candidate",
        lambda user_image_path, video_image_path, output_dir=None: {
            "selected_image_path": video_image_path,
            "selected_source": "video_preprocessed_sketch",
            "selection_reason": "test",
            "user_score": {},
            "video_score": {},
        },
    )

    prepared = input_adapter.prepare_workflow_input(
        text="make UI",
        image_path=str(user_img),
        video_path=str(video),
        preprocess_output_dir=str(tmp_path),
    )

    assert prepared["selected_image_path"] == str(video_img)
    assert prepared["selection"]["selection_reason"] == "test"
    assert f"[IMAGE]: {video_img}" in prepared["final_prompt"]


def test_prepare_input_from_video_reads_package(monkeypatch, tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fake video")
    sketch = tmp_path / "normalized.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGB", (390, 844), "white").save(sketch)
    audio.write_bytes(b"fake audio")

    fake_package = SimpleNamespace(
        model_dump=lambda: {
            "normalized_sketch_path": str(sketch),
            "orientation_corrected_sketch_path": None,
            "rectified_sketch_path": None,
            "selected_sketch_path": str(sketch),
            "audio_path": str(audio),
            "package_path": str(tmp_path / "metadata" / "package.json"),
            "platform_hint": {"platform": "mobile"},
            "transcript_text": "",
            "warnings": [],
            "errors": [],
        }
    )

    class FakeOrchestrator:
        def __init__(self, output_root=None):
            self.output_root = output_root

        def run(self, input_data):
            assert input_data.video_path == str(video)
            return fake_package

    monkeypatch.setattr("src.preprocess.orchestrator.PreAgentOrchestrator", FakeOrchestrator)

    result = input_adapter.prepare_input_from_video(
        video_path=str(video),
        user_text="make UI",
        preprocess_output_dir=str(tmp_path),
    )

    assert result["image_path"] == str(sketch)
    assert result["audio_path"] == str(audio)
    assert result["platform_hint"] == {"platform": "mobile"}
