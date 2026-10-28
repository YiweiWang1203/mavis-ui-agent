"""Compile explicit region-local plans; never infer layout from photo position."""
import copy

from src.utils.coordinate_contract import _bbox, _id, _size
from src.utils.hierarchy_contract import CONTAINERS, build_structure, contains


def _refs(record, allowed):
    refs = record.get('evidence_refs')
    if not isinstance(refs, list) or not refs or any(
        not isinstance(ref, str) or ref not in allowed for ref in refs
    ):
        raise ValueError('Region layout requires existing evidence references')
    if not isinstance(record.get('reason'), str) or not record['reason'].strip():
        raise ValueError('Region layout requires a decision reason')
    return copy.deepcopy(refs)


def _local(record):
    if record.get('coordinate_space') != 'region_local':
        raise ValueError('Expected region_local coordinates; image coordinates are not layout')
    return _bbox(record.get('bbox'), 1, 1)


def _map(local, bounds):
    x, y, right, bottom = bounds
    width, height = right - x, bottom - y
    return [x + local[0] * width, y + local[1] * height,
            x + local[2] * width, y + local[3] * height]


def _pixels(bounds, viewport):
    rounded = [int(round(x)) for x in bounds]
    return _bbox(rounded, viewport['width'], viewport['height'])


def _intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _outside(a, b):
    return [side for side, invalid in zip(('left', 'top', 'right', 'bottom'),
            (b[0] < a[0], b[1] < a[1], b[2] > a[2], b[3] > a[3])) if invalid]


