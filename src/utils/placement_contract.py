"""Compile the coordinate boundary before generation; never mutate generated HTML."""
import json
import math

def compile_placement_contract(state):
    if (state.get('page_meta',{}).get('layout_solver') or {}).get('version') != 'hierarchy-v1':
        raise ValueError('Placement contract requires hierarchy-v1')
    rows=[]
    ids=set()
    for e in state['elements']:
        key=e['id']
        if key in ids:
            raise ValueError('Duplicate placement id')
        ids.add(key)
        box=e['spatial_info']['bbox']
        if len(box)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in box):
            raise ValueError('Invalid placement bbox')
        x,y,right,bottom=box
        if right<=x or bottom<=y:
            raise ValueError('Empty placement bbox')
        rows.append({'id':key,'dom_parent':'page-root','semantic_parent':e.get('parent_id'),
                     'style':f'position:absolute;left:{x}px;top:{y}px;width:{right-x}px;height:{bottom-y}px;box-sizing:border-box;margin:0;',
                     'type':e.get('type'),'text':e.get('text','')})
    return {'coordinate_space':'page_global','root_id':'page-root','viewport':state['page_meta']['viewport'],'placements':rows}

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
