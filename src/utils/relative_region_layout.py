"""Compile a source-supported row/column tree without editing source identities."""
import copy
import math
from src.utils.hierarchy_contract import CONTAINERS


def compile_relative_layout(state, transcript, tree):
    result = copy.deepcopy(state)
    nodes = {e['id']: e for e in result['elements']}
    if not nodes or len(nodes) != len(result['elements']) or any(k == 'page' or k.startswith('layout_') for k in nodes):
        raise ValueError('Unique nonreserved source objects required')
    view = result['page_meta']['viewport']
    if not all(isinstance(view.get(k), int) and not isinstance(view[k], bool) and view[k] > 0 for k in ['width','height']):
        raise ValueError('Explicit target viewport required')
    seen, used, groups, decisions = set(), set(), [], []

    def visit(row, bounds, semantic_parent, group_path, depth):
        if depth > 12 or len(seen) >= len(nodes)+21:
            raise ValueError('Relative tree exceeds fixed structural limits')
        if not isinstance(row, dict) or set(row) != {'id','axis','weight','quote','children'}:
            raise ValueError('Expected complete relative tree node')
        key, children = row['id'], row['children']
        if not isinstance(key, str) or key in seen or not isinstance(children, list):
            raise ValueError('Invalid or repeated tree identity')
        seen.add(key)
        weight = row['weight']
        if isinstance(weight, bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or not 0 < weight <= 100:
            raise ValueError('Relative weight must be finite, positive and at most 100')
        if key == 'page':
            if depth != 0 or row['quote'] is not None:
                raise ValueError('Page must be the root and cannot supply invented evidence')
        elif key not in nodes and not key.startswith('layout_'):
            raise ValueError('Unknown object; no automatic parent creation')
        if children:
            if row['axis'] not in {'row','column'}:
                raise ValueError('Branch needs explicit row or column')
            if key in nodes and nodes[key]['type'] not in CONTAINERS:
                raise ValueError('Interactive or image object cannot become a container')
            if key != 'page':
                quote = row['quote']
                if not isinstance(quote,str) or not quote or transcript.count(quote) != 1:
                    raise ValueError('Each group requires a unique verbatim transcript quote')
                start = transcript.index(quote)
                groups.append({'id':key,'axis':row['axis'],'quote':quote,'source_start':start,'source_end':start+len(quote),
                    'bbox':list(bounds),'layout_only':key not in nodes,'parent_layout_group':group_path[-1] if group_path else 'page'})
            group_path = group_path+[key]
        elif row['axis'] is not None or row['quote'] is not None or key not in nodes:
            raise ValueError('Only existing objects may be leaves, without layout declarations')
        if key in nodes:
            used.add(key); e=nodes[key]; previous=list(e['spatial_info']['bbox'])
            e['spatial_info']['relative_layout_input_bbox']=previous
            e['spatial_info']['bbox']=list(bounds)
            e['parent_id']=semantic_parent
            e['relative_layout_path']=list(group_path)
            decisions.append({'id':key,'old_bbox':previous,'new_bbox':list(bounds),'semantic_parent':semantic_parent})
            if children: semantic_parent=key
        if not children: return
        weights=[]
        for child in children:
            value = child.get('weight') if isinstance(child,dict) else None
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 < value <= 100:
                raise ValueError('Child relative weight invalid')
            weights.append(value)
        axis=0 if row['axis']=='row' else 1
        total=sum(weights); cursor=bounds[axis]; length=bounds[axis+2]-cursor
        for index,child in enumerate(children):
            end=bounds[axis+2] if index==len(children)-1 else cursor+length*weights[index]/total
            child_box=list(bounds);child_box[axis]=cursor;child_box[axis+2]=end
            if end<=cursor:raise ValueError('Degenerate relative partition')
            visit(child,child_box,semantic_parent,group_path,depth+1);cursor=end

    if not isinstance(tree,dict) or tree.get('id')!='page':raise ValueError('Expected page root')
    visit(tree,[0,0,view['width'],view['height']],None,[],0)
    if used != set(nodes):raise ValueError('Every source object must appear exactly once')
    for e in nodes.values():e['children_ids']=[]
    for e in nodes.values():
        if e['parent_id'] is not None:nodes[e['parent_id']]['children_ids'].append(e['id'])
    result['page_meta']['relative_region_layout']={'version':'relative_region_v1','tree':copy.deepcopy(tree),
        'groups':groups,'decisions':decisions,'new_ui_objects':0,
        'limits':'Layout-only groups are not detected objects; quote validation is lexical, not semantic proof; DOM placement stays flat'}
    result['page_meta']['layout_solver']={'version':'hierarchy-v1','coordinate_space':'page_global','placement_mechanism':'relative_region_v1'}
    return result
