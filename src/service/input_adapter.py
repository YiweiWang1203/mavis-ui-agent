from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from src.utils.pipeline_trace import traced_stage

DEFAULT_USER_TEXT = "Generate runnable frontend UI code from the provided attachments."
DEFAULT_TEAM_MEMBERS = [
    "researcher",
    "coder",
    "reporter",
    "meeting_agent",
    "browser_agent",
    "sa2va_agent",
    "vision_agent",
    "ui_architect",
]


def _get_team_members() -> list[str]:
    try:
        from src.config import TEAM_MEMBERS

        return TEAM_MEMBERS
    except Exception:
        return DEFAULT_TEAM_MEMBERS


def infer_preferred_locale(user_text: str | None) -> str:
    """Infer UI locale from explicit language requests, then prompt language."""
    text = (user_text or "").strip()
    lowered = text.lower()

    english_markers = [
        "english",
        "en-us",
        "en_us",
        "en ",
        "global users",
        "foreign users",
        "overseas",
        "international",
        "英文",
        "英语",
        "海外用户",
        "外国用户",
        "国际化",
    ]
    chinese_markers = [
        "chinese",
        "zh-cn",
        "zh_cn",
        "中文",
        "汉语",
        "中国用户",
        "中文界面",
    ]

    if any(marker in lowered for marker in english_markers) and not any(marker in lowered for marker in chinese_markers):
        return "en"
    if any(marker in lowered for marker in chinese_markers):
        return "zh-CN"

    ascii_letters = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if ascii_letters >= 12 and ascii_letters > cjk_chars * 2:
        return "en"
    return "zh-CN"


def score_sketch_candidate(image_path: str) -> dict[str, Any]:
    """Score an image for suitability as the UI sketch input."""
    import cv2

    result: dict[str, Any] = {
        "image_path": image_path,
        "exists": False,
        "readable": False,
        "width": 0,
        "height": 0,
        "sharpness_score": 0.0,
        "edge_density_score": 0.0,
        "content_coverage_score": 0.0,
        "aspect_score": 0.0,
        "final_score": 0.0,
        "warnings": [],
    }

    path = Path(image_path)
    if not path.exists():
        result["warnings"].append("file_missing")
        return result

    result["exists"] = True
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        result["warnings"].append("not_readable")
        return result

    result["readable"] = True
    height, width = img.shape[:2]
    result["width"] = width
    result["height"] = height

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharpness_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharpness = max(0.0, min(1.0, sharpness_var / (sharpness_var + 100.0)))

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.astype(bool).sum()) / max(1, width * height)
    edge_score = max(0.0, min(1.0, (edge_density - 0.005) / (0.15 - 0.005)))

    foreground = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)[1]
    coverage = float(foreground.astype(bool).sum()) / max(1, width * height)
    coverage_score = max(0.0, min(1.0, coverage * 2.0))

    ratio = width / height if height > 0 else 1.0
    target_ratio = 9.0 / 16.0
    aspect_score = 1.0 - min(1.0, abs(ratio - target_ratio))

    result["sharpness_score"] = sharpness
    result["edge_density_score"] = edge_score
    result["content_coverage_score"] = coverage_score
    result["aspect_score"] = aspect_score
    result["final_score"] = max(
        0.0,
        min(1.0, 0.3 * sharpness + 0.3 * edge_score + 0.25 * coverage_score + 0.15 * aspect_score),
    )
    return result


