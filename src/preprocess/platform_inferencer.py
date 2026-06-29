from __future__ import annotations
from typing import Optional, List, Tuple
from pathlib import Path
import cv2
from .schemas import PlatformInferenceResult


class PlatformRatioInferencer:
    def infer(self, user_prompt: str, transcript_text: str, sketch_path: str, explicit_platform: Optional[str] = None, explicit_ratio: Optional[str] = None) -> PlatformInferenceResult:
        if explicit_platform:
            platform = explicit_platform
        else:
            platform = self._infer_from_text(user_prompt) or self._infer_from_text(transcript_text) or "unknown"

        evidence: List[str] = []
        if platform != "unknown":
            evidence.append(f"text_hint:{platform}")

        # image rules
        size = (0, 0)
        try:
            img = cv2.imread(sketch_path)
            if img is not None:
                h, w = img.shape[:2]
                size = (w, h)
                ratio = w / h if h > 0 else 1.0
                if ratio < 0.75:
                    platform = platform if platform != "unknown" else "mobile"
                    evidence.append("img_ratio_portrait")
                elif ratio > 1.35:
                    platform = platform if platform != "unknown" else "desktop"
                    evidence.append("img_ratio_landscape")
                else:
                    platform = platform if platform != "unknown" else "adaptive"
                    evidence.append("img_ratio_square")
        except Exception:
            pass

        orientation = "portrait" if size[1] >= size[0] else "landscape"

        # mapping
        if platform == "mobile":
            target_ratio = "9:16"
            target_size = (390, 844)
        elif platform == "tablet":
            target_ratio = "3:4"
            target_size = (768, 1024)
        elif platform == "desktop":
            # choose 16:9 default
            target_ratio = explicit_ratio or "16:9"
            target_size = (1366, 768)
        elif platform == "adaptive":
            target_ratio = "adaptive"
            target_size = (1024, 1024)
        else:
            target_ratio = "adaptive"
            target_size = (1024, 1024)

        confidence = 0.9 if platform != "unknown" else 0.4

        return PlatformInferenceResult(
            platform=platform,
            orientation=orientation,
            target_ratio=target_ratio,
            target_size=target_size,
            evidence=evidence,
            confidence=confidence,
        )

    def _infer_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        t = text.lower()
        mobile_keywords = ["手机", "移动端", "小程序", "app", "h5", "phone", "mobile"]
        desktop_keywords = ["网页端", "pc", "后台", "管理系统", "dashboard", "desktop", "web admin"]
        tablet_keywords = ["平板", "tablet"]
        for k in mobile_keywords:
            if k in t:
                return "mobile"
        for k in desktop_keywords:
            if k in t:
                return "desktop"
        for k in tablet_keywords:
            if k in t:
                return "tablet"
        return None
