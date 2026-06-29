import tempfile
import cv2
import numpy as np
from src.preprocess.orchestrator import PreAgentOrchestrator
from src.preprocess.schemas import UserPreprocessInput


def make_mock_video(path: str, frames: int = 10, w: int = 320, h: int = 240):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, 10.0, (w, h))
    for i in range(frames):
        img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        cv2.putText(img, f"{i}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        out.write(img)
    out.release()


def test_orchestrator_with_mock_video():
    with tempfile.TemporaryDirectory() as td:
        video_path = f"{td}/mock.mp4"
        make_mock_video(video_path)
        inp = UserPreprocessInput(user_prompt="请根据视频生成页面", video_path=video_path, output_dir=td)
        orch = PreAgentOrchestrator(output_root=td)
        pkg = orch.run(inp)
        assert pkg.input_video == video_path
        assert pkg.raw_user_prompt == "请根据视频生成页面"
        # orientation correction should have been applied by default
        assert hasattr(pkg, "orientation_corrected_sketch_path")
        assert pkg.orientation_corrected_sketch_path is not None
        # metadata should include orientation_correction
        meta = pkg.preprocess_metadata or {}
        assert "orientation_correction" in meta
        assert meta["orientation_correction"]["rotation_degrees"] == 180
