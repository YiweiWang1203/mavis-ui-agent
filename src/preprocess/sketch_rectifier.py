from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import cv2
import numpy as np
from src.utils.pipeline_trace import traced_stage
from .utils import ensure_dir, unique_path
from .schemas import SketchRectificationResult


class SketchRectifier:
    @traced_stage('preprocess.rectify')
    def rectify(self, sketch_path: str, output_dir: str) -> SketchRectificationResult:
        sp = Path(sketch_path)
        if not sp.exists():
            raise FileNotFoundError(f"sketch not found: {sketch_path}")

        outd = ensure_dir(Path(output_dir))
        img = cv2.imread(str(sp))
        h, w = img.shape[:2]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        board_detected = False
        homography_applied = False
        rectified_path = None
        enhanced_path = None
        metadata: Dict[str, Any] = {}

        # find largest quad
        quads = []
        for cnt in contours:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4:
                area = cv2.contourArea(approx)
                quads.append((area, approx))

        if quads:
            quads.sort(key=lambda x: x[0], reverse=True)
            area, quad = quads[0]
            # heuristic: area should be sufficiently large
            if area > 0.1 * h * w:
                board_detected = True
                pts = quad.reshape(4, 2)
                # order points
                rect = self._order_points(pts)
                (tl, tr, br, bl) = rect
                widthA = np.linalg.norm(br - bl)
                widthB = np.linalg.norm(tr - tl)
                maxWidth = max(int(widthA), int(widthB))
                heightA = np.linalg.norm(tr - br)
                heightB = np.linalg.norm(tl - bl)
                maxHeight = max(int(heightA), int(heightB))

                dst = np.array([
                    [0, 0],
                    [maxWidth - 1, 0],
                    [maxWidth - 1, maxHeight - 1],
                    [0, maxHeight - 1]
                ], dtype="float32")

                M = cv2.getPerspectiveTransform(rect.astype('float32'), dst)
                warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
                rectified_path = unique_path(outd / f"rectified_{sp.name}")
                cv2.imwrite(str(rectified_path), warped)
                homography_applied = True
                metadata["homography_matrix"] = M.tolist()

        if not rectified_path:
            # fallback: copy original
            rectified_path = unique_path(outd / f"rectified_{sp.name}")
            cv2.imwrite(str(rectified_path), img)

        # enhancement
        rimg = cv2.imread(str(rectified_path))
        gray2 = cv2.cvtColor(rimg, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.adaptiveThreshold(gray2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8)
        enhanced_path = unique_path(outd / f"enhanced_{sp.name}")
        cv2.imwrite(str(enhanced_path), enhanced)

        metadata.update({"board_detected": board_detected, "homography_applied": homography_applied})

        return SketchRectificationResult(
            raw_sketch_path=str(sp),
            rectified_sketch_path=str(rectified_path),
            enhanced_sketch_path=str(enhanced_path),
            board_detected=board_detected,
            homography_applied=homography_applied,
            metadata=metadata,
        )

    def _order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect
