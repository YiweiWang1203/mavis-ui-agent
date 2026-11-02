"""Opt-in relation/tree consistency, never semantic inference or tree repair."""
import copy
import os
from src.utils.pipeline_trace import trace_event


def enabled():
    mode=os.getenv('UI_REGION_RELATION_MODE','off')
    if mode not in {'off','relation_first_v1'}:
        raise ValueError('INVALID_REGION_RELATION_MODE')
    if mode!='off' and os.getenv('UI_REGION_TREE_MODE','off')!='region_tree_v1':
        raise ValueError('RELATION_PLAN_REQUIRES_REGION_TREE')
    return mode!='off'


class RegionRelationError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics=copy.deepcopy(diagnostics)
        super().__init__('RELATION_TREE_CONFLICT')


def verify_relation_plan(state, vision, intent):
    # Invoked only after existing tree/source/cycle/order checks pass.
    from src.utils.region_tree_contract import evidence
    plan=state.get('relation_plan')
    trace_event('region_relations.before',relation_plan=plan)
    if not isinstance(plan,dict) or set(plan)!={'version','relations'} or plan.get('version')!='spatial-relations-v1':
        raise ValueError('SINGLE_RELATION_PLAN_REQUIRED')
    claims=plan.get('relations')
    if not isinstance(claims,list):raise ValueError('RELATION_LIST_REQUIRED')
    nodes={r['id']:r for r in state['region_contract']['regions']}
    regions=set(nodes);nodes.update({e['id']:e for e in state['elements']})
    parents=state['region_layout']['parent_by_id']
    visual_ids={v['id'] for v in vision['elements']}
    def path(identity):
        result=[]
        while identity is not None:
            result.append(identity);identity=parents[identity]
        return list(reversed(result))
    records=[];problems=[];seen=set();claim_ids=set()
    for i,claim in enumerate(claims):
        if not isinstance(claim,dict) or set(claim)!={'id','kind','subject','object','status','evidence'}:
            raise ValueError('EXPLICIT_RELATION_FIELDS_REQUIRED')
        cid=claim['id'];a=claim['subject'];b=claim['object'];kind=claim['kind'];status=claim['status']
        if not isinstance(cid,str) or not cid.startswith('rel_') or cid in claim_ids:raise ValueError('INVALID_RELATION_ID')
        claim_ids.add(cid)
        if not isinstance(a,str) or not isinstance(b,str) or a not in nodes or b not in nodes or a==b:
            raise ValueError('INVALID_RELATION_ENDPOINTS')
        if kind not in {'left_of','above','contains'}:raise ValueError('UNSUPPORTED_SPATIAL_RELATION')
        if status not in {'proposed','unknown'}:raise ValueError('INVALID_RELATION_CLAIM_STATUS')
        key=(kind,a,b)
        if key in seen:raise ValueError('DUPLICATE_RELATION_CLAIM')
        seen.add(key)
        resolved=evidence(claim['evidence'],intent,visual_ids)
        record={'relation_id':cid,'kind':kind,'subject':a,'object':b,
                'declared_status':status,'evidence':resolved,'semantic_support':'UNKNOWN',
                'source_coverage':'NOT_VERIFIED; existence of claims/quotes does not prove completeness or meaning'}
        if status=='unknown':
            record['consistency']='UNKNOWN_NOT_ENFORCED'
            records.append(record);continue
        pa,pb=path(a),path(b)
        if kind=='contains':
            consistent=a in regions and a in pb[:-1]
            record['tree_fact']={'subject_is_region':a in regions,'object_ancestor_path':pb}
        else:
            shared=0
            while shared<min(len(pa),len(pb)) and pa[shared]==pb[shared]:shared+=1
            if shared==min(len(pa),len(pb)):
                consistent=False;record['tree_fact']={'reason':'ANCESTOR_NOT_DISTINCT_LAYOUT_BRANCHES','subject_path':pa,'object_path':pb}
            else:
                lca=pa[shared-1];branch_a=pa[shared];branch_b=pb[shared]
                direction=nodes[lca]['layout']['direction'];oa=nodes[branch_a]['order'];ob=nodes[branch_b]['order']
                record['tree_fact']={'lowest_common_ancestor':lca,'direction':direction,
                    'subject_branch':branch_a,'object_branch':branch_b,'subject_order':oa,'object_order':ob}
                consistent=direction==('row' if kind=='left_of' else 'column') and oa<ob
        record['consistency']='PROPOSED_CONSISTENT_WITH_TREE' if consistent else 'CONFLICT_WITH_TREE'
        records.append(record)
        if not consistent:problems.append({'node_id':cid,'field_path':f'relation_plan.relations[{i}]',
            'error':'RELATION_TREE_CONFLICT','status':'CONFLICT_WITH_TREE','relation':copy.deepcopy(record)})
    result={'version':'spatial-relations-check-v1','claims':records,
            'proposed_count':sum(c['status']=='proposed' for c in claims),
            'unknown_count':sum(c['status']=='unknown' for c in claims),
            'source_relation_coverage':'NOT_VERIFIED_BY_CODE',
            'semantic_confirmation':'NONE; model claims and tree consistency are not semantic truth',
            'geometry_scope':'topology/order consistency only; actual pixel position/overlap require browser',
            'outcome':'CONFLICT_NO_REPAIR' if problems else 'CONSISTENT_PROPOSALS_NOT_SEMANTIC_ACCEPTANCE' if any(c['status']=='proposed' for c in claims) else 'NO_PROPOSED_RELATIONS_NOT_VALIDATED'}
    trace_event('region_relations.checked',review=result,diagnostics=problems)
    if problems:raise RegionRelationError(problems)
    return result
