"""Unique literal source anchors need no generative identity selection."""
from src.agents.input_requirement_binder import input_requirement_slots, compile_requirement_bindings


def bind_unique_requirements(state, vision, intent):
    slots,_=input_requirement_slots(intent)
    declarations=[]; decisions=[]
    for slot in slots:
        candidates=[e['id'] for e in vision['elements'] if e.get('type') in {'text','input'}
                    and isinstance(e.get('text'),str) and e['text'] and e['text'] in slot['quote']]
        selected=candidates[0] if len(candidates)==1 else None
        declarations.append({'requirement_id':slot['requirement_id'],'vision_id':selected})
        decisions.append({'requirement_id':slot['requirement_id'],'candidates':candidates,'selected':selected,
                          'reason':'unique_literal_anchor' if selected else 'no_unique_literal_anchor'})
    result=compile_requirement_bindings(state,vision,intent,{'bindings':declarations})
    for item in result['page_meta']['input_requirement_binding']['unresolved']:
        if item.get('reason')=='model_unbound':item['reason']='no_unique_literal_anchor'
    result['page_meta']['unique_requirement_binding']={'version':'unique-literal-v1','decisions':decisions,
        'additional_model_calls':0,'semantic_review_required':True,'missing_entities_created':False}
    return result
