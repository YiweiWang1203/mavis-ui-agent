from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import logging
import cv2
import math
from src.utils.pipeline_trace import traced_stage
from .utils import ensure_dir, run_ffmpeg_extract_audio, unique_path
from .schemas import VideoDecompositionResult

logger = logging.getLogger(__name__)


class VideoDecomposer:
    @traced_stage('preprocess.video_decompose')
    def decompose(self, video_path: str, output_dir: str, end_window_ratio: float = 0.3, sample_fps: float = 2.0) -> VideoDecompositionResult:
        vp = Path(video_path)
        if not vp.exists():
            raise FileNotFoundError(f"video not found: {video_path}")

        out_dir = ensure_dir(Path(output_dir))
        frames_dir = ensure_dir(out_dir / "frames")
        audio_dir = ensure_dir(out_dir / "audio")

        base_name = vp.stem

        # Try ffmpeg to extract audio
        audio_path = audio_dir / f"{base_name}.wav"
        ok, msg = run_ffmpeg_extract_audio(vp, audio_path)
        if not ok:
            logger.warning("audio extraction failed: %s", msg)
            audio_path = None

        cap = cv2.VideoCapture(str(vp))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0

        # sampling window: last end_window_ratio of video
        start_t = max(0.0, duration * (1.0 - end_window_ratio))
        end_t = duration

        candidate_frame_paths: List[str] = []
        timestamps: List[float] = []

        # sample at sample_fps within window
        step = 1.0 / sample_fps
        t = start_t
        idx = 0
        while t < end_t:
            frame_idx = int(t * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                t += step
                continue
            fname = frames_dir / f"{base_name}_{int(t)}s_{idx}.jpg"
            fname = unique_path(fname)
            cv2.imwrite(str(fname), frame)
            candidate_frame_paths.append(str(fname))
            timestamps.append(t)
            idx += 1
            t += step

        cap.release()

        metadata: Dict[str, Any] = {
            "width": width,
            "height": height,
            "frame_count": frame_count,
        }

        return VideoDecompositionResult(
            video_path=str(vp),
            audio_path=str(audio_path) if audio_path is not None else None,
            candidate_frame_paths=candidate_frame_paths,
            video_duration=duration,
            fps=fps,
            sampling_window={"start": start_t, "end": end_t},
            metadata=metadata,
        )
