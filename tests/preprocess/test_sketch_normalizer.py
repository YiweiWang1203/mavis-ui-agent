import tempfile
import cv2
import numpy as np
from src.preprocess.platform_inferencer import PlatformRatioInferencer
from src.preprocess.sketch_normalizer import GeometryPreservingSketchNormalizer


def test_sketch_normalizer_letterbox():
    # create dummy image
    img = 255 * np.ones((200, 100, 3), dtype=np.uint8)
    with tempfile.TemporaryDirectory() as td:
        p = f"{td}/dummy.jpg"
        cv2.imwrite(p, img)
        inf = PlatformRatioInferencer()
        pres = inf.infer("", "", p)
        norm = GeometryPreservingSketchNormalizer()
        res = norm.normalize(p, pres, td)
        assert res.target_size == pres.target_size
        # check file exists
        import os
        assert os.path.exists(res.normalized_sketch_path)
