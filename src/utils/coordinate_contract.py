"""D1 opt-in contract: image observations never own viewport placements."""
import copy
import math
import re


def _id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Coordinate contract requires a nonempty ID')
    return value


def _size(value):
    if not isinstance(value, dict) or any(
        not isinstance(value.get(k), int) or isinstance(value[k], bool) or value[k] <= 0
        for k in ('width', 'height')
    ):
        raise ValueError('Coordinate contract requires positive integer dimensions')
    return {k: value[k] for k in ('width', 'height')}


def _bbox(value, width, height):
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
        for x in value
    ):
        raise ValueError('Coordinate contract requires four finite coordinates')
    x1, y1, x2, y2 = value
    if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
        raise ValueError('Coordinate contract box outside its declared space')
    return copy.deepcopy(value)


def apply_coordinate_contract(state, vision_elements, contract):
    """Attach source geometry and validate a separate, complete layout plan.

    Semantic-layout provenance is checked for references, not truth. No implicit
    image-to-page transform is offered. The old API remains the legacy baseline.
    """
    if not isinstance(contract, dict) or contract.get('version') != 'evidence-layout-v1':
        raise ValueError('Unknown coordinate contract version')
    frame, viewport = contract.get('frame'), contract.get('viewport')
    if not isinstance(frame, dict) or not isinstance(viewport, dict):
        raise ValueError('Frame and viewport provenance required')
    frame_id, viewport_id = _id(frame.get('id')), _id(viewport.get('id'))
    _size(frame)
    size = _size(viewport)
    if size != state['page_meta']['viewport']:
        raise ValueError('Declared viewport differs from UI viewport')
    digest = frame.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Frame SHA256 required')
    placements = contract.get('placements')
    if not isinstance(placements, list):
        raise ValueError('Complete explicit placements required')
    by_id = {}
    for placement in placements:
        if not isinstance(placement, dict):
            raise ValueError('Invalid placement record')
        eid = _id(placement.get('entity_id'))
        if eid in by_id:
            raise ValueError('Duplicate placement entity')
        by_id[eid] = placement
    ids = {e['id'] for e in state['elements']}
    if set(by_id) != ids:
        raise ValueError('Placement coverage mismatch: missing=%s extra=%s' % (
            sorted(ids - set(by_id)), sorted(set(by_id) - ids)))
    vision = {v['id']: v for v in vision_elements['elements']}
    valid_refs = {'vision:' + vid for vid in vision}
    valid_refs |= {'spoken_intent:' + e['id'] for e in state['elements'] if e.get('origin') == 'spoken'}
    from src.utils.text_evidence_contract import validate_text_evidence
    valid_refs |= validate_text_evidence(contract.get('text_sources', {}), contract.get('text_evidence', []))
    result = copy.deepcopy(state)
    for entity in result['elements']:
        placement = by_id[entity['id']]
        if placement.get('coordinate_space') != 'viewport_px' or placement.get('viewport_id') != viewport_id:
            raise ValueError('Placement has wrong coordinate space or viewport')
        bounds = _bbox(placement.get('bbox'), size['width'], size['height'])
        rounded = [int(round(v)) for v in bounds]
        _bbox(rounded, size['width'], size['height'])
        derivation = placement.get('derivation')
        if not isinstance(derivation, dict) or derivation.get('kind') != 'semantic_layout':
            raise ValueError('Explicit semantic layout derivation required; no implicit photo mapping')
        refs = derivation.get('evidence_refs')
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or ref not in valid_refs for ref in refs
        ) or not isinstance(derivation.get('reason'), str) or not derivation['reason'].strip():
            raise ValueError('Layout evidence references and reason required')
        observations = []
        vid = entity.get('vision_id')
        if vid is not None:
            raw = vision[vid].get('bbox')
            if not isinstance(raw, dict):
                raise ValueError('Normalized observation box required')
            observed = _bbox([raw.get(k) for k in ('x_min', 'y_min', 'x_max', 'y_max')], 1, 1)
            observations.append({'source_ref': 'vision:' + vid, 'coordinate_space': 'image_norm',
                                 'frame_id': frame_id, 'frame_sha256': digest, 'bbox': observed})
        entity['observation_geometry'] = observations
        entity['spatial_info'] = {'bbox': rounded, 'coordinate_space': 'viewport_px',
                                  'viewport_id': viewport_id, 'source': 'explicit_layout_plan',
                                  'derivation': copy.deepcopy(derivation)}
    result['page_meta']['coordinate_contract'] = {
        'version': 'evidence-layout-v1', 'frame': copy.deepcopy(frame),
        'viewport': copy.deepcopy(viewport), 'placement_count': len(by_id),
        'observation_count': sum(len(e['observation_geometry']) for e in result['elements']),
        'status': 'engineering_contract_validated_semantics_not_evaluated',
        'implicit_photo_to_viewport_mapping': False,
        'text_evidence': copy.deepcopy(contract.get('text_evidence', [])),
    }
    return result