def select_best_sketch_candidate(
    user_image_path: str | None,
    video_image_path: str | None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Select the best sketch when both a direct image and video-derived image exist."""
    user_score = score_sketch_candidate(user_image_path) if user_image_path else None
    video_score = score_sketch_candidate(video_image_path) if video_image_path else None

    user_valid = bool(user_score and user_score.get("readable"))
    video_valid = bool(video_score and video_score.get("readable"))
    if not user_valid and not video_valid:
        raise RuntimeError("No valid image candidates available")

    if user_valid and not video_valid:
        selected = user_image_path
        source = "user_image"
        reason = "only user image readable"
    elif video_valid and not user_valid:
        selected = video_image_path
        source = "video_preprocessed_sketch"
        reason = "only video-derived image readable"
    else:
        user_final = float(user_score.get("final_score", 0.0))
        video_final = float(video_score.get("final_score", 0.0))
        if abs(user_final - video_final) < 0.05:
            selected = video_image_path
            source = "video_preprocessed_sketch"
            reason = "scores close; prefer video-derived sketch"
        elif video_final > user_final:
            selected = video_image_path
            source = "video_preprocessed_sketch"
            reason = "video score higher"
        else:
            selected = user_image_path
            source = "user_image"
            reason = "user image score higher"

    result = {
        "selected_image_path": selected,
        "selected_source": source,
        "selection_reason": reason,
        "user_score": user_score,
        "video_score": video_score,
    }

    if output_dir:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "sketch_candidate_selection.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _serialize_platform_hint(platform_hint: Any) -> dict[str, Any] | None:
    if platform_hint is None:
        return None
    if isinstance(platform_hint, dict):
        return platform_hint
    if hasattr(platform_hint, "model_dump"):
        return platform_hint.model_dump()
    if hasattr(platform_hint, "dict"):
        return platform_hint.dict()
    return {
        k: getattr(platform_hint, k)
        for k in ("platform", "orientation", "target_ratio", "target_size", "confidence")
        if hasattr(platform_hint, k)
    }


def prepare_input_from_video(
    video_path: str,
    user_text: str,
    preprocess_output_dir: str | None = None,
    rotate_degrees: int = 180,
    orientation_correction_enabled: bool = True,
    enable_asr: bool = False,
    vision_image_mode: str = "recognition",
) -> dict[str, Any]:
    """Run the pre-agent video pipeline and expose graph-ready input pieces."""
    if vision_image_mode not in {"recognition", "normalized"}:
        raise ValueError("vision_image_mode must be either 'recognition' or 'normalized'")
    try:
        from src.preprocess.orchestrator import PreAgentOrchestrator
        from src.preprocess.schemas import UserPreprocessInput
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Video preprocessing dependencies are not installed. "
            "Install the project requirements before running video input."
        ) from exc

    output_dir = preprocess_output_dir or os.path.join("outputs", "preprocess")
    input_data = UserPreprocessInput(
        user_prompt=user_text,
        video_path=video_path,
        output_dir=output_dir,
        rotate_degrees=rotate_degrees,
        disable_orientation_correction=not orientation_correction_enabled,
        enable_asr=enable_asr,
    )

    package = PreAgentOrchestrator(output_root=output_dir).run(input_data)
    package_dict = package.model_dump() if hasattr(package, "model_dump") else dict(package)

    recognition_image_path = (
        package_dict.get("orientation_corrected_sketch_path")
        or package_dict.get("rectified_sketch_path")
        or package_dict.get("selected_sketch_path")
        or package_dict.get("normalized_sketch_path")
    )
    layout_image_path = package_dict.get("normalized_sketch_path")
    if vision_image_mode == "normalized":
        image_path = layout_image_path or recognition_image_path
    else:
        image_path = recognition_image_path or layout_image_path
    if not image_path:
        raise RuntimeError("Video preprocessing did not produce a sketch image")

    return {
        "image_path": image_path,
        "vision_image_mode": vision_image_mode,
        "recognition_image_path": recognition_image_path,
        "layout_image_path": layout_image_path,
        "audio_path": package_dict.get("audio_path"),
        "text": user_text,
        "package_path": package_dict.get("package_path"),
        "preprocess_output_dir": output_dir,
        "selected_sketch_path": package_dict.get("selected_sketch_path"),
        "rectified_sketch_path": package_dict.get("rectified_sketch_path"),
        "orientation_corrected_sketch_path": package_dict.get("orientation_corrected_sketch_path"),
        "normalized_sketch_path": package_dict.get("normalized_sketch_path"),
        "platform_hint": _serialize_platform_hint(package_dict.get("platform_hint")),
        "transcript_text": package_dict.get("transcript_text") or "",
        "warnings": package_dict.get("warnings") or [],
        "errors": package_dict.get("errors") or [],
    }


def build_multimodal_prompt(
    *,
    user_text: str,
    selected_image_path: str,
    selected_source: str,
    audio_path: str | None = None,
    video_context: dict[str, Any] | None = None,
    package_path: str | None = None,
    preferred_locale: str = "zh-CN",
) -> str:
    """Create the canonical first user message consumed by graph nodes."""
    lines = [
        f"User request: {user_text}",
        "",
        "[PREPROCESS CONTEXT]",
        f"selected_source: {selected_source}",
        f"preferred_locale: {preferred_locale}",
    ]

    if video_context:
        if video_context.get("vision_image_mode"):
            lines.append(f"vision_image_mode: {video_context['vision_image_mode']}")
        if video_context.get("recognition_image_path"):
            lines.append(f"recognition_image_path: {video_context['recognition_image_path']}")
        if video_context.get("layout_image_path"):
            lines.append(f"layout_image_path: {video_context['layout_image_path']}")
        platform_hint = video_context.get("platform_hint")
        if platform_hint:
            lines.append(f"platform_hint: {json.dumps(platform_hint, ensure_ascii=False)}")
        if video_context.get("transcript_text"):
            lines.append(f"transcript_text: {video_context['transcript_text']}")
        if video_context.get("warnings"):
            lines.append(f"preprocess_warnings: {json.dumps(video_context['warnings'], ensure_ascii=False)}")
        if package_path:
            lines.append(f"package_path: {package_path}")

    lines.extend(["", f"[IMAGE]: {selected_image_path}"])
    if audio_path:
        lines.append(f"[AUDIO FILE]: {audio_path}")

    return "\n".join(lines)


@traced_stage('workflow.prepare_input')
def prepare_workflow_input(
    *,
    text: str | None = None,
    image_path: str | None = None,
    video_path: str | None = None,
    audio_path: str | None = None,
    preprocess_output_dir: str | None = None,
    rotate_degrees: int = 180,
    orientation_correction_enabled: bool = True,
    enable_asr: bool = False,
    vision_image_mode: str = "recognition",
) -> dict[str, Any]:
    """Prepare graph input state from image/video/audio paths."""
    user_text = text or DEFAULT_USER_TEXT
    preferred_locale = infer_preferred_locale(user_text)
    if vision_image_mode not in {"recognition", "normalized"}:
        raise ValueError("vision_image_mode must be either 'recognition' or 'normalized'")
    if not image_path and not video_path:
        raise ValueError("Either image_path or video_path must be provided")

    video_result: dict[str, Any] | None = None
    video_image_path: str | None = None
    if video_path:
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video path does not exist: {video_path}")
        video_result = prepare_input_from_video(
            video_path=video_path,
            user_text=user_text,
            preprocess_output_dir=preprocess_output_dir,
            rotate_degrees=rotate_degrees,
            orientation_correction_enabled=orientation_correction_enabled,
            enable_asr=enable_asr,
            vision_image_mode=vision_image_mode,
        )
        video_image_path = video_result["image_path"]
        audio_path = audio_path or video_result.get("audio_path")

    if image_path and not Path(image_path).exists():
        raise FileNotFoundError(f"Image path does not exist: {image_path}")

    if image_path and video_image_path:
        selection = select_best_sketch_candidate(image_path, video_image_path, output_dir=preprocess_output_dir)
        selected_image_path = selection["selected_image_path"]
        selected_source = selection["selected_source"]
    elif video_image_path:
        selected_image_path = video_image_path
        selected_source = "video_preprocessed_sketch"
        selection = None
    else:
        selected_image_path = image_path
        selected_source = "user_image"
        selection = None

    package_path = video_result.get("package_path") if video_result else None
    final_prompt = build_multimodal_prompt(
        user_text=user_text,
        selected_image_path=selected_image_path,
        selected_source=selected_source,
        audio_path=audio_path,
        video_context=video_result,
        package_path=package_path,
        preferred_locale=preferred_locale,
    )

    state = {
        "TEAM_MEMBERS": _get_team_members(),
        "messages": [{"role": "user", "content": final_prompt}],
        "image_path": selected_image_path,
        "recognition_image_path": (video_result or {}).get("recognition_image_path"),
        "layout_image_path": (video_result or {}).get("layout_image_path"),
        "vision_image_mode": (video_result or {}).get("vision_image_mode") or ("user_image" if not video_result else vision_image_mode),
        "voice_intent": None,
        "vision_elements": None,
        "vision_status": None,
        "vision_raw_output": None,
        "vision_retry_count": 0,
        "ui_state_json": None,
        "final_code": None,
        "warnings": (video_result or {}).get("warnings", []),
        "preferred_locale": preferred_locale,
    }

    return {
        "state": state,
        "final_prompt": final_prompt,
        "selected_image_path": selected_image_path,
        "recognition_image_path": (video_result or {}).get("recognition_image_path"),
        "layout_image_path": (video_result or {}).get("layout_image_path"),
        "vision_image_mode": (video_result or {}).get("vision_image_mode") or ("user_image" if not video_result else vision_image_mode),
        "selected_source": selected_source,
        "audio_path": audio_path,
        "video_result": video_result,
        "selection": selection,
        "package_path": package_path,
        "preferred_locale": preferred_locale,
    }
