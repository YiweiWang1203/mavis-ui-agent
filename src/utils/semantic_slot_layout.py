"""Keep the complete fresh object inventory; compile bounded source-backed groups."""
import copy
import math
from src.utils.hierarchy_contract import CONTAINERS


def compile_semantic_slots(state, transcript, groups):
    result=copy.deepcopy(state)
    nodes={e['id']:e for e in result['elements']}
    if not nodes or len(nodes)!=len(result['elements']):raise ValueError('Unique source inventory required')
    view=state['page_meta']['viewport']; original={k:list(e['spatial_info']['bbox']) for k,e in nodes.items()}
    for box in original.values():
        if (len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box)
            or not 0<=box[0]<box[2]<=view['width'] or not 0<=box[1]<box[3]<=view['height']):
            raise ValueError('Valid in-canvas source slots required')
    if not isinstance(groups,list) or len(groups)>20:raise ValueError('Bounded group list required')
    assigned=set();ids=set();ledger=[]
    for group in groups:
        if not isinstance(group,dict) or set(group)!={'id','children','axis','quote'}:raise ValueError('Complete group contract required')
        key,children,axis,quote=(group[k] for k in ['id','children','axis','quote'])
        if not isinstance(key,str) or key in ids:raise ValueError('Unique group identity required')
        ids.add(key)
        actual=key in nodes
        if actual and nodes[key]['type'] not in CONTAINERS:raise ValueError('Parent is not an existing legal container')
        if not actual and not key.startswith('layout_'):raise ValueError('No unknown UI parent creation')
        if axis not in [None,'row','column']:raise ValueError('Invalid group axis')
        if not isinstance(quote,str) or not quote or transcript.count(quote)!=1:raise ValueError('Unique verbatim source quote required')
        if not isinstance(children,list) or not children or any(not isinstance(c,str) or c not in nodes for c in children):raise ValueError('Existing children required')
        if len(set(children))!=len(children) or key in children or assigned.intersection(children):raise ValueError('Conflicting child assignments')
        assigned.update(children)
        positions=[]
        if axis is not None:
            coordinate=0 if axis=='row' else 1; perpendicular=1-coordinate
            if min(original[c][perpendicular+2] for c in children)<=max(original[c][perpendicular] for c in children):
                raise ValueError('Ordered group is not a single observed row or column')
            source_order=sorted(children,key=lambda c:(original[c][coordinate]+original[c][coordinate+2])/2)
            centers=[(original[c][coordinate]+original[c][coordinate+2])/2 for c in source_order]
            if len(set(centers))!=len(centers):raise ValueError('Ambiguous source slot order')
            for child,slot_id in zip(children,source_order):
                nodes[child]['spatial_info']['bbox']=list(original[slot_id])
                positions.append({'id':child,'slot_source_id':slot_id,'bbox':list(original[slot_id])})
        if actual:
            for child in children:nodes[child]['parent_id']=key
        start=transcript.index(quote)
        ledger.append({**copy.deepcopy(group),'layout_only':not actual,'source_start':start,'source_end':start+len(quote),'slot_assignments':positions})
    for key,e in nodes.items():
        seen={key};parent=e.get('parent_id')
        while parent is not None:
            if parent in seen:raise ValueError('Cross-group or original parent cycle')
            if parent not in nodes or nodes[parent]['type'] not in CONTAINERS:raise ValueError('Invalid semantic parent')
            seen.add(parent);parent=nodes[parent].get('parent_id')
    for e in nodes.values():e['children_ids']=[]
    for e in nodes.values():
        if e.get('parent_id') is not None:nodes[e['parent_id']]['children_ids'].append(e['id'])
    def expand(key):
        e=nodes[key];box=list(e['spatial_info']['bbox'])
        for child in e['children_ids']:
            c=expand(child);box=[min(box[0],c[0]),min(box[1],c[1]),max(box[2],c[2]),max(box[3],c[3])]
        e['spatial_info']['bbox']=box
        return box
    for key,e in nodes.items():
        if e.get('parent_id') is None:expand(key)
    decisions=[]
    for key,e in nodes.items():
        if e['spatial_info']['bbox']!=original[key]:
            e['spatial_info']['semantic_slot_input_bbox']=original[key]
            decisions.append({'id':key,'original_bbox':original[key],'new_bbox':e['spatial_info']['bbox'],'reason':'observed-slot assignment and/or verified-child extent'})
    result['page_meta']['semantic_slot_layout']={'version':'semantic_slots_v1','groups':ledger,'decisions':decisions,
        'assigned_ids':sorted(assigned),'unassigned_preserved_ids':sorted(set(nodes)-assigned),'source_count':len(nodes),
        'new_objects':0,'limitation':'Unassigned objects retained, not silently covered; verbatim evidence is not semantic proof'}
    result['page_meta']['layout_solver']={'version':'hierarchy-v1','coordinate_space':'page_global','placement_mechanism':'semantic_slots_v1'}
    return result
