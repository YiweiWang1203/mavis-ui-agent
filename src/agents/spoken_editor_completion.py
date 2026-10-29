"""Bounded explicit editable requirement completion; observations stay separate."""
import copy
import json
import re
from src.agents.input_requirement_binder import input_requirement_slots
from src.utils.coordinate_contract import _bbox


def intersect(a, b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def compile_spoken_editors(state, intent, declaration, *, frame_sha256):
    if not isinstance(frame_sha256,str) or not re.fullmatch('[0-9a-f]{64}',frame_sha256):
        raise ValueError('Frozen full-frame provenance required')
    slots, local_unresolved=input_requirement_slots(intent)
    if not isinstance(declaration,dict) or set(declaration)!={'slots'} or not isinstance(declaration['slots'],list):
        raise ValueError('Expected complete slot decisions')
    lookup={s['requirement_id']:s for s in slots}; seen=set(); result=copy.deepcopy(state)
    originals={e['id']:e for e in state['elements']}; added=[];matched=[];unresolved=copy.deepcopy(local_unresolved)
    width,height=(state['page_meta']['viewport'][k] for k in ('width','height'))
    for row in declaration['slots']:
        if not isinstance(row,dict) or set(row)!={'requirement_id','status','existing_id','observed_bbox','target_bbox'}:
            raise ValueError('Decision schema mismatch')
        rid=row['requirement_id'];status=row['status']
        if not isinstance(rid,str) or rid not in lookup or rid in seen:raise ValueError('Unknown or duplicate requirement')
        seen.add(rid);source=lookup[rid]
        if intent[source['start']:source['end']]!=source['quote']:raise ValueError('Source span mismatch')
        if status in {'existing','unresolved'}:
            if row['observed_bbox'] is not None or row['target_bbox'] is not None:raise ValueError('No layout for uncreated entity')
            eid=row['existing_id']
            if status=='existing':
                if eid not in originals:raise ValueError('Unknown existing entity')
                if originals[eid]['type'] in {'input','textarea'}:matched.append(dict(source,entity_id=eid))
                else:unresolved.append(dict(source,entity_id=eid,reason='existing_non_native_role_outside_completion_scope'))
            else:
                if eid is not None:raise ValueError('Unresolved may not assert identity')
                unresolved.append(dict(source,reason='model_unresolved'))
            continue
        if status!='missing' or row['existing_id'] is not None:raise ValueError('Invalid missing declaration')
        if any(e['type'] in {'input','textarea'} for e in state['elements']):
            raise ValueError('Existing native editor prevents additive completion; no guessed distinction')
        observed=_bbox(row['observed_bbox'],1,1);box=_bbox(row['target_bbox'],width,height)
        if box[2]-box[0]<48 or box[3]-box[1]<24:raise ValueError('Insufficient editable target space')
        if any(intersect(box,e['spatial_info']['bbox']) for e in result['elements']):
            raise ValueError('Completion overlaps existing target entity; no automatic movement')
        eid='spoken_editor_'+rid
        if eid in originals:raise ValueError('Completion identity collision')
        entity={'id':eid,'vision_id':None,'origin':'spoken','type':'input','text':'','label':'文本输入',
                'parent_id':None,'rpa_action':None,'children_ids':[],
                'spatial_info':{'bbox':box,'coordinate_space':'page_global','source':'spoken_editor_target_layout'},
                'source_refs':[{'source':'spoken_intent','id':rid,'start':source['start'],'end':source['end']}],
                'spoken_evidence':copy.deepcopy(source),
                'observation_geometry':[{'coordinate_space':'image_norm','frame_sha256':frame_sha256,'bbox':observed,
                    'status':'model_observation_proposal_requires_semantic_review'}]}
        result['elements'].append(entity);added.append(dict(source,entity_id=eid,observed_bbox=observed,target_bbox=box))
    if seen!=set(lookup):raise ValueError('Missing slot decision is not unresolved')
    if result['elements'][:len(state['elements'])]!=state['elements']:raise ValueError('Original entities changed')
    result.setdefault('page_meta',{})['spoken_editor_completion']={'version':'spoken-editor-v1','source_slots':slots,
        'reviewed_count':len(seen),'added':added,'matched':matched,'unresolved':unresolved,
        'semantic_review_required':True,'implicit_photo_mapping':False,'original_entities_unchanged':True}
    if 'layout_solver' in result['page_meta']:
        result['page_meta']['layout_solver']['element_count']=len(result['elements'])
    return result


def complete_spoken_editors(state, intent, *, image_data_url, frame_sha256, client, model):
    slots,_=input_requirement_slots(intent)
    if not slots:return compile_spoken_editors(state,intent,{'slots':[]},frame_sha256=frame_sha256)
    response=client.chat.completions.create(model=model,temperature=0,max_tokens=8192,timeout=600,
        response_format={'type':'json_object'},messages=[
        {'role':'system','content':'''Review ONLY the immutable explicit editable requirement slots against the complete photo, original speech and existing UI entities. Do not assume the visual inventory is complete. For each slot decide existing, missing, or unresolved. existing must reference its true existing editor entity; do not bind conversation content as editor. missing is allowed only if an editable object is explicitly required and no existing entity represents it. For missing, observe its actual drawing rectangle in the entire PHOTO using normalized [x1,y1,x2,y2] (not target coordinates), and independently propose its appropriate target canvas bbox in pixels respecting spoken regions and page organization. Do not copy photo fractions into target positions. Preserve all existing entities. Target box must be within viewport, width>=48 height>=24, and have NO positive-area intersection with ANY existing bbox (including text); do not move or resize old objects. If unsupported or no compatible space, unresolved. Never invent invisible editor evidence or duplicate an existing editor. Output exactly {"slots":[{"requirement_id":"...","status":"existing|missing|unresolved","existing_id":null,"observed_bbox":null,"target_bbox":null}]}. existing uses an existing ID and null boxes; missing uses null existing_id and two boxes; unresolved uses all three null. Complete every slot exactly once. Do not supply quotes, labels, types, IDs of new objects, or actions; code owns them.'''} ,
        {'role':'user','content':[{'type':'text','text':json.dumps({'original_speech':intent,'immutable_requirements':slots,
            'viewport':state['page_meta']['viewport'],'existing_entities':state['elements']},ensure_ascii=False)},
            {'type':'image_url','image_url':{'url':image_data_url}}]}])
    if response.choices[0].finish_reason=='length':raise ValueError('Completion truncated; no additional attempt')
    declaration=json.loads(response.choices[0].message.content)
    return compile_spoken_editors(state,intent,declaration,frame_sha256=frame_sha256)
