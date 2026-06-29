from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


class UserPreprocessInput(BaseModel):
    user_prompt: str
    video_path: str
    output_dir: str = "outputs/preprocess"
    language: str = "zh"
    enable_asr: bool = False
    enable_llm_refine: bool = False
    enable_frame_fusion: bool = False
    target_platform: Optional[str] = None
    target_ratio: Optional[str] = None
    # orientation correction controls
    rotate_degrees: int = 180
    disable_orientation_correction: bool = False


class OptimizedPromptSpec(BaseModel):
    raw_prompt: str
    optimized_prompt: str
    user_goal: str
    expected_outputs: List[str]
    constraints: List[str]
    uncertainties: List[str]
    inferred_task_type: str
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class VideoDecompositionResult(BaseModel):
    video_path: str
    audio_path: Optional[str]
    candidate_frame_paths: List[str]
    video_duration: float
    fps: float
    sampling_window: Dict[str, float]
    metadata: Dict[str, Any]


class FrameScore(BaseModel):
    frame_path: str
    timestamp: float
    sharpness_score: float
    sketch_density_score: float
    end_proximity_score: float
    occlusion_score: Optional[float]
    board_coverage_score: Optional[float]
    final_score: float


class FinalSketchResult(BaseModel):
    selected_frame_path: str
    topk_frame_paths: List[str]
    frame_scores: List[FrameScore]
    selection_strategy: str
    confidence: float


class SketchRectificationResult(BaseModel):
    raw_sketch_path: str
    rectified_sketch_path: Optional[str]
    enhanced_sketch_path: Optional[str]
    board_detected: bool
    homography_applied: bool
    metadata: Dict[str, Any]


class OrientationCorrectionResult(BaseModel):
    input_sketch_path: str
    corrected_sketch_path: Optional[str]
    enabled: bool = True
    rotation_degrees: int = 180
    method: str = "rotate_180"
    reason: str = "lamp-mounted overhead camera captures the sketch upside down"
    metadata: Dict[str, Any] = {}


class PlatformInferenceResult(BaseModel):
    platform: str
    orientation: str
    target_ratio: str
    target_size: Tuple[int, int]
    evidence: List[str]
    confidence: float


class SketchNormalizationResult(BaseModel):
    input_sketch_path: str
    normalized_sketch_path: str
    target_ratio: str
    target_size: Tuple[int, int]
    method: str
    preserve_geometry: bool
    metadata: Dict[str, Any]


class MultimodalPreprocessPackage(BaseModel):
    input_video: str
    raw_user_prompt: str
    optimized_prompt_spec: OptimizedPromptSpec
    audio_path: Optional[str]
    transcript_text: str = ""
    candidate_frames: List[str]
    selected_sketch_path: Optional[str]
    rectified_sketch_path: Optional[str]
    orientation_corrected_sketch_path: Optional[str] = None
    normalized_sketch_path: Optional[str]
    platform_hint: PlatformInferenceResult
    preprocess_metadata: Dict[str, Any]
    errors: List[str]
    warnings: List[str]
    package_path: Optional[str] = None
