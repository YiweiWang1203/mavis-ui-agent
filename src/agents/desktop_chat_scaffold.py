"""Opt-in desktop-chat archetype: bind identity once, compile declared defaults."""
import json
from pathlib import Path
import unicodedata

from src.agents.frozen_region_planner import compile_frozen_regions, frozen_inventory
from src.utils.semantic_page_plan import parse_semantic_json
from src.utils.text_evidence_contract import source_spans

ROLES = ('back', 'search', 'history', 'profile', 'conversation', 'composer_input', 'attachment', 'voice', 'send')


def compile_desktop_chat(binding, state, vision, *, request, speech, frame, viewport):
    if '电脑' not in request + speech or not any(w in request + speech for w in ('聊天', '对话')):
        raise ValueError('Desktop-chat archetype not supported by explicit request')
    if viewport['width'] < 900 or viewport['height'] < 600:
        raise ValueError('Desktop-chat prototype requires desktop canvas')
    if not isinstance(binding, dict) or set(binding) != {'roles', 'unresolved'}:
        raise ValueError('Expected complete roles and unresolved')
    if binding['unresolved'] != []:
        raise ValueError('Unresolved identities; no dropping or guessed role')
    rows = binding['roles']
    if not isinstance(rows, dict) or set(rows) != set(ROLES):
        raise ValueError('All declared semantic roles required')
    entities = {e['id']: e for e in state['elements']}
    if len(entities) != len(state['elements']):
        raise ValueError('Duplicate source identity')
    spans = {s['ref']: s for s in source_spans({'request': request, 'speech': speech})}
    seen = set()
    for role in ROLES:
        row = rows[role]
        if not isinstance(row, dict) or set(row) != {'entity_ids', 'evidence_refs'}:
            raise ValueError('Role must contain only identity list and source refs')
        ids, refs = row['entity_ids'], row['evidence_refs']
        if not isinstance(ids, list) or not ids or (role not in {'history', 'conversation'} and len(ids) != 1):
            raise ValueError('Missing or multiple atomic role identities')
        if not isinstance(refs, list) or not refs or any(not isinstance(r,str) or r not in spans for r in refs):
            raise ValueError('Role requires code-owned text evidence')
        for eid in ids:
            if not isinstance(eid,str) or eid not in entities or eid in seen:
                raise ValueError('Unknown or duplicate role identity')
            seen.add(eid)
    if seen != set(entities):
        raise ValueError('Role inventory incomplete; no hidden omission')
    if entities[rows['composer_input']['entity_ids'][0]]['type'] not in {'input', 'textarea'}:
        raise ValueError('Main input is not native editable; no type repair in layout')
    w,h=viewport['width'],viewport['height']; sidebar=w*.25; main=w-sidebar
    # Fixed archetype defaults, explicitly not ratios inferred from the photograph.
    regions={'sidebar':('page',[0,0,.25,1]),'main':('page',[.25,0,1,1]),
        'sidebar_top':('sidebar',[0,0,1,64/h]), 'history':('sidebar',[0,64/h,1,1-64/h]),
        'profile':('sidebar',[0,1-64/h,1,1]),
        'conversation':('main',[0,0,1,1-128/h]),'composer':('main',[0,1-128/h,1,1]),
        'composer_input':('composer',[16/main,8/128,1-16/main,64/128]),
        'tools':('composer',[16/main,72/128,1-16/main,120/128])}
    role_regions={'back':'sidebar_top','search':'sidebar_top','history':'history','profile':'profile',
        'conversation':'conversation','composer_input':'composer_input','attachment':'tools','voice':'tools','send':'tools'}
    plan={'version':'region-local-v1','root_region_id':'page','regions':[],'placements':[]}
    bounds={'page':[0,0,w,h]}
    all_refs=list(dict.fromkeys(r for row in rows.values() for r in row['evidence_refs']))
    for rid,(parent,box) in regions.items():
        pb=bounds[parent]; pw,ph=pb[2]-pb[0],pb[3]-pb[1]
        bounds[rid]=[pb[0]+box[0]*pw,pb[1]+box[1]*ph,pb[0]+box[2]*pw,pb[1]+box[3]*ph]
        plan['regions'].append(dict(id=rid,parent_id=parent,coordinate_space='region_local',bbox=box,
            proportion_basis='default',evidence_refs=all_refs,reason='Declared desktop-chat archetype; semantic references do not establish measured proportions'))
    footprints=[]
    for role in ROLES:
        row=rows[role];rid=role_regions[role];rb=bounds[rid];rw,rh=rb[2]-rb[0],rb[3]-rb[1]
        for i,eid in enumerate(row['entity_ids']):
            box=[0,0,1,1]
            if role in {'back','search'}:
                box=[0 if role=='back' else .5,0,.5 if role=='back' else 1,1]
            elif role in {'attachment','voice','send'}:
                box={'attachment':[0,0,.2,1],'voice':[.6,0,.8,1],'send':[.8+8/rw,0,1,1]}[role]
            elif role in {'history','conversation'}:
                n=len(row['entity_ids']);box=[0,i/n,1,(i+1)/n]
            if entities[eid]['type']=='button':
                cw,ch=(box[2]-box[0])*rw,(box[3]-box[1])*rh
                caption=str(entities[eid].get('text') or '')
                preferred=max(48,24+sum(14 if unicodedata.east_asian_width(c) in {'W','F'} else 8 for c in caption))
                fw,fh=min(cw,preferred),min(ch,48)
                dx,dy=(cw-fw)/2/rw,(ch-fh)/2/rh
                box=[box[0]+dx,box[1]+dy,box[2]-dx,box[3]-dy]
                footprints.append(dict(entity_id=eid,preferred_width_px=preferred,preferred_height_px=48))
            plan['placements'].append(dict(entity_id=eid,region_id=rid,coordinate_space='region_local',
                bbox=box,evidence_refs=row['evidence_refs'],reason='Role '+role+' bound to declared archetype; manually review entailment'))
    result=compile_frozen_regions(plan,state,vision,request=request,speech=speech,frame=frame,viewport=viewport)
    result['page_meta']['desktop_chat_scaffold']={'version':'desktop-chat-scaffold-v1','binding':binding,
        'source_spans':list(spans.values()),'plan':plan,'footprints':footprints,'semantic_review_required':True,
        'proportions_are_design_defaults':True,'new_semantic_entities':0,'dom_nesting_implied':False}
    return result


