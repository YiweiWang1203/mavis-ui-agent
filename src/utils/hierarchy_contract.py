"""Source-preserving hierarchical geometry in page-global coordinates."""
import copy
import math
import os
from collections import defaultdict
from src.utils.pipeline_trace import traced_stage, trace_event

CONTAINERS={'page','container','card','navigation','navigation_bar','toolbar','footer','header','list','modal'}


def box(value):
    if not isinstance(value,list) or len(value)!=4:
        raise ValueError('Expected pixel box')
    if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value):
        raise ValueError('Invalid pixel coordinates')
    b=[int(round(x)) for x in value]
    if b[0]>=b[2] or b[1]>=b[3]:raise ValueError('Nonpositive box')
    return b


@traced_stage('architect.identity_contract')
def build_structure(ui_state,vision_elements, *, coordinate_contract=None):
    result=copy.deepcopy(ui_state)
    view=result.get('page_meta',{}).get('viewport',{})
    if not all(isinstance(view.get(k),int) and not isinstance(view.get(k),bool) and view[k]>0 for k in ('width','height')):
        raise ValueError('Invalid target viewport')
    visual={e['id']:e for e in vision_elements['elements']}
    if len(visual)!=len(vision_elements['elements']):raise ValueError('Duplicate vision ids')
    output=[];aliases={};used=set();original_ids=set()
    for raw in result.get('elements',[]):
        e=copy.deepcopy(raw);old=e.get('id')
        if not isinstance(old,str) or not old or old in original_ids:raise ValueError('Missing or duplicate architect id')
        original_ids.add(old)
        vid=e.get('vision_id')
        if vid is None and old in visual:vid=old
        if vid is not None:
            if vid not in visual or vid in used:raise ValueError('Invalid or reused vision source')
            used.add(vid);e['id']=vid;e['vision_id']=vid
            if coordinate_contract is None:
                b=visual[vid]['bbox'];w,h=view['width'],view['height']
                e.setdefault('spatial_info',{})['bbox']=box([b['x_min']*w,b['y_min']*h,b['x_max']*w,b['y_max']*h])
            e['source_refs']=[{'source':'vision','id':vid}]
        elif e.get('origin')=='spoken' and old.startswith('u_'):
            if coordinate_contract is None:
                e.setdefault('spatial_info',{})['bbox']=box(e.get('spatial_info',{}).get('bbox'))
            e['source_refs']=[{'source':'spoken_intent','id':old}]
        else:raise ValueError('Element has no explicit source')
        aliases[old]=e['id'];output.append(e)
    for vid,v in visual.items():
        if vid not in used:
            b=v['bbox'];w,h=view['width'],view['height']
            output.append({'id':vid,'vision_id':vid,'origin':'vision','type':v['type'],
                'text':v.get('text') or '', 'parent_id':v.get('parent_id'), 'rpa_action':'',
                'source_refs':[{'source':'vision','id':vid}],
                'spatial_info':{} if coordinate_contract is not None else {'bbox':box([b['x_min']*w,b['y_min']*h,b['x_max']*w,b['y_max']*h])}})
    indexed={e['id']:e for e in output}
    if len(indexed)!=len(output):raise ValueError('Canonical identity collision')
    for e in output:
        parent=aliases.get(e.get('parent_id'),e.get('parent_id'))
        if parent is not None and (parent not in indexed or indexed[parent].get('type') not in CONTAINERS):
            raise ValueError('Invalid parent container')
        e['parent_id']=parent;e['children_ids']=[]
    for e in output:
        seen={e['id']};parent=e['parent_id']
        while parent is not None:
            if parent in seen:raise ValueError('Hierarchy cycle')
            seen.add(parent);parent=indexed[parent]['parent_id']
        if e['parent_id'] is not None:indexed[e['parent_id']]['children_ids'].append(e['id'])
    result['elements']=output
    result['page_meta']['structure_contract']={'version':'hierarchy-v1','visual_sources':len(visual),
        'model_sources':len(used),'fallback_sources':len(visual)-len(used)}
    if coordinate_contract is not None:
        from src.utils.coordinate_contract import apply_coordinate_contract
        result = apply_coordinate_contract(result, vision_elements, coordinate_contract)
    return result


