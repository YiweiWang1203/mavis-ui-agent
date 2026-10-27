from __future__ import annotations
from typing import List, Tuple
from pathlib import Path
import cv2
import numpy as np
import json
from src.utils.pipeline_trace import traced_stage
from .schemas import FinalSketchResult, FrameScore
from .utils import ensure_dir, unique_path


class FinalSketchExtractor:
    def __init__(self):
        pass

    def _sharpness(self, img) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        var = cv2.Laplacian(gray, cv2.CV_64F).var()
        # map var to 0-1 using heuristic
        score = max(0.0, min(1.0, var / 1000.0))
        return score

    def _sketch_density(self, img) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        ratio = edges.sum() / 255.0 / (edges.shape[0] * edges.shape[1])
        # heuristic normalization
        score = max(0.0, min(1.0, (ratio - 0.01) / 0.1))
        return score

    @traced_stage('preprocess.frame_select')
    def select_final_sketch(self, candidate_frame_paths: List[str], timestamps: List[float], output_dir: str, top_k: int = 5) -> FinalSketchResult:
        outd = ensure_dir(Path(output_dir))
        scores = []
        if not candidate_frame_paths:
            raise ValueError("no candidate frames provided")

        max_t = max(timestamps) if timestamps else 0.0
        min_t = min(timestamps) if timestamps else 0.0

        for p, t in zip(candidate_frame_paths, timestamps):
            img = cv2.imread(p)
            if img is None:
                continue
            sharp = self._sharpness(img)
            density = self._sketch_density(img)
            end_prox = 0.0
            if max_t > min_t:
                end_prox = (t - min_t) / (max_t - min_t)
            occlusion = None
            board_cov = None

            # combine with default weights
            # if optional scores are None, normalize weights
            w = {"sharp": 0.35, "dens": 0.30, "end": 0.25, "occ": 0.05, "cov": 0.05}
            total_weight = 0.35 + 0.30 + 0.25
            final = (w["sharp"] * sharp + w["dens"] * density + w["end"] * end_prox) / total_weight

            scores.append((p, t, sharp, density, end_prox, occlusion, board_cov, final))

        # sort by final descending
        scores_sorted = sorted(scores, key=lambda x: x[7], reverse=True)
        topk = scores_sorted[:top_k]

        frame_scores = []
        topk_paths = []
        for item in topk:
            p, t, sharp, dens, endp, occ, cov, final = item
            frame_scores.append(FrameScore(
                frame_path=p,
                timestamp=t,
                sharpness_score=sharp,
                sketch_density_score=dens,
                end_proximity_score=endp,
                occlusion_score=occ,
                board_coverage_score=cov,
                final_score=final,
            ))
            topk_paths.append(p)

        selected = topk_paths[0] if topk_paths else candidate_frame_paths[0]

        # write metadata
        meta_path = outd / "frame_scores.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump([fs.dict() for fs in frame_scores], f, ensure_ascii=False, indent=2)

        return FinalSketchResult(
            selected_frame_path=selected,
            topk_frame_paths=topk_paths,
            frame_scores=frame_scores,
            selection_strategy="weighted_sharp_density_end",
            confidence=frame_scores[0].final_score if frame_scores else 0.0,
        )
