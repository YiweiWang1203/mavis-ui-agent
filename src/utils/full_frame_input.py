"""Recover a provenance-checked, uncropped selected frame for boundary discovery."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def historical_package_path(case):
    case=Path(case).resolve()
    local=case/'preprocess/metadata/package.json'
    if local.is_file():return local
    # Legacy development cases retain their preprocessing run outside pilot_cases.
    if case.parent.name!='pilot_cases' or case.parent.parent.name!='outputs':
        raise ValueError('External historical package requires project pilot_cases')
    project=case.parents[2]
    manifest=json.loads((case/'case.json').read_text(encoding='utf-8'))
    value=manifest.get('preprocess_package')
    if not isinstance(value,str):raise ValueError('Historical package reference missing')
    path=Path(value)
    path=(path if path.is_absolute() else project/path).resolve()
    if (not path.is_relative_to(project/'outputs/preprocess') or path.name!='package.json'
            or path.parent.name!='metadata' or not path.is_file()):
        raise ValueError('Historical package outside project preprocessing records')
    return path


def recover_full_frame(case, output):
    import cv2
    case = Path(case).resolve()
    output = Path(output)
    package_path = historical_package_path(case)
    source_root=package_path.parent.parent
    project=case.parents[2] if case.parent.name=='pilot_cases' and case.parent.parent.name=='outputs' else case
    package = json.loads(package_path.read_text(encoding='utf-8'))
    manifest = json.loads((case / 'case.json').read_text(encoding='utf-8'))
    def source(key):
        value=Path(package[key])
        p = (value if value.is_absolute() else project/value).resolve()
        if not p.is_relative_to(source_root) or not p.is_file():
            raise ValueError('Historical source must be retained within its preprocessing run')
        return p
    raw = source('selected_sketch_path')
    crop = source('orientation_corrected_sketch_path')
    frozen = (case / manifest['image']).resolve()
    if not frozen.is_relative_to(case) or digest(crop) != digest(frozen):
        raise ValueError('Historical crop does not match frozen image')
    degrees = package['preprocess_metadata']['orientation_correction']['rotation_degrees']
    if degrees != 180:
        raise ValueError('This paired recovery currently supports recorded 180-degree correction only')
    image = cv2.imread(str(raw))
    if image is None:
        raise ValueError('Selected original frame cannot be decoded')
    output.mkdir(parents=True, exist_ok=False)
    if not cv2.imwrite(str(output / 'image.jpg'), cv2.rotate(image, cv2.ROTATE_180)):
        raise ValueError('Cannot save complete oriented frame')
    record = dict(raw_source=str(raw), raw_sha256=digest(raw),
                  historical_crop=str(crop), frozen_crop_sha256=digest(frozen),
                  package_sha256=digest(package_path), package_path=str(package_path), raw_size=[image.shape[1], image.shape[0]],
                  output_sha256=digest(output / 'image.jpg'), rotation_degrees=degrees,
                  transformation='rotation_only_no_crop_no_resize',
                  timestamp_status='historical filename only; verify against video timestamps separately',
                  historical_frame_name=raw.name, historical_video=package['input_video'])
    (output / 'provenance.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record
