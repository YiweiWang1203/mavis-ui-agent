"""Compile explicit reviewed interaction groups into non-overlapping render surfaces.

Observed spatial_info and semantic parents are never changed. Group membership is
supplied evidence, not inferred from geometry, labels, or case identity.
"""
import copy
import math
from src.utils.pipeline_trace import trace_event

class FunctionalContentRejected(ValueError):
    pass


def _overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def compile_functional_content(state):
    from src.utils.layout_solver import _line_count
    groups=state.get('interaction_groups',[])
    if not isinstance(groups,list):raise FunctionalContentRejected('GROUPS_NOT_LIST')
    if not groups:return copy.deepcopy(state)
    result=copy.deepcopy(state);by_id={e['id']:e for e in result['elements']}
    view=result['page_meta']['viewport'];used=set();group_ids=set();records=[]
    for group in groups:
        if not isinstance(group,dict) or group.get('kind')!='composer' or not group.get('id'):
            raise FunctionalContentRejected('INVALID_GROUP_KIND_OR_ID')
        if group['id'] in group_ids:raise FunctionalContentRejected('DUPLICATE_GROUP_ID')
        group_ids.add(group['id'])
        evidence=group.get('evidence',{})
        if (evidence.get('status')!='reviewed_structure' or not evidence.get('review_ref')
            or not evidence.get('source_refs') or evidence.get('origin')!='manual_structure_annotation'):
            raise FunctionalContentRejected('UNREVIEWED_GROUP')
        edit=group.get('editable_id');left=group.get('left_tools');right=group.get('right_tools')
        if not isinstance(left,list) or not isinstance(right,list) or not left+right:
            raise FunctionalContentRejected('EXPLICIT_TOOL_ROLES_REQUIRED')
        ids=[edit]+left+right
        if any(not isinstance(i,str) or i not in by_id for i in ids) or len(set(ids))!=len(ids) or used.intersection(ids):
            raise FunctionalContentRejected('INVALID_OR_REUSED_MEMBER')
        used.update(ids)
        if by_id[edit]['type'] not in {'input','input_field','textarea','search_input'} or any(by_id[i]['type']!='button' for i in left+right):
            raise FunctionalContentRejected('ROLE_TYPE_MISMATCH')
        boxes={i:list(by_id[i]['spatial_info']['bbox']) for i in ids}
        env=[min(b[0] for b in boxes.values()),min(b[1] for b in boxes.values()),max(b[2] for b in boxes.values()),max(b[3] for b in boxes.values())]
        if group.get('footprint_policy')!='union_of_source_boxes':raise FunctionalContentRejected('UNKNOWN_FOOTPRINT_POLICY')
        metrics=group.get('style_metrics',{})
        if set(metrics)!={'border_px','content_inset_px','caret_px'} or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in metrics.values()):
            raise FunctionalContentRejected('INVALID_STYLE_METRICS')
        # Preserve source width/height and y; re-seat tools in explicit source order.
        render={};cursor=env[0]
        for i in left:
            b=boxes[i];w=b[2]-b[0];render[i]=[cursor,b[1],cursor+w,b[3]];cursor+=w
        text_left=cursor;cursor=env[2]
        for i in reversed(right):
            b=boxes[i];w=b[2]-b[0];render[i]=[cursor-w,b[1],cursor,b[3]];cursor-=w
        b=boxes[edit];render[edit]=[max(b[0],text_left),b[1],min(b[2],cursor),b[3]]
        inset=metrics['border_px']+metrics['content_inset_px'];e=render[edit]
        content=[e[0]+inset,e[1]+inset,e[2]-inset,e[3]-inset]
        font=by_id[edit].get('typography',{}).get('font_size_px',16)
        if content[2]-content[0]<font+metrics['caret_px'] or content[3]-content[1]<font*1.5:
            raise FunctionalContentRejected('INSUFFICIENT_EDITABLE_CAPACITY')
        for i,b in render.items():
            if not (0<=b[0]<b[2]<=view['width'] and 0<=b[1]<b[3]<=view['height']):
                raise FunctionalContentRejected('RENDER_OUTSIDE_VIEWPORT')
            for j,c in render.items():
                if i!=j and _overlap(b,c):raise FunctionalContentRejected('FUNCTIONAL_SURFACES_INTERSECT')
            for other in result['elements']:
                if other['id'] in ids:continue
                # Explicit declared ancestor backgrounds may contain the group.
                ancestors=set();p=by_id[i].get('parent_id')
                while p in by_id and p not in ancestors:
                    ancestors.add(p);p=by_id[p].get('parent_id')
                ob=other.get('functional_content',{}).get('render_bbox',other['spatial_info']['bbox'])
                if other['id'] not in ancestors and _overlap(b,ob):
                    raise FunctionalContentRejected('GROUP_EXTERNAL_OBSTRUCTION')
        for i in ids:
            element=by_id[i];rb=render[i]
            element['functional_content']={'version':'functional-content-v1','group_ref':group['id'],
                'role':'editable' if i==edit else 'tool','render_bbox':rb,'source_bbox':boxes[i],
                'change_reason':'explicit_reviewed_group_functional_exclusion','coordinate_space':'target_px_xyxy'}
            if i==edit:
                element['functional_content'].update(editable_content_rect=content,style_metrics=copy.deepcopy(metrics))
                element['typography']['line_count']=_line_count(str(element.get('text') or ''),content[2]-content[0],font)
                element['typography']['wrap']=False
        records.append({'group_ref':group['id'],'source_union_footprint':env,'policy':'engineering_union_not_user_container_GT',
                        'render_surfaces':render,'editable_content_rect':content,'manual_structure_annotation':True})
    result['page_meta']['functional_content']={'version':'functional-content-v1','status':'applied',
          'group_count':len(groups),'manual_structure_annotation':True,'records':records}
    trace_event('architect.functional_content',records=records)
    return result