def generate_desktop_chat(state, vision, *, request, speech, frame, viewport, image_data_url, client, model, output):
    payload={'request':request,'speech':speech,'immutable_entities':frozen_inventory(state),
        'source_spans':source_spans({'request':request,'speech':speech}), 'roles':list(ROLES)}
    out=Path(output)
    (out/'role_binding_input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    prompt=('Bind existing UI entity IDs to the supplied desktop-chat semantic roles using the original intent and image. '
        'Do not generate geometry, new entities, changed text/type/action, or quotes. Return exactly roles and unresolved. '
        'roles must contain all nine supplied role names, each with entity_ids (a list) and evidence_refs '
        '(existing request/speech span refs supporting that role). Every entity must occur exactly once, either in a role or unresolved. '
        'history/conversation may have several IDs; other roles require one. Missing roles use empty entity_ids. '
        'profile is the user personal-information entry; conversation is message content; composer_input is the main editable input, not search. '
        'If unsupported, leave unresolved. IDs and source references are not themselves proof of semantic fit. JSON only.')
    response=client.chat.completions.create(model=model,temperature=.3,max_tokens=8192,timeout=600,
        response_format={'type':'json_object'},messages=[{'role':'system','content':prompt},
        {'role':'user','content':[{'type':'text','text':json.dumps(payload,ensure_ascii=False)},
                                {'type':'image_url','image_url':{'url':image_data_url}}]}])
    raw=response.choices[0].message.content or ''
    (out/'role_binding_raw.txt').write_text(raw,encoding='utf-8')
    if response.choices[0].finish_reason=='length':raise ValueError('Role binding truncated; no retry')
    parsed=parse_semantic_json(raw)
    (out/'role_binding_parsed.json').write_text(json.dumps(parsed,ensure_ascii=False,indent=2),encoding='utf-8')
    result=compile_desktop_chat(parsed,state,vision,request=request,speech=speech,frame=frame,viewport=viewport)
    (out/'ui_state.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