def compile_region_structure(ui_state, vision_elements, *, frame, viewport, region_plan):
    """Return an opt-in structure and audit, preserving all semantic decisions.

    This compiles declared proportions, not their semantic correctness. Plans
    and original observations remain read-only. Conflicts produce a diagnostic
    structure and no automatic refit/reparent; no user HTML is generated here.
    """
    if not isinstance(region_plan, dict) or region_plan.get('version') != 'region-local-v1':
        raise ValueError('Unknown region plan version')
    _id(viewport.get('id'))
    size = _size(viewport)
    root = _id(region_plan.get('root_region_id'))
    records = region_plan.get('regions')
    placements = region_plan.get('placements')
    if not isinstance(records, list) or not isinstance(placements, list):
        raise ValueError('Regions and complete placements required')
    if len(records) > 128 or len(placements) > 512:
        raise ValueError('Region prototype size limit exceeded')
    allowed = {'vision:' + v['id'] for v in vision_elements['elements']}
    allowed |= {'spoken_intent:' + e['id'] for e in ui_state['elements'] if e.get('origin') == 'spoken'}
    regions = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid region record')
        rid = _id(record.get('id'))
        if rid == root or rid in regions:
            raise ValueError('Duplicate or redefined root region')
        regions[rid] = record
    bounds = {root: [0, 0, size['width'], size['height']]}
    paths = {root: [root]}
    ledger = [{'region_id': root, 'parent_id': None, 'bbox': bounds[root],
               'basis': 'target_canvas_not_observed_sketch_boundary'}]
    active = set()
    defaults = []

    def resolve(rid):
        if rid in bounds:
            return
        if rid not in regions:
            raise ValueError('Unknown parent region: ' + str(rid))
        if rid in active:
            raise ValueError('Region hierarchy cycle')
        if len(active) >= 32:
            raise ValueError('Region depth limit exceeded')
        active.add(rid)
        record = regions[rid]
        parent = _id(record.get('parent_id'))
        resolve(parent)
        local = _local(record)
        refs = _refs(record, allowed)
        basis = record.get('proportion_basis')
        if basis not in {'observed_relative', 'explicit_requirement', 'default'}:
            raise ValueError('Explicit proportion basis required')
        if basis == 'default':
            defaults.append({'region_id': rid, 'reason': record['reason']})
        bounds[rid] = _map(local, bounds[parent])
        _pixels(bounds[rid], size)
        paths[rid] = paths[parent] + [rid]
        ledger.append({'region_id': rid, 'parent_id': parent, 'local_bbox': local,
                       'bbox': _pixels(bounds[rid], size), 'proportion_basis': basis,
                       'evidence_refs': refs, 'reason': record['reason']})
        active.remove(rid)

    for rid in regions:
        resolve(rid)
    compiled, membership = [], {}
    for record in placements:
        if not isinstance(record, dict):
            raise ValueError('Invalid local placement')
        eid, rid = _id(record.get('entity_id')), _id(record.get('region_id'))
        if eid in membership:
            raise ValueError('Duplicate entity region membership')
        if rid not in bounds:
            raise ValueError('Unknown placement region')
        local = _local(record)
        refs = _refs(record, allowed)
        membership[eid] = rid
        compiled.append({'entity_id': eid, 'coordinate_space': 'viewport_px',
            'viewport_id': viewport['id'], 'bbox': _pixels(_map(local, bounds[rid]), size),
            'derivation': {'kind': 'semantic_layout', 'reason': record['reason'],
                           'evidence_refs': refs, 'region_path': paths[rid], 'local_bbox': local,
                           'method': 'nested_region_affine_v1'}})
    contract = {'version': 'evidence-layout-v1', 'frame': copy.deepcopy(frame),
                'viewport': copy.deepcopy(viewport), 'placements': compiled}
    # Identity validation and exact inventory coverage are still authoritative.
    structure = build_structure(ui_state, vision_elements, coordinate_contract=contract)
    conflicts = []
    region_ids = list(regions)
    for i, left in enumerate(region_ids):
        for right in region_ids[i + 1:]:
            if left in paths[right] or right in paths[left]:
                continue
            a, b = _pixels(bounds[left], size), _pixels(bounds[right], size)
            if _intersects(a, b):
                conflicts.append({'kind': 'region_extent_overlap', 'regions': [left, right],
                    'beyond_first_region_sides': _outside(a, b),
                    'review': 'Review region proportions/overlap intent against evidence; no auto refit'})
    entities = {e['id']: e for e in structure['elements']}
    for entity in structure['elements']:
        eid = entity['id']
        rid = membership[eid]
        entity['layout_region_id'] = rid
        box = entity['spatial_info']['bbox']
        parent = entity['parent_id']
        if parent is not None:
            parent_region = membership[parent]
            parent_box = entities[parent]['spatial_info']['bbox']
            if parent_region not in paths[rid] or not contains(parent_box, box):
                conflicts.append({'kind': 'semantic_parent_layout_conflict', 'entity_id': eid,
                    'parent_id': parent, 'region_id': rid, 'parent_region_id': parent_region,
                    'outside_parent_sides': _outside(parent_box, box),
                    'review': 'Review parent membership or extent; preserve child position and semantic parent'})
        if entity.get('type') in {'button', 'input', 'search_input', 'search_bar', 'textarea', 'select'}:
            if box[2] - box[0] < 24 or box[3] - box[1] < 24:
                conflicts.append({'kind': 'insufficient_control_space', 'entity_id': eid,
                                  'review': 'Increase available layout space or revise supported constraints'})

    def semantic_ancestor(parent_id, child):
        current = child['parent_id']
        while current is not None:
            if current == parent_id:
                return True
            current = entities[current]['parent_id']
        return False

    items = list(entities.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            ab, bb = a['spatial_info']['bbox'], b['spatial_info']['bbox']
            legitimate_parent = (
                a.get('type') in CONTAINERS and semantic_ancestor(a['id'], b) and contains(ab, bb)
            ) or (b.get('type') in CONTAINERS and semantic_ancestor(b['id'], a) and contains(bb, ab))
            if _intersects(ab, bb) and not legitimate_parent:
                conflicts.append({'kind': 'entity_extent_overlap', 'entities': [a['id'], b['id']],
                    'cross_region': membership[a['id']] != membership[b['id']],
                    'review': 'Inspect actual occlusion, grouping or duplicate identity; geometry overlap alone is not browser proof'})
    audit = {'version': 'region-local-v1', 'coordinate_space': 'viewport_px',
        'region_ledger': ledger, 'membership': membership, 'conflicts': conflicts,
        'default_proportions': defaults, 'semantic_correctness_evaluated': False,
        'user_effect_evaluated': False, 'automatic_refit': False,
        'status': 'compiled_conflicts' if conflicts else (
            'compiled_default_proportions' if defaults else 'compiled_geometry_semantics_unverified')}
    structure['page_meta']['region_layout'] = audit
    return structure
