"""Optional, conservative matching of conflicting visual leaves to existing regions.

Containment is a geometric hypothesis, not a semantic confidence probability.
No labels, case IDs, new regions, coordinate corrections or retries are used.
"""
import copy
from src.utils.hierarchy_contract import CONTAINERS, box, contains


def reconcile_parent_geometry(state):
    result = copy.deepcopy(state)
    elements = result['elements']
    index = {e['id']: e for e in elements}
    if len(index) != len(elements):
        raise ValueError('Duplicate IDs')
    view = result['page_meta']['viewport']
    page = [0, 0, view['width'], view['height']]
    boxes = {i: box(e['spatial_info']['bbox']) for i, e in index.items()}
    if any(not contains(page, b) for b in boxes.values()):
        raise ValueError('Observation outside target canvas')
    # Validate the complete original graph before any repair.
    for e in elements:
        seen = {e['id']}
        parent = e.get('parent_id')
        while parent is not None:
            if parent not in index or index[parent].get('type') not in CONTAINERS:
                raise ValueError('Invalid original parent')
            if parent in seen:
                raise ValueError('Original hierarchy cycle')
            seen.add(parent)
            parent = index[parent].get('parent_id')
    original_parents = {i: e.get('parent_id') for i, e in index.items()}
    ledger = []
    for e in elements:
        eid = e['id']; parent = original_parents[eid]
        # Do not reinterpret containers, spoken requirements, or unparented leaves.
        if e.get('origin') != 'vision' or e.get('type') in CONTAINERS or parent is None:
            continue
        if contains(boxes[parent], boxes[eid]):
            continue
        record = {'id': eid, 'original_parent': parent, 'observed_bbox': boxes[eid],
                  'candidate_ids': [], 'accepted_parent': None}
        candidates = []
        for cid, container in index.items():
            if container.get('type') not in CONTAINERS or boxes[cid] == page or cid == eid:
                continue
            if not contains(boxes[cid], boxes[eid]):
                continue
            current = cid; chain_ok = True
            while current is not None:
                if current == eid or not contains(boxes[current], boxes[eid]):
                    chain_ok = False; break
                current = original_parents[current]
            if chain_ok:
                candidates.append(cid)
        # Incomparable overlapping containers and equal boxes are ambiguous.
        innermost = [cid for cid in candidates if not any(
            other != cid and boxes[other] != boxes[cid] and contains(boxes[cid], boxes[other])
            for other in candidates)]
        record['candidate_ids'] = sorted(candidates)
        record['innermost_ids'] = sorted(innermost)
        if len(innermost) == 1:
            e['parent_id'] = innermost[0]
            record.update(accepted_parent=innermost[0], reason='unique_existing_containment_chain')
        else:
            record['reason'] = 'no_unique_supported_region_keep_original'
        ledger.append(record)
    for e in elements:
        e['children_ids'] = []
    for e in elements:
        if e.get('parent_id') is not None:
            index[e['parent_id']]['children_ids'].append(e['id'])
    result['page_meta']['parent_geometry_guard'] = {
        'version':'parent_geometry_v1', 'decisions':ledger,
        'conflicts':len(ledger), 'accepted':sum(r['accepted_parent'] is not None for r in ledger),
        'unresolved':sum(r['accepted_parent'] is None for r in ledger),
        'semantic_validation':'required; containment alone is not semantic proof'}
    return result
