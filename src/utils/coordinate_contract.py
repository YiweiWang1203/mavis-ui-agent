"""D1 opt-in contract: image observations never own viewport placements."""
import copy
import math
import re


class CoordinateResponsibilityError(ValueError):
    """A pre-overwrite coordinate audit failed with machine-readable evidence."""

    def __init__(self, diagnostic):
        self.diagnostic = copy.deepcopy(diagnostic)
        super().__init__(
            'Coordinate responsibility rejected architect placements: '
            f"invalid={diagnostic['invalid_count']}/{diagnostic['element_count']} "
            f"skipped={diagnostic['skipped_count']}"
        )


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


def audit_architect_coordinate_responsibility(state, vision_elements, provenance):
    """Inspect architect geometry before identity compilation can replace it.

    This is a validator, not a mapper.  It requires the caller to declare the
    observed frame and target viewport independently and never infers a space
    from coordinate ranges.  The returned report retains the raw architect
    boxes and gives one denominator over architect elements.
    """
    elements = state.get('elements') if isinstance(state, dict) else None
    if not isinstance(elements, list):
        raise ValueError('Architect state requires an element list')
    vision = vision_elements if isinstance(vision_elements, dict) else {}
    observed = vision.get('elements')
    if not isinstance(observed, list):
        raise ValueError('Vision observations require an element list')
    if not isinstance(provenance, dict):
        provenance = {}

    frame = provenance.get('observation_frame')
    viewport = provenance.get('target_viewport')
    global_issues = []
    try:
        frame_id = _id(frame.get('id'))
        frame_size = _size(frame)
        digest = frame.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Frame SHA256 required')
    except (AttributeError, ValueError) as exc:
        frame_id, frame_size, digest = None, None, None
        global_issues.append({'code': 'invalid_observation_frame', 'detail': str(exc)})
    try:
        viewport_id = _id(viewport.get('id'))
        viewport_size = _size(viewport)
    except (AttributeError, ValueError) as exc:
        viewport_id, viewport_size = None, None
        global_issues.append({'code': 'invalid_target_viewport', 'detail': str(exc)})

    declared_view = state.get('page_meta', {}).get('viewport')
    if viewport_size is not None and declared_view != viewport_size:
        global_issues.append({'code': 'target_viewport_mismatch',
                              'declared': copy.deepcopy(declared_view),
                              'expected': copy.deepcopy(viewport_size)})
    observed_canvas = vision.get('canvas')
    canvas_size = None
    if isinstance(observed_canvas, dict):
        try:
            canvas_size = _size(observed_canvas)
        except ValueError as exc:
            global_issues.append({'code': 'invalid_observation_canvas', 'detail': str(exc)})
    else:
        global_issues.append({'code': 'missing_observation_canvas'})
    if frame_size is not None and canvas_size is not None and frame_size != canvas_size:
        global_issues.append({'code': 'observation_frame_canvas_mismatch',
                              'frame': frame_size, 'canvas': canvas_size})

    visual_ids = [item.get('id') for item in observed if isinstance(item, dict)]
    visual_set = {value for value in visual_ids if isinstance(value, str) and value}
    if len(visual_set) != len(visual_ids):
        global_issues.append({'code': 'invalid_or_duplicate_vision_ids'})
    architect_vision_ids = [item.get('vision_id') for item in elements
                            if isinstance(item, dict) and item.get('vision_id') is not None]
    missing_visual = sorted(visual_set - set(architect_vision_ids))
    extra_visual = sorted(set(architect_vision_ids) - visual_set)
    if missing_visual or extra_visual:
        global_issues.append({'code': 'architect_vision_coverage_mismatch',
                              'missing': missing_visual, 'extra': extra_visual})
    valid_evidence_refs = {'vision:' + value for value in visual_set}
    valid_evidence_refs |= {
        'spoken_intent:' + item['id'] for item in elements
        if isinstance(item, dict) and item.get('origin') == 'spoken'
        and isinstance(item.get('id'), str) and item['id']
    }
    records = []
    valid_count = skipped_count = 0
    for index, element in enumerate(elements):
        issues = []
        if not isinstance(element, dict):
            records.append({'index': index, 'id': None, 'raw_bbox': None,
                            'issues': [{'code': 'invalid_element_record'}]})
            continue
        eid = element.get('id')
        spatial = element.get('spatial_info')
        raw_bbox = spatial.get('bbox') if isinstance(spatial, dict) else None
        if raw_bbox is None:
            skipped_count += 1
            issues.append({'code': 'missing_placement'})
        elif viewport_size is None:
            issues.append({'code': 'target_viewport_unavailable'})
        else:
            try:
                _bbox(raw_bbox, viewport_size['width'], viewport_size['height'])
            except ValueError as exc:
                issues.append({'code': 'invalid_target_bbox', 'detail': str(exc)})
        if not isinstance(spatial, dict) or spatial.get('coordinate_space') != 'viewport_px':
            issues.append({'code': 'missing_or_wrong_coordinate_space',
                           'actual': spatial.get('coordinate_space') if isinstance(spatial, dict) else None})
        if not isinstance(spatial, dict) or spatial.get('viewport_id') != viewport_id:
            issues.append({'code': 'missing_or_wrong_viewport_id',
                           'actual': spatial.get('viewport_id') if isinstance(spatial, dict) else None})
        derivation = spatial.get('derivation') if isinstance(spatial, dict) else None
        refs = derivation.get('evidence_refs') if isinstance(derivation, dict) else None
        if not isinstance(derivation, dict) or derivation.get('kind') != 'semantic_layout':
            issues.append({'code': 'missing_derivation'})
        elif not isinstance(refs, list) or not refs:
            issues.append({'code': 'missing_derivation_sources'})
        else:
            unknown_refs = [ref for ref in refs
                            if not isinstance(ref, str) or ref not in valid_evidence_refs]
            if unknown_refs:
                issues.append({'code': 'unknown_derivation_sources',
                               'references': copy.deepcopy(unknown_refs)})
            if not isinstance(derivation.get('reason'), str) or not derivation['reason'].strip():
                issues.append({'code': 'missing_derivation_reason'})
        vision_id = element.get('vision_id')
        if vision_id is not None and vision_id not in visual_set:
            issues.append({'code': 'unknown_vision_source', 'vision_id': vision_id})
        if not issues:
            valid_count += 1
        records.append({'index': index, 'id': eid, 'vision_id': vision_id,
                        'raw_bbox': copy.deepcopy(raw_bbox), 'issues': issues})

    invalid_count = len(elements) - valid_count
    return {
        'version': 'coordinate-responsibility-audit-v1',
        'status': 'valid' if invalid_count == 0 and not global_issues else 'rejected',
        'element_count': len(elements), 'valid_count': valid_count,
        'invalid_count': invalid_count, 'skipped_count': skipped_count,
        'global_issues': global_issues, 'elements': records,
        'observation_geometry': {'coordinate_space': 'image_norm', 'frame_id': frame_id,
                                 'frame_sha256': digest, 'size': frame_size,
                                 'provenance_trust': 'caller_supplied_not_byte_verified_here'},
        'target_placement': {'coordinate_space': 'viewport_px', 'viewport_id': viewport_id,
                             'size': viewport_size},
        'mapping_strategy': 'pending_user_decision',
        'implicit_photo_to_viewport_mapping': False,
    }


def enforce_architect_coordinate_responsibility(state, vision_elements, provenance):
    diagnostic = audit_architect_coordinate_responsibility(state, vision_elements, provenance)
    if diagnostic['status'] != 'valid':
        raise CoordinateResponsibilityError(diagnostic)
    return diagnostic


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
