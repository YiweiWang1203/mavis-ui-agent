"""Observation-only topology; ambiguity is recorded, never called semantics."""
import copy
import math
from src.utils.symbolic_flow_layout import compile_symbolic_flow


def projection_tree(state, vision):
    observed = {v['id']: v for v in vision['elements']}
    if len(observed) != len(vision['elements']):
        raise ValueError('Duplicate visual source')
    items, seen = [], set()
    for entity in state['elements']:
        eid = entity['id']; vid = entity.get('vision_id') or eid
        if eid in seen or vid not in observed:
            raise ValueError('Missing or duplicate projection identity; no guessed placement')
        seen.add(eid)
        b = observed[vid].get('bbox', {})
        box = [b.get(k) for k in ['x_min', 'y_min', 'x_max', 'y_max']]
        if any(isinstance(x, bool) or not isinstance(x, (float,int)) or not math.isfinite(x) for x in box) or not box[0] < box[2] or not box[1] < box[3]:
            raise ValueError('Invalid projection source geometry')
        items.append({'id':eid,'vision_id':vid,'box':box})
    if not items:
        raise ValueError('Empty projection inventory')
    diagnostics = []
    def bounds(rows):
        return [min(r['box'][0] for r in rows),min(r['box'][1] for r in rows),max(r['box'][2] for r in rows),max(r['box'][3] for r in rows)]
    def build(rows):
        if len(rows)==1:
            r=rows[0]
            return dict(kind='entity',entity_id=r['id'],evidence_refs=['vision:'+r['vision_id']],reason='Observed spatial topology; semantic correctness not implied')
        box=bounds(rows); options=[]
        for axis in (0,1):
            ordered=sorted(rows,key=lambda r:(r['box'][axis],r['box'][axis+2],r['id']))
            for i in range(1,len(rows)):
                left,right=ordered[:i],ordered[i:]
                end=max(r['box'][axis+2] for r in left);start=min(r['box'][axis] for r in right)
                if end<=start:
                    gap=(start-end)/(box[axis+2]-box[axis])
                    options.append((round(gap,12),min(i,len(rows)-i),-axis,-i,axis,left,right))
        rid='projection_'+str(len(diagnostics))
        if options:
            option=max(options,key=lambda o:o[:4]);axis,left,right=option[4:]
            parts=[left,right];kind='observed_non_crossing_cut'
            weights=[bounds(part)[axis+2]-bounds(part)[axis] for part in parts]
            total=sum(weights);weights=[round(w/total,12) for w in weights]
        else:
            axis=0;parts=[[r] for r in sorted(rows,key=lambda r:(r['box'][0]+r['box'][2],r['box'][1]+r['box'][3],r['id']))]
            weights=[1]*len(parts);kind='ambiguous_overlap_uniform_row_default'
        diagnostics.append({'id':rid,'kind':kind,'axis':['row','column'][axis],
            'source_entity_ids':[r['id'] for r in rows], 'source_boxes':{r['id']:copy.deepcopy(r['box']) for r in rows},
            'child_entity_ids':[[r['id'] for r in part] for part in parts], 'weights':weights})
        return dict(kind='split',id=rid,axis=['row','column'][axis],weights=weights,children=[build(part) for part in parts],
            evidence_refs=['vision:'+r['vision_id'] for r in rows],reason=kind+'; source extent weights uncalibrated, not target screen ratios')
    return {'version':'symbolic-flow-v1','root':build(items)}, diagnostics


def compile_projection_flow(state, vision, **kwargs):
    tree, diagnostics=projection_tree(state,vision)
    result=compile_symbolic_flow(tree,state,vision,**kwargs)
    result['page_meta']['projection_flow']={'version':'projection-flow-v1','cuts':diagnostics,
        'ambiguous_groups':sum(d['kind'].startswith('ambiguous') for d in diagnostics),
        'semantic_coverage_evaluated':False,'source_geometry_can_be_wrong':True}
    return result
