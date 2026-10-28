import importlib.util
import unittest
import numpy as np
from src.utils.paper_line_probe import line_records, visible_paper


class MappingTests(unittest.TestCase):
    def test_crop_lines_return_to_original_without_scaling(self):
        result = line_records([np.array([[1., 2.], [11., 7.]])], (20, 100))
        self.assertEqual(result[0]['endpoints'], [21., 102., 31., 107.])

    def test_nonfinite_evidence_rejected(self):
        with self.assertRaises(ValueError):
            line_records([np.array([0., 0., np.nan, 1.])])


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV required')
class PaperTests(unittest.TestCase):
    def test_uniform_frame_is_unresolved_not_full_image_paper(self):
        mask, record = visible_paper(np.full((100, 160, 3), 200, np.uint8))
        self.assertIsNone(mask)
        self.assertEqual(record['status'], 'unresolved')

    def test_visible_paper_can_touch_photo_without_claiming_complete(self):
        image = np.empty((150, 200, 3), np.uint8)
        image[:] = [80, 120, 160]
        image[30:130] = [200, 200, 200]
        image[65:68, 40:170] = 20
        mask, record = visible_paper(image)
        self.assertIsNotNone(mask)
        self.assertTrue(record['touches_photo_edges']['left'])
        self.assertFalse(record['complete_paper_boundary_verified'])
        self.assertGreater(mask[66, 100], 0)


if __name__ == '__main__':
    unittest.main()
