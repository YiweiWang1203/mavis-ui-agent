import tempfile
import cv2
import numpy as np
import os
from src.preprocess.sketch_rectifier import SketchRectifier


def make_rect_image(path):
    h, w = 400, 300
    img = 255 * np.ones((h, w, 3), dtype=np.uint8)
    # draw large rectangle (simulate board)
    cv2.rectangle(img, (20, 30), (w-20, h-30), (0, 0, 0), 10)
    cv2.imwrite(path, img)


def test_sketch_rectifier_detects_and_rectifies():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "rect.jpg")
        make_rect_image(p)
        sr = SketchRectifier()
        res = sr.rectify(p, td)
        assert res.raw_sketch_path == p
        assert os.path.exists(res.rectified_sketch_path)
        assert os.path.exists(res.enhanced_sketch_path)
        assert isinstance(res.board_detected, bool)
