from __future__ import annotations
from pathlib import Path
import logging
from typing import Dict, Any
import cv2

from src.utils.pipeline_trace import traced_stage
from .utils import ensure_dir, unique_path
from .schemas import OrientationCorrectionResult

logger = logging.getLogger(__name__)


class OrientationCorrector:
    def __init__(self):
        pass

    @traced_stage('preprocess.orientation')
    def correct(self, sketch_path: str, output_dir: str, rotation_degrees: int = 180, enabled: bool = True, reason: str = "lamp-mounted overhead camera captures the sketch upside down") -> OrientationCorrectionResult:
        inp = Path(sketch_path)
        out_root = ensure_dir(Path(output_dir))
        sketches_dir = ensure_dir(out_root / "sketches")

        result = OrientationCorrectionResult(
            input_sketch_path=str(inp),
            corrected_sketch_path=None,
            enabled=enabled,
            rotation_degrees=rotation_degrees,
            method=f"rotate_{rotation_degrees}",
            reason=reason,
            metadata={},
        )

        if not enabled:
            # Not enabled: keep original path
            result.corrected_sketch_path = str(inp)
            result.metadata["note"] = "orientation correction disabled"
            logger.info("Orientation correction disabled; returning original sketch path")
            return result

        if rotation_degrees not in (0, 90, 180, 270):
            msg = f"Unsupported rotation_degrees: {rotation_degrees}. Only 0/90/180/270 supported"
            logger.error(msg)
            raise ValueError(msg)

        # load image
        img = cv2.imread(str(inp))
        if img is None:
            msg = f"Unable to read image for orientation correction: {inp}"
            logger.error(msg)
            raise RuntimeError(msg)

        if rotation_degrees == 0:
            out_path = unique_path(sketches_dir / f"oriented_{inp.name}")
            # copy original
            cv2.imwrite(str(out_path), img)
            result.corrected_sketch_path = str(out_path)
            result.metadata["note"] = "rotation 0 - copied"
            return result

        if rotation_degrees == 180:
            rotated = cv2.rotate(img, cv2.ROTATE_180)
        elif rotation_degrees == 90:
            rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif rotation_degrees == 270:
            rotated = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

        out_path = unique_path(sketches_dir / f"oriented_{rotation_degrees}_{inp.name}")
        ok = cv2.imwrite(str(out_path), rotated)
        if not ok:
            msg = f"Failed to write oriented image to {out_path}"
            logger.error(msg)
            raise RuntimeError(msg)

        result.corrected_sketch_path = str(out_path)
        result.metadata["written"] = result.corrected_sketch_path
        return result
