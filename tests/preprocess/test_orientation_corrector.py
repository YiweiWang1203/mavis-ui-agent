import tempfile
from pathlib import Path
import cv2
import numpy as np

from src.preprocess.orientation_corrector import OrientationCorrector


def test_orientation_corrector_rotates_180():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img_path = td / "orig.jpg"
        # create white image with black square in top-left
        h, w = 100, 200
        img = 255 * np.ones((h, w, 3), dtype=np.uint8)
        cv2.rectangle(img, (5, 5), (20, 20), (0, 0, 0), -1)
        cv2.imwrite(str(img_path), img)

        oc = OrientationCorrector()
        res = oc.correct(str(img_path), str(td), rotation_degrees=180, enabled=True)

        assert res.rotation_degrees == 180
        assert res.enabled is True
        assert res.corrected_sketch_path is not None

        out = cv2.imread(res.corrected_sketch_path)
        assert out is not None
        # original top-left black pixel should move to bottom-right after 180 rotation
        # check a pixel near bottom-right
        br = out[h - 6, w - 6]
        # tolerate slight JPEG compression artifacts: check dark pixel
        assert int(br.sum()) < 30