def contains(a,b):
    return a[0]<=b[0] and a[1]<=b[1] and a[2]>=b[2] and a[3]>=b[3]


@traced_stage('architect.hierarchy_layout')
def solve_hierarchy(ui_state):
    if ui_state.get('page_meta',{}).get('coordinate_contract',{}).get('version') == 'evidence-layout-v1':
        raise ValueError('Explicit layout plan requires a dedicated compiler; legacy hierarchy fitting is not permitted')
    result=copy.deepcopy(ui_state);view=result['page_meta']['viewport'];index={e['id']:e for e in result['elements']}
    root=[0,0,view['width'],view['height']];done=set();decisions=[]
    mode=os.getenv('UI_HIERARCHY_LAYOUT_MODE','baseline')
    if mode not in {'baseline','container_extent_v1'}:raise ValueError('Unsupported hierarchy layout mode')
    original={eid:box(e['spatial_info']['bbox']) for eid,e in index.items()}
    desired=copy.deepcopy(original);extent_decisions=[]
    if mode=='container_extent_v1':
        children=defaultdict(list)
        for eid,e in index.items():
            if e['parent_id'] is not None:children[e['parent_id']].append(eid)
        visited=set();active=set()
        def expand(eid):
            if eid in visited:return
            if eid in active:raise ValueError('Hierarchy cycle')
            active.add(eid)
            for child in children[eid]:expand(child)
            if children[eid]:
                if index[eid].get('type') not in CONTAINERS:raise ValueError('Invalid extent parent container')
                boxes=[original[eid]]+[desired[c] for c in children[eid]]
                desired[eid]=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
                extent_decisions.append({'id':eid,'children':children[eid],'evidence_bbox':original[eid],
                    'desired_bbox':desired[eid],'reason':'validated_child_extent_union'})
            active.remove(eid);visited.add(eid)
        for eid in index:expand(eid)
    def place(eid):
        if eid in done:return
        e=index[eid];parent=e['parent_id']
        if parent is not None:place(parent)
        bounds=index[parent]['spatial_info']['bbox'] if parent else root
        spatial=e['spatial_info'];evidence=desired[eid]
        w=min(evidence[2]-evidence[0],bounds[2]-bounds[0]);h=min(evidence[3]-evidence[1],bounds[3]-bounds[1])
        # Do not manufacture one-pixel controls to disguise insufficient space.
        if e.get('type') in {'button','input','search_input','search_bar','textarea','select'} and (w<24 or h<24):
            raise ValueError('Insufficient control space in parent')
        x=min(max(evidence[0],bounds[0]),bounds[2]-w);y=min(max(evidence[1],bounds[1]),bounds[3]-h)
        render=[x,y,x+w,y+h]
        spatial.update(evidence_bbox=original[eid],bbox=render,source='hierarchy_layout_v1',coordinate_space='page_global')
        decisions.append({'id':eid,'parent_id':parent,'changed':evidence!=render,'reason':'fit_within_parent' if evidence!=render else 'preserve_evidence'})
        done.add(eid)
    for eid in index:place(eid)
    groups=defaultdict(list);conflicts=[]
    for e in result['elements']:groups[e['parent_id']].append(e)
    for siblings in groups.values():
        for i,a in enumerate(siblings):
            for b in siblings[i+1:]:
                x,y=a['spatial_info']['bbox'],b['spatial_info']['bbox']
                overlap=min(x[2],y[2])>max(x[0],y[0]) and min(x[3],y[3])>max(x[1],y[1])
                if overlap and not (a.get('allow_overlay') is True or b.get('allow_overlay') is True):conflicts.append([a['id'],b['id']])
    result['page_meta']['layout_solver']={'version':'hierarchy-v1','coordinate_space':'page_global',
        'element_count':len(index),'sibling_conflicts':conflicts,'status':'conflicts_reported' if conflicts else 'validated_geometry',
        'extent_policy':mode,'container_extent_decisions':extent_decisions}
    trace_event('architect.hierarchy_layout.decisions',decisions=decisions,sibling_conflicts=conflicts,extent_decisions=extent_decisions)
    return result
