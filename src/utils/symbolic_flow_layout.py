"""Compile sourced grouping/order to pixels without model-authored coordinates."""
import copy
import math
import unicodedata

from src.agents.frozen_region_planner import compile_frozen_regions, frozen_inventory
from src.utils.text_evidence_contract import source_spans


def expand_flat_program(program):
    """Validate references and construct the tree; never fill missing leaves."""
    if not isinstance(program, dict) or set(program) != {'version', 'nodes'} or program['version'] != 'symbolic-flat-v1':
        raise ValueError('Expected symbolic-flat-v1 nodes only')
    rows = program['nodes']
    if not isinstance(rows, list) or not rows or len(rows) > 1024:
        raise ValueError('Invalid flat node count')
    nodes, children = {}, {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid flat node')
        common = {'id', 'kind', 'parent_id', 'weight', 'evidence_refs', 'reason'}
        expected = common | ({'axis'} if row.get('kind') == 'split' else {'entity_id'})
        if set(row) != expected or row.get('kind') not in {'split', 'entity'}:
            raise ValueError('Invalid flat fields; coordinates not allowed')
        rid, parent, weight = row['id'], row['parent_id'], row['weight']
        if not isinstance(rid, str) or not rid or rid in nodes or (parent is not None and (not isinstance(parent, str) or not parent)):
            raise ValueError('Invalid flat node identity')
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 <= weight <= 1000000:
            raise ValueError('Invalid flat weight')
        nodes[rid] = row
        children.setdefault(parent, []).append(rid)
    roots = children.get(None, [])
    if len(roots) != 1:
        raise ValueError('Exactly one flat root required')
    for rid, row in nodes.items():
        parent = row['parent_id']
        if parent is not None and (parent not in nodes or nodes[parent]['kind'] != 'split'):
            raise ValueError('Unknown or non-group flat parent')
        if row['kind'] == 'entity' and rid in children:
            raise ValueError('Entity cannot own flat nodes')
    seen = set()
    def build(rid, depth=0):
        if rid in seen or depth > 32:
            raise ValueError('Flat cycle or depth exceeded')
        seen.add(rid)
        row = nodes[rid]
        item = {k: copy.deepcopy(row[k]) for k in ['kind', 'evidence_refs', 'reason']}
        if row['kind'] == 'entity':
            item['entity_id'] = row['entity_id']
        else:
            kids = children.get(rid, [])
            if not kids:
                raise ValueError('Empty flat group')
            item.update(id=rid, axis=row['axis'], weights=[nodes[k]['weight'] for k in kids], children=[build(k, depth + 1) for k in kids])
        return item
    root = build(roots[0])
    if seen != set(nodes):
        raise ValueError('Unreachable flat nodes or disconnected cycle')
    return {'version': 'symbolic-flow-v1', 'root': root}


def compile_symbolic_flow(tree, state, vision, *, request, speech, frame, viewport, button_footprints=False):
    if not isinstance(tree, dict) or set(tree) != {'version', 'root'} or tree['version'] != 'symbolic-flow-v1':
        raise ValueError('Expected symbolic-flow-v1 with root only')
    inventory = {e['id']: e for e in frozen_inventory(state)}
    allowed = {'vision:' + v['id'] for v in vision['elements']}
    allowed |= {s['ref'] for s in source_spans({'request': request, 'speech': speech})}
    allowed |= {'spoken_intent:' + e['id'] for e in state['elements'] if e.get('origin') == 'spoken'}
    seen_nodes, seen_entities, measurements, records = set(), set(), {}, []
    gap, minimum = 8, 24

    def measure(node, depth=0):
        if not isinstance(node, dict) or depth > 32 or len(records) >= 1024:
            raise ValueError('Invalid or oversized symbolic tree')
        kind = node.get('kind')
        expected = ({'kind', 'entity_id', 'evidence_refs', 'reason'} if kind == 'entity' else
                    {'kind', 'id', 'axis', 'weights', 'children', 'evidence_refs', 'reason'})
        if set(node) != expected or kind not in {'entity', 'split'}:
            raise ValueError('Symbolic nodes cannot contain coordinates or semantic edits')
        refs = node['evidence_refs']
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in allowed for r in refs):
            raise ValueError('Unknown symbolic evidence')
        if not isinstance(node['reason'], str) or not node['reason'].strip():
            raise ValueError('Symbolic grouping requires a reason')
        records.append(node)
        if kind == 'entity':
            eid = node['entity_id']
            if not isinstance(eid, str) or eid not in inventory or eid in seen_entities:
                raise ValueError('Unknown or duplicated symbolic entity')
            seen_entities.add(eid)
            key = 'leaf__' + eid
            size = [minimum, minimum]
        else:
            key = node['id']
            if not isinstance(key, str) or not key.strip() or key.startswith('leaf__') or key in seen_nodes:
                raise ValueError('Invalid or duplicated symbolic group')
            seen_nodes.add(key)
            children, weights = node['children'], node['weights']
            if node['axis'] not in {'row', 'column'} or not isinstance(children, list) or not children or not isinstance(weights, list) or len(weights) != len(children):
                raise ValueError('Symbolic split requires axis and per-child weights')
            if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 or w > 1000000 for w in weights) or sum(weights) <= 0:
                raise ValueError('Invalid remaining-space weights')
            sizes = [measure(c, depth + 1) for c in children]
            axis = 0 if node['axis'] == 'row' else 1
            size = [max(s[0] for s in sizes), max(s[1] for s in sizes)]
            size[axis] = sum(s[axis] for s in sizes) + gap * (len(children) - 1)
        measurements[id(node)] = (key, size)
        return size

    root = tree['root']
    required = measure(root)
    if seen_entities != set(inventory):
        raise ValueError('Symbolic tree inventory incomplete')
    if required[0] > viewport['width'] or required[1] > viewport['height']:
        raise ValueError('Insufficient canvas for declared grouping; no squeezing')
    root_id = measurements[id(root)][0]
    plan = {'version': 'region-local-v1', 'root_region_id': root_id, 'regions': [], 'placements': []}
    allocation = []
    footprints = []

    def place(node, bounds, parent=None, local=None):
        key, size = measurements[id(node)]
        if parent is not None:
            plan['regions'].append({'id': key, 'parent_id': parent, 'coordinate_space': 'region_local',
                'bbox': local, 'proportion_basis': 'default', 'evidence_refs': copy.deepcopy(node['evidence_refs']),
                'reason': 'Declared symbolic grouping with uncalibrated flex weights and code minimum/gap defaults: ' + node['reason']})
        allocation.append({'id': key, 'bounds': bounds, 'minimum': size})
        if node['kind'] == 'entity':
            eid = node['entity_id']
            local_box = [0, 0, 1, 1]
            if button_footprints and inventory[eid]['type'] == 'button':
                width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
                caption = str(inventory[eid].get('text') or '')
                # Explicit prototype defaults, not source geometry or font measurement.
                preferred_width = max(48, 24 + sum(14 if unicodedata.east_asian_width(c) in {'W', 'F'} else 8 for c in caption))
                actual_width, actual_height = min(width, preferred_width), min(height, 48)
                dx, dy = (1-actual_width/width)/2, (1-actual_height/height)/2
                local_box = [round(v,12) for v in [dx,dy,1-dx,1-dy]]
                footprints.append({'entity_id': eid, 'allocated_bounds': list(bounds),
                    'preferred_width_px': preferred_width, 'preferred_height_px': 48,
                    'local_bbox': local_box, 'caption_width_is_estimate': True})
            plan['placements'].append({'entity_id': node['entity_id'], 'region_id': key,
                'coordinate_space': 'region_local', 'bbox': local_box,
                'evidence_refs': copy.deepcopy(node['evidence_refs']), 'reason': node['reason']})
            return
        axis = 0 if node['axis'] == 'row' else 1
        start, end = bounds[axis], bounds[axis + 2]
        children, weights = node['children'], node['weights']
        mins = [measurements[id(c)][1][axis] for c in children]
        spare = end - start - sum(mins) - gap * (len(children) - 1)
        if spare < -1e-6:
            raise ValueError('Insufficient group space; no clipping')
        cursor = start
        for child, weight, child_min in zip(children, weights, mins):
            span = child_min + max(0, spare) * weight / sum(weights)
            box = list(bounds); box[axis] = cursor; box[axis + 2] = cursor + span
            normalized = [(box[0] - bounds[0]) / (bounds[2] - bounds[0]),
                          (box[1] - bounds[1]) / (bounds[3] - bounds[1]),
                          (box[2] - bounds[0]) / (bounds[2] - bounds[0]),
                          (box[3] - bounds[1]) / (bounds[3] - bounds[1])]
            # Roundoff only, never permit or clamp materially out-of-bounds geometry.
            if any(x < -1e-12 or x > 1 + 1e-12 for x in normalized):
                raise ValueError('Allocation outside parent')
            normalized = [round(x, 12) for x in normalized]
            place(child, box, key, normalized)
            cursor += span + gap

    place(root, [0, 0, viewport['width'], viewport['height']])
    result = compile_frozen_regions(plan, state, vision, request=request, speech=speech, frame=frame, viewport=viewport)
    result['page_meta']['symbolic_flow'] = {'version': 'symbolic-flow-v1', 'minimum_px': minimum,
        'gap_px': gap, 'weight_meaning': 'remaining_space_after_child_minima_and_gaps',
        'proportions_calibrated': False, 'defaults_are_design_not_measurement': True,
        'allocations': allocation, 'source_tree': copy.deepcopy(tree)}
    if button_footprints:
        result['page_meta']['button_footprints'] = {'version': 'atomic-button-footprint-v1',
            'policy_is_design_default_not_observation': True, 'alignment': 'center',
            'preferred_height_px': 48, 'wide_character_px': 14, 'narrow_character_px': 8,
            'horizontal_padding_px': 24, 'minimum_preferred_width_px': 48, 'placements': footprints}
    return result
