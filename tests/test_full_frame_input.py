import json
from pathlib import Path
import pytest
from src.utils.full_frame_input import recover_full_frame


def fixture_case(tmp_path):
    case=tmp_path/'case';pre=case/'preprocess';pre.mkdir(parents=True)
    (pre/'metadata').mkdir()
    import cv2
    import numpy as np
    image=np.zeros((40,60,3),dtype=np.uint8);image[:10,:15]=255
    cv2.imwrite(str(pre/'frame.jpg'),image)
    cv2.imwrite(str(pre/'crop.jpg'),image[:20,:20])
    (case/'image.jpg').write_bytes((pre/'crop.jpg').read_bytes())
    (case/'case.json').write_text(json.dumps({'image':'image.jpg'}))
    package=dict(selected_sketch_path=str(pre/'frame.jpg'),orientation_corrected_sketch_path=str(pre/'crop.jpg'),
                 input_video='retained.mp4',preprocess_metadata={'orientation_correction':{'rotation_degrees':180}})
    (pre/'metadata/package.json').write_text(json.dumps(package))
    return case


def test_complete_dimensions_and_pixels_are_preserved(tmp_path):
    import cv2
    case=fixture_case(tmp_path);out=tmp_path/'out'
    r=recover_full_frame(case,out)
    assert r['raw_size']==[60,40]
    image=cv2.imread(str(out/'image.jpg'))
    assert image.shape[:2]==(40,60)
    assert image[-5:,-5:].mean()>240
    assert image[:5,:5].mean()<10


def test_mismatched_crop_fails_without_output(tmp_path):
    case=fixture_case(tmp_path);(case/'image.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError,match='does not match'):
        recover_full_frame(case,tmp_path/'out')
    assert not (tmp_path/'out').exists()
