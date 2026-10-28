"""Narrow, opt-in role grammar; never infer a missing widget or specific field."""
import copy
import hashlib
import re
from src.agents.input_requirement_binder import input_requirement_slots

GENERIC_ROLE = re.compile(r'^(?:用户|我的|本人|主)?(?:输入框|文本框)$')
SPECIFIC_FIELD = re.compile(r'(?:搜索|密码|验证码|昵称|代理|agent)\s*(?:的)?(?:输入框|文本框)', re.I)


def compile_unique_editable_role(state, vision, intent):
    slots, unresolved = input_requirement_slots(intent)
    visual = {v['id']:v for v in vision['elements']}
    indexed = {e.get('vision_id') or e['id']:e for e in state['elements']}
    if len(visual)!=len(vision['elements']) or len(indexed)!=len(state['elements']):
        raise ValueError('Duplicate editable role identity')
    # Count all generic roles, including an ineligible type, to avoid selecting
    # the convenient text object when another visual candidate is present.
    candidates = [v for v in visual.values() if GENERIC_ROLE.fullmatch(v.get('text') or '')]
    result = copy.deepcopy(state)
    target = {e.get('vision_id') or e['id']:e for e in result['elements']}
    accepted, native, bindings = [], [], []
    for slot in slots:
        quote = slot['quote']; reason = None
        if not re.search(r'输入框|文本框',quote):reason='no_generic_component_in_source'
        elif SPECIFIC_FIELD.search(quote):reason='specific_field_context_not_resolved'
        elif len(candidates)!=1:reason='missing_or_ambiguous_generic_role'
        else:
            v=candidates[0];eid=v['id'];e=target.get(eid)
            if e is None:reason='visual_identity_missing_in_state'
            elif v.get('type') not in {'text','input'} or indexed[eid].get('type')!=v['type']:reason='ineligible_or_disagreeing_source_type'
            elif e.get('text')!=v.get('text'):reason='source_caption_changed'
            else:
                evidence=dict(slot,vision_id=eid,source_caption=v['text'],anchor_kind='unique_generic_user_input_role')
                bindings.append(evidence)
                if v['type']=='input':native.append(evidence)
                elif e['type']=='text':
                    e['type']='input'
                    e['semantic_type_evidence']={'source_type':'text','source':'verbatim_requirement_and_unique_generic_role','quote':quote,'start':slot['start'],'end':slot['end']}
                    accepted.append(evidence)
                # Repeated sentences about the same source retain bindings,
                # but only one object transition is counted.
        if reason:unresolved.append(dict(slot,reason=reason))
    result.setdefault('page_meta',{})['editable_role_anchor']={'version':'unique-editable-role-v1',
        'intent_sha256':hashlib.sha256(intent.encode()).hexdigest(),'source_slots':slots,
        'eligible_slots':len(slots),'generic_candidates':[v['id'] for v in candidates],
        'bindings':bindings,'bound_slots':len(bindings),'accepted':accepted,'accepted_type_changes':len(accepted),
        'already_native':native,'native_confirmations':len(native),'unresolved':unresolved,'unresolved_count':len(unresolved),
        'semantic_review_required':True,'coverage':'explicit editable sentences and narrow generic-role grammar only'}
    return result
