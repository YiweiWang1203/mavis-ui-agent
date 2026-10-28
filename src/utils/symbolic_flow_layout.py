"""Compile sourced grouping/order to pixels without model-authored coordinates."""
import copy
import math

from src.agents.frozen_region_planner import compile_frozen_regions, frozen_inventory
from src.utils.text_evidence_contract import source_spans


def compile_symbolic_flow(tree, state, vision, *, request, speech, frame, viewport):
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

    def place(node, bounds, parent=None, local=None):
        key, size = measurements[id(node)]
        if parent is not None:
            plan['regions'].append({'id': key, 'parent_id': parent, 'coordinate_space': 'region_local',
                'bbox': local, 'proportion_basis': 'default', 'evidence_refs': copy.deepcopy(node['evidence_refs']),
                'reason': 'Declared symbolic grouping with uncalibrated flex weights and code minimum/gap defaults: ' + node['reason']})
        allocation.append({'id': key, 'bounds': bounds, 'minimum': size})
        if node['kind'] == 'entity':
            plan['placements'].append({'entity_id': node['entity_id'], 'region_id': key,
                'coordinate_space': 'region_local', 'bbox': [0, 0, 1, 1],
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
    return result
