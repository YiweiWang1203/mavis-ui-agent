from __future__ import annotations
from pathlib import Path
from typing import Tuple
import cv2
import numpy as np
from src.utils.pipeline_trace import traced_stage
from .utils import ensure_dir, unique_path
from .schemas import SketchNormalizationResult, PlatformInferenceResult


class GeometryPreservingSketchNormalizer:
    @traced_stage('preprocess.normalize')
    def normalize(self, sketch_path: str, platform_result: PlatformInferenceResult, output_dir: str, preserve_geometry: bool = True, input_after_orientation_correction: bool = False) -> SketchNormalizationResult:
        sp = Path(sketch_path)
        if not sp.exists():
            raise FileNotFoundError(f"sketch not found: {sketch_path}")

        outd = ensure_dir(Path(output_dir))
        img = cv2.imread(str(sp))
        h, w = img.shape[:2]

        target_w, target_h = platform_result.target_size

        # compute scale preserving aspect ratio (letterbox)
        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        canvas = 255 * np.ones((target_h, target_w, 3), dtype=np.uint8)
        x = (target_w - new_w) // 2
        y = (target_h - new_h) // 2
        canvas[y:y+new_h, x:x+new_w] = resized

        out_path = unique_path(outd / f"normalized_{sp.name}")
        cv2.imwrite(str(out_path), canvas)

        metadata = {"original_size": (w, h), "resized": (new_w, new_h), "offset": (x, y), "input_after_orientation_correction": bool(input_after_orientation_correction)}

        return SketchNormalizationResult(
            input_sketch_path=str(sp),
            normalized_sketch_path=str(out_path),
            target_ratio=platform_result.target_ratio,
            target_size=platform_result.target_size,
            method="letterbox_scale",
            preserve_geometry=preserve_geometry,
            metadata=metadata,
        )

    # placeholders for future
    def detect_geometric_primitives(self, img_path: str):
        raise NotImplementedError

    def remap_layout_boxes(self):
        raise NotImplementedError

    def redraw_canonical_sketch(self):
        raise NotImplementedError
