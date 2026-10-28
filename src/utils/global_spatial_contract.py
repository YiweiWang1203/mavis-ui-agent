"""Compile image -> drawn page -> region -> existing object coordinates.

No HTML input, no clipping to disguise conflicts, no semantic type edits.
An axis-aligned page approximation is explicit, not perspective correction.
"""
import copy
import math


def normalized_box(value):
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value
    ):
        raise ValueError('Invalid normalized box')
    if not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1):
        raise ValueError('Normalized box outside image')
    return list(value)


def inside(parent, child):
    return parent[0] <= child[0] and parent[1] <= child[1] and parent[2] >= child[2] and parent[3] >= child[3]


def relative(child, parent):
    return [(child[0]-parent[0])/(parent[2]-parent[0]),
            (child[1]-parent[1])/(parent[3]-parent[1]),
            (child[2]-parent[0])/(parent[2]-parent[0]),
            (child[3]-parent[1])/(parent[3]-parent[1])]


def compile_global_spatial(state, intent, declaration):
    if not isinstance(declaration, dict) or set(declaration) != {'page_bbox', 'regions', 'placements'}:
        raise ValueError('Expected page, regions, placements only')
    page = normalized_box(declaration['page_bbox'])
    result = copy.deepcopy(state)
    original = {e['id']: e for e in state['elements']}
    if len(original) != len(state['elements']):
        raise ValueError('Duplicate original ID')
    regions = {}; order = []
    for row in declaration['regions']:
        if set(row) != {'id', 'parent_id', 'label', 'evidence_quote', 'bbox'}:
            raise ValueError('Invalid region declaration')
        key = row['id']; parent = row['parent_id']; quote = row['evidence_quote']
        if not isinstance(key, str) or not key.startswith('u_region_') or key in original or key in regions:
            raise ValueError('Invalid region identity')
        if parent is not None and parent not in regions:
            raise ValueError('Regions must declare parents before children')
        if not isinstance(quote, str) or not quote.strip() or quote not in intent:
            raise ValueError('Region source is not original intent')
        if not isinstance(row['label'], str) or not row['label'].strip():
            raise ValueError('Empty region label')
        b = normalized_box(row['bbox'])
        if not inside(regions[parent]['bbox'] if parent else page, b):
            raise ValueError('Region outside declared parent')
        regions[key] = row; order.append(key)
    view = result['page_meta']['viewport']; width, height = view['width'], view['height']
    if (width, height) not in {(1440,900),(375,812)}:
        raise ValueError('Expected explicit standard viewport')
    def pixels(b):
        r = relative(b,page)
        value = [round(r[0]*width),round(r[1]*height),round(r[2]*width),round(r[3]*height)]
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError('Rounded box has no area')
        return value
    # Semantic region labels remain metadata: never paint extra label text over controls.
    compiled = []
    for key in order:
        r = regions[key]
        compiled.append({'id':key,'origin':'spoken','type':'container','text':'','region_label':r['label'],
            'parent_id':r['parent_id'],'rpa_action':'',
            'source_refs':[{'source':'spoken_intent','quote':r['evidence_quote']}],
            'spatial_info':{'bbox':pixels(r['bbox']),'image_bbox':r['bbox'],
                'parent_local_bbox':relative(r['bbox'],regions[r['parent_id']]['bbox'] if r['parent_id'] else page),
                'coordinate_space':'page_global','source':'global_spatial_v1'}})
    seen = set(); changes = []
    for row in declaration['placements']:
        if set(row) != {'id','region_id','bbox'} or row['id'] not in original or row['id'] in seen:
            raise ValueError('Invalid or duplicate element placement')
        key = row['id']; parent = row['region_id']; b = normalized_box(row['bbox'])
        if parent is not None and parent not in regions:
            raise ValueError('Unknown region assignment')
        bounds = regions[parent]['bbox'] if parent else page
        if not inside(bounds,b):
            raise ValueError('Element outside declared region; no silent clamping')
        e = copy.deepcopy(original[key]); old = copy.deepcopy(e['spatial_info'])
        e['parent_id'] = parent
        e['spatial_info'] = {'bbox':pixels(b),'image_bbox':b,'parent_local_bbox':relative(b,bounds),
                            'coordinate_space':'page_global','source':'global_spatial_v1',
                            'previous_spatial_info':old}
        compiled.append(e); seen.add(key)
        changes.append({'id':key,'old_bbox':old['bbox'],'new_bbox':e['spatial_info']['bbox'],
                        'old_parent':original[key].get('parent_id'),'new_parent':parent})
    if seen != set(original):
        raise ValueError('Missing existing object placement')
    indexed = {e['id']:e for e in compiled}
    for e in compiled:
        e['children_ids'] = []
    for e in compiled:
        if e['parent_id'] is not None:
            indexed[e['parent_id']]['children_ids'].append(e['id'])
    result['elements'] = compiled
    result['page_meta']['global_spatial_contract'] = {
        'version':'global_spatial_v1','page_bbox_image_normalized':page,
        'region_count':len(regions),'placed_existing_count':len(seen),'changes':changes,
        'limits':'Axis-aligned page mapping; semantic region quotes and image localization require human review. No perspective correction. No missing object recovery.'}
    # Report all sibling collisions, including new region-region collisions, without moving anything.
    conflicts = []
    for i,a in enumerate(compiled):
        for b in compiled[i+1:]:
            if a['parent_id'] != b['parent_id']: continue
            x,y = a['spatial_info']['bbox'],b['spatial_info']['bbox']
            if min(x[2],y[2])>max(x[0],y[0]) and min(x[3],y[3])>max(x[1],y[1]):
                conflicts.append([a['id'],b['id']])
    result['page_meta']['layout_solver'] = {'version':'hierarchy-v1','coordinate_space':'page_global',
        'element_count':len(compiled),'sibling_conflicts':conflicts,
        'status':'conflicts_reported' if conflicts else 'validated_geometry','extent_policy':'global_spatial_v1'}
    return result
