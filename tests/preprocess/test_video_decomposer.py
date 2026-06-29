import tempfile
import cv2
import numpy as np
import os
from src.preprocess.video_decomposer import VideoDecomposer


def make_mock_video(path: str, frames: int = 10, w: int = 320, h: int = 240):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, 10.0, (w, h))
    for i in range(frames):
        img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        cv2.putText(img, f"{i}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        out.write(img)
    out.release()


def test_video_decomposer_extracts_frames_and_audio():
    with tempfile.TemporaryDirectory() as td:
        video_path = os.path.join(td, "mock.mp4")
        make_mock_video(video_path)
        vd = VideoDecomposer()
        res = vd.decompose(video_path, td, end_window_ratio=0.5, sample_fps=2.0)
        assert res.video_path == video_path
        assert isinstance(res.candidate_frame_paths, list)
        # frames should be saved
        assert len(res.candidate_frame_paths) > 0
        # audio_path may be None if ffmpeg missing, but should exist or be None
        if res.audio_path:
            assert os.path.exists(res.audio_path)
