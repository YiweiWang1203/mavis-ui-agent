import tempfile
import cv2
import numpy as np
import os
from src.preprocess.frame_selector import FinalSketchExtractor


def make_image(path, sharp=True, edges=1000):
    h, w = 200, 200
    if sharp:
        img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        cv2.line(img, (10, 10), (190, 10), (0, 0, 0), 3)
        cv2.line(img, (10, 10), (10, 190), (0, 0, 0), 3)
    else:
        img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        img = cv2.GaussianBlur(img, (11, 11), 0)
    cv2.imwrite(path, img)


def test_frame_selector_picks_best():
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "f1.jpg")
        p2 = os.path.join(td, "f2.jpg")
        p3 = os.path.join(td, "f3.jpg")
        make_image(p1, sharp=True)
        make_image(p2, sharp=False)
        make_image(p3, sharp=True)
        fs = FinalSketchExtractor()
        res = fs.select_final_sketch([p1, p2, p3], [1.0, 2.0, 3.0], td, top_k=2)
        assert res.selected_frame_path in [p1, p3]
        assert len(res.topk_frame_paths) <= 2
        # metadata file created
        assert os.path.exists(os.path.join(td, "frame_scores.json"))
