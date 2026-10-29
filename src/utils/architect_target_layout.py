"""Validate existing target placements without treating observations as CSS."""
import copy

from src.utils.coordinate_contract import _bbox
from src.utils.hierarchy_contract import build_structure, contains
from src.utils.pipeline_trace import trace_event


def compile_architect_target_layout(raw_state, vision, *, frame, viewport):
    placements=[]
    visual={e['id'] for e in vision['elements']}
    for e in raw_state.get('elements',[]):
        vid=e.get('vision_id')
        if vid is None and e.get('id') in visual:
            vid=e['id']
        eid=vid if vid is not None else e.get('id')
        bounds=e.get('spatial_info',{}).get('bbox')
        _bbox(bounds,viewport['width'],viewport['height'])
        if e.get('type') in {'button','input','search_input','search_bar','textarea','select'} and (bounds[2]-bounds[0]<24 or bounds[3]-bounds[1]<24):
            raise ValueError('Explicit target placement has insufficient control space')
        ref='vision:'+vid if isinstance(vid,str) else 'spoken_intent:'+str(eid)
        submitted_derivation=e.get('spatial_info',{}).get('derivation')
        derivation=copy.deepcopy(submitted_derivation) if isinstance(submitted_derivation,dict) else {
            'kind':'semantic_layout','evidence_refs':[ref],
            'reason':'Existing target bbox from this fresh architect response; source reference does not prove layout correctness'}
        placements.append({'entity_id':eid,'coordinate_space':'viewport_px','viewport_id':viewport['id'],
            'bbox':copy.deepcopy(bounds),'derivation':derivation})
    contract={'version':'evidence-layout-v1','frame':copy.deepcopy(frame),'viewport':copy.deepcopy(viewport),
              'placements':placements}
    result=build_structure(raw_state,vision,coordinate_contract=contract)
    index={e['id']:e for e in result['elements']}
    outside=[];overlaps=[]
    for e in result['elements']:
        parent=index.get(e.get('parent_id'))
        if parent and not contains(parent['spatial_info']['bbox'],e['spatial_info']['bbox']):
            outside.append({'child':e['id'],'parent':parent['id'],'reason':'target_child_outside_declared_parent; not moved'})
    for i,a in enumerate(result['elements']):
        for b in result['elements'][i+1:]:
            if a.get('parent_id')!=b.get('parent_id') or a.get('allow_overlay') or b.get('allow_overlay'):
                continue
            x,y=a['spatial_info']['bbox'],b['spatial_info']['bbox']
            if min(x[2],y[2])>max(x[0],y[0]) and min(x[3],y[3])>max(x[1],y[1]):
                overlaps.append([a['id'],b['id']])
    result['page_meta']['architect_target_layout']={'version':'architect-target-layout-v1',
        'status':'target_geometry_validated_semantics_not_evaluated','parent_containment_conflicts':outside,
        'sibling_conflicts':overlaps,'observations_used_as_target_coordinates':False,
        'hidden_clamping':False,'missing_semantics_repaired':False,
        'submitted_derivation_preserved':all(isinstance(
            e.get('spatial_info',{}).get('derivation'),dict) for e in raw_state.get('elements',[])),
        'compiler_derivation_fallback_count':sum(not isinstance(
            e.get('spatial_info',{}).get('derivation'),dict) for e in raw_state.get('elements',[]))}
    trace_event('architect.explicit_target_layout',raw_state=raw_state,coordinate_contract=contract,output=result)
    return result
