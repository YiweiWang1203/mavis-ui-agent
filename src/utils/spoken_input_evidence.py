"""Conservative source-backed input role compilation before fresh rendering."""
import copy
import re
from src.utils.pipeline_trace import traced_stage

EDITABLE_BEHAVIOR_PATTERN = r'输入文字|输入文本|输入内容|填写文字|键入文字|can (?:enter|type)|editable (?:text|input)'
NEGATIVE_INPUT_PATTERN = r'不能|不可以|不可输入|不需要输入|无需输入|只读|read.only|cannot|not editable'


@traced_stage('architect.spoken_input_evidence')
def compile_spoken_inputs(state, vision, intent):
    result=copy.deepcopy(state)
    proposals=result.get('semantic_input_overrides', [])
    if not isinstance(proposals,list):raise ValueError('Invalid semantic input ledger')
    visual={e['id']:e for e in vision['elements']}
    if len(visual)!=len(vision['elements']):raise ValueError('Duplicate vision identity')
    indexed={e.get('vision_id') or e['id']:e for e in result['elements']}
    if len(indexed)!=len(result['elements']):raise ValueError('Duplicate input source identity')
    seen=set();accepted=[];unresolved=[]
    for p in proposals:
        if not isinstance(p,dict) or set(p)!={'vision_id','target_type','evidence_quote'}:
            raise ValueError('Input proposal may only declare source, type and quote')
        vid=p['vision_id']
        if not isinstance(vid,str) or vid not in visual or vid not in indexed or vid in seen:
            raise ValueError('Unknown or repeated input source')
        seen.add(vid)
        if p['target_type']!='input':raise ValueError('Unsupported semantic input target')
        e=indexed[vid];source=visual[vid];q=p['evidence_quote'];label=source.get('text') or ''
        reason=None
        if source.get('type')!='text' or e.get('type')!='text':reason='not_visual_text'
        elif not isinstance(q,str) or not 2<=len(q)<=400 or q not in intent:reason='source_quote_not_found'
        elif not label or label not in q or (e.get('text') or '')!=label:reason='literal_label_not_anchored'
        elif sum((v.get('text') or '')==label for v in visual.values())!=1:reason='ambiguous_literal_label'
        elif re.search(NEGATIVE_INPUT_PATTERN,q,re.I):reason='negative_or_readonly_source'
        elif not re.search(EDITABLE_BEHAVIOR_PATTERN,q,re.I):reason='editable_behavior_not_anchored'
        if reason:
            unresolved.append(dict(p,reason=reason));continue
        e['type']='input'
        e['semantic_type_evidence']={'source_type':'text','source':'spoken_intent','quote':q}
        accepted.append(dict(p,original_type='text'))
    result.setdefault('page_meta',{})['spoken_input_evidence']={
        'version':'spoken_input_v1','proposed_count':len(proposals),'accepted_count':len(accepted),
        'accepted':accepted,'unresolved_count':len(unresolved),'unresolved':unresolved,
        'semantic_review':'required; literal checks are not entailment proof'}
    return result
