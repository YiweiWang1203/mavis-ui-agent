"""Source-derived final consumer projection and read-only observed-box checks."""
import copy
import math
from collections import Counter

PROJECTION_SEPARATOR = "\n\nDeterministic final consumer projection (derived only from the UI-State above):\n"
EDIT_TYPES = {'input','input_field','textarea','search_input'}


def compile_consumer_projection(state):
    view=state['page_meta']['viewport'];width,height=view['width'],view['height']
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in (width,height)):
        raise ValueError('INVALID_VIEWPORT')
    objects=[];seen=set()
    for e in state['elements']:
        identity=e.get('id')
        if not isinstance(identity,str) or not identity or identity in seen:raise ValueError('INVALID_OR_DUPLICATE_ID')
        seen.add(identity)
        functional=e.get('functional_content') or {}
        box=copy.deepcopy(functional.get('render_bbox',e.get('spatial_info',{}).get('bbox')))
        if not isinstance(box,list) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box):raise ValueError('UNKNOWN_FINAL_BOX:'+identity)
        if not 0<=box[0]<box[2]<=width or not 0<=box[1]<box[3]<=height:raise ValueError('INVALID_FINAL_BOX:'+identity)
        action=e.get('rpa_action')
        if isinstance(action,str) and action.startswith('display_'):role='display_only'
        elif e.get('type') in EDIT_TYPES:role='native_edit'
        elif action and e.get('type') in {'button','list','select','link','image'}:role='user_action'
        else:role='unknown'
        objects.append({'id':identity,'source_type':e.get('type'),'source_action':action,'semantic_parent_id':e.get('parent_id'),
                        'target_css_xyxy':box,'left':box[0],'top':box[1],'width':box[2]-box[0],'height':box[3]-box[1],
                        'role':role,'box_source':'functional_content.render_bbox' if functional.get('render_bbox') is not None else 'spatial_info.bbox'})
    return {'version':'consumer-projection-v1','coordinate_space':'page_root_global_css_px','viewport':copy.deepcopy(view),'objects':objects}


def compare_browser_observation(projection, observation, tolerance_css_px=0.001):
    """Consumes actual browser snapshots; never infers computed boxes from HTML."""
    rows=[];observed=observation.get('objects',[]);counts=Counter(x.get('id') for x in observed)
    for e in projection['objects']:
        row={'stage':'coder_browser','object_id':e['id'],'expected':[e['left'],e['top'],e['width'],e['height']],'actual':None,'status':'UNKNOWN','failure_code':'MISSING_BROWSER_EVIDENCE'}
        matches=[x for x in observed if x.get('id')==e['id']]
        if counts[e['id']]>1:row.update(status='FAIL',failure_code='DUPLICATE_RENDERED_ID')
        elif matches:
            box=matches[0].get('box');row['actual']=box
            if isinstance(box,list) and len(box)==4 and all(isinstance(v,(float,int)) and math.isfinite(v) for v in box):
                row['max_abs_delta']=max(abs(a-b) for a,b in zip(row['expected'],box))
                row.update(status='PASS' if row['max_abs_delta']<=tolerance_css_px else 'FAIL',failure_code='' if row['max_abs_delta']<=tolerance_css_px else 'GLOBAL_RECT_MISMATCH')
        rows.append(row)
    return {'basis':'actual browser box snapshot only','tolerance_css_px':tolerance_css_px,'rows':rows,
            'display_behavior':'UNKNOWN_requires_ordinary_browser_click','business_behavior':'UNKNOWN_requires_browser_acceptance'}


def compare_display_click(projection, object_id, before, after, operation=None):
    item=next((x for x in projection['objects'] if x['id']==object_id),None)
    if item is None or item['role']!='display_only':raise ValueError('NOT_EXPLICIT_DISPLAY_OBJECT')
    if not isinstance(operation,dict) or operation.get('type')!='ordinary_click' or operation.get('target_id')!=object_id or not operation.get('evidence_ref'):
        return {'object_id':object_id,'status':'UNKNOWN','failure_code':'NO_ORDINARY_CLICK_EVIDENCE'}
    a=[x for x in before.get('objects',[]) if x.get('id')==object_id]
    b=[x for x in after.get('objects',[]) if x.get('id')==object_id]
    if len(a)!=1 or len(b)!=1 or not isinstance(a[0].get('text'),str) or not isinstance(b[0].get('text'),str):return {'object_id':object_id,'status':'UNKNOWN','failure_code':'MISSING_CLICK_EVIDENCE'}
    return {'object_id':object_id,'expected':'ordinary click leaves display text unchanged','before':a[0].get('text'),'after':b[0].get('text'),
            'status':'PASS' if a[0].get('text')==b[0].get('text') else 'FAIL','failure_code':'' if a[0].get('text')==b[0].get('text') else 'DISPLAY_TEXT_MUTATED',
            'operation_evidence':operation['evidence_ref'],'scope':'text invariance after evidenced ordinary click only; no proof of absence of all hidden side effects'}
