"""Compile the coordinate boundary before generation; never mutate generated HTML."""
import json
import math

def compile_placement_contract(state):
    meta = state.get('page_meta', {})
    explicit = meta.get('coordinate_contract')
    if explicit is not None:
        from src.utils.coordinate_contract import _size, _id
        if not isinstance(explicit, dict) or explicit.get('version') != 'evidence-layout-v1' or explicit.get('status') != 'engineering_contract_validated_semantics_not_evaluated':
            raise ValueError('Placement requires a validated explicit coordinate contract')
        viewport = explicit.get('viewport', {})
        viewport_id = _id(viewport.get('id'))
        size = _size(viewport)
        if size != meta.get('viewport') or explicit.get('placement_count') != len(state['elements']):
            raise ValueError('Explicit placement viewport or inventory count mismatch')
        frame = explicit.get('frame', {})
        import re
        _id(frame.get('id')); _size(frame)
        if not isinstance(frame.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', frame['sha256']):
            raise ValueError('Explicit placement requires frame provenance')
    elif (meta.get('layout_solver') or {}).get('version') != 'hierarchy-v1':
        raise ValueError('Placement contract requires hierarchy-v1')
    rows=[]
    ids=set()
    for e in state['elements']:
        key=e['id']
        if key in ids:
            raise ValueError('Duplicate placement id')
        ids.add(key)
        box=e['spatial_info']['bbox']
        if explicit is not None:
            from src.utils.coordinate_contract import _bbox
            spatial = e['spatial_info']
            if spatial.get('coordinate_space') != 'viewport_px' or spatial.get('viewport_id') != viewport_id or spatial.get('source') != 'explicit_layout_plan':
                raise ValueError('Explicit placement has wrong coordinate space or viewport source')
            derivation = spatial.get('derivation', {})
            if derivation.get('kind') != 'semantic_layout' or not derivation.get('evidence_refs') or not isinstance(derivation.get('reason'), str) or not derivation['reason'].strip():
                raise ValueError('Explicit placement lacks layout derivation')
            _bbox(box, size['width'], size['height'])
        if len(box)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in box):
            raise ValueError('Invalid placement bbox')
        x,y,right,bottom=box
        if right<=x or bottom<=y:
            raise ValueError('Empty placement bbox')
        rows.append({'id':key,'dom_parent':'page-root','semantic_parent':e.get('parent_id'),
                     'style':f'position:absolute;left:{x}px;top:{y}px;width:{right-x}px;height:{bottom-y}px;box-sizing:border-box;margin:0;',
                     'type':e.get('type'),'text':e.get('text','')})
    return {'coordinate_space':'viewport_px' if explicit is not None else 'page_global','root_id':'page-root','viewport':state['page_meta']['viewport'],'placements':rows}

def placement_instructions(state):
    manifest=compile_placement_contract(state)
    return ("\nCOMPILED PLACEMENT CONTRACT. This overrides earlier placement and nesting advice. "
            "Every listed element MUST be a direct DOM child of #page-root, regardless of semantic_parent. "
            "Semantic parents belong in data-parent-id only. NEVER nest positioned children under a card/navigation. "
            "For example, child top=568 and parent top=528 means child style top:568px directly under page-root, NOT 1096px after nesting. "
            "Copy each compiled inline style exactly; add colors/fonts without overriding position, dimensions, margin or box-sizing. "
            "Set html/body margin:0 and root position:relative with the compiled viewport. "
            "Do not depend on CDN CSS for the coordinate reset. Render container backgrounds before their children. "
            "Keep original types and actions; this contract changes coordinate implementation only.\n"+
            json.dumps(manifest,ensure_ascii=False))


INPUT_TYPES={'input':'text','text_input':'text','search_input':'search','search_bar':'search','password_input':'password','email_input':'email','number_input':'number'}
REGION_TYPES={'container','card','navigation','navigation_bar','nav_bar','toolbar','header','footer','image','avatar','modal'}

def compile_component_contract(state):
    # Geometry remains owned by the placement compiler. No content-based case rules.
    compile_placement_contract(state)
    rows=[]
    for e in state['elements']:
        kind=e.get('type','');label=e.get('text') or e.get('label') or ''
        row={'id':e['id'],'source_type':kind,'label':label,'tag':'div','feedback':'none'}
        if kind in INPUT_TYPES or kind=='textarea':
            row.update(tag='textarea' if kind=='textarea' else 'input',input_type=INPUT_TYPES.get(kind),
                       disabled=e.get('disabled') is True,readonly=e.get('readonly') is True,
                       placeholder=e.get('placeholder') or '',affordance='visible border and focus outline')
        elif kind=='button' or (e.get('rpa_action') and kind not in {'text','image','avatar'}):
            row.update(tag='button',button_type='button',action=e.get('rpa_action'),
                       feedback='labelled click acknowledgement only; no invented business success',
                       affordance='visible border, contrasting label, pointer and focus outline')
        elif kind in REGION_TYPES:
            row.update(affordance='visible subtle border/background, no invented image content')
        elif kind=='divider':
            row.update(affordance='visible separator')
        rows.append(row)
    return rows

def component_instructions(state):
    return ("\nCOMPILED COMPONENT CONTRACT. Copy the tag and behavior for each id below. "
            "A search_bar is an editable input, NEVER an empty div. Put its id on the operative native control. "
            "Preserve placement manifest style exactly, adding visible borders/backgrounds with border-box. "
            "Keep input native focus/typing; do not attach click alerts to inputs or clear their values. "
            "For button tags, bind an actual click handler. If an explicit action exists preserve it; "
            "otherwise button type itself supports a minimal labelled click acknowledgement. "
            "Show an alert with the corresponding existing button label (e.g. Clicked: + label, localized to page locale), "
            "without claiming a backend operation succeeded. Do not leave handler as console.log only. "
            "No new pages, backend, elements or business behavior. Passive regions stay passive. "
            "Render every drawn passive region with a visible boundary or subtle background, not blank whitespace. "
            "Do not change bbox to accommodate padding; inline sizes are border-box. "
            "Return complete raw HTML with working handlers, not a report.\n"+
            json.dumps(compile_component_contract(state),ensure_ascii=False))
