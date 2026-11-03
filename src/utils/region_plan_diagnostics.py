"""Read-only, multi-error planning diagnostics. NEVER a production acceptance gate.

No repair, model call, semantic inference or import of evaluation references.
Independent raw tree facts may be shown while source validity blocks enforcement.
"""
from collections import defaultdict


def diagnose_region_plan(state, vision, intent):
    issues = []
    checks = []

    def issue(code, path, *, status='ERROR', related_paths=None, **facts):
        row = {'code':code, 'status':status, 'field_path':path,
               'related_paths':related_paths or [], 'facts':facts}
        issues.append(row)
        return row

    if not isinstance(state,dict):
        issue('PLAN_NOT_OBJECT','$')
        return _result(issues,checks)
    contract = state.get('region_contract')
    if not isinstance(contract,dict):
        issue('REGION_CONTRACT_NOT_OBJECT','$.region_contract')
        contract = {}
    elements = state.get('elements')
    regions = contract.get('regions')
    if not isinstance(elements,list):
        issue('ELEMENTS_NOT_LIST','$.elements'); elements=[]
    if not isinstance(regions,list):
        issue('REGIONS_NOT_LIST','$.region_contract.regions'); regions=[]
    root = contract.get('root_id')
    if not isinstance(root,str):
        issue('INVALID_ROOT_ID','$.region_contract.root_id')
        root = None
    observed = vision.get('elements',[]) if isinstance(vision,dict) else []
    if not isinstance(observed,list):observed=[]
    visual_ids = {x.get('id') for x in observed if isinstance(x,dict)
                  and isinstance(x.get('id'),str)}

    def quote(quote_value,path):
        if not isinstance(intent,str):
            issue('SOURCE_TEXT_UNAVAILABLE',path,status='BLOCKED'); return False
        if not isinstance(quote_value,str) or not quote_value.strip():
            issue('UNKNOWN_INVALID_QUOTE',path,occurrences=0); return False
        starts=[];offset=0
        while True:
            start=intent.find(quote_value,offset)
            if start<0:break
            starts.append(start);offset=start+1
        if len(starts)!=1:
            issue('UNKNOWN_QUOTE_ABSENT' if not starts else 'UNKNOWN_QUOTE_AMBIGUOUS',
                  path,occurrences=len(starts)); return False
        return True

    def evidence(items,path,is_root=False):
        if is_root and items==[{'source':'system_root'}]:return True
        if not isinstance(items,list) or not items:
            issue('MISSING_RELATION_EVIDENCE',path); return False
        valid=True
        for i,item in enumerate(items):
            p=f'{path}[{i}]'
            if not isinstance(item,dict):
                issue('INVALID_EVIDENCE_ITEM',p);valid=False;continue
            source=item.get('source')
            if source=='asr':
                if set(item)!={'source','quote'}:
                    issue('QUOTE_ONLY_SOURCE_REQUIRED_NO_MODEL_OFFSETS',p);valid=False
                valid=quote(item.get('quote'),p+'.quote') and valid
            elif source=='sketch':
                ids=item.get('visual_ids')
                if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or x not in visual_ids for x in ids) or not item.get('reason'):
                    issue('INVALID_SKETCH_REFERENCE',p);valid=False
            elif source=='model_inference':
                if not isinstance(item.get('reason'),str) or not item['reason'].strip():
                    issue('UNEXPLAINED_INFERENCE',p);valid=False
            else:
                issue('INVALID_EVIDENCE_SOURCE',p);valid=False
        return valid

    nodes={};paths={};region_ids=set();duplicate_ids=set();source_ok={}
    ordered=[]
    for items,base,is_region in ((regions,'$.region_contract.regions',True),
                                (elements,'$.elements',False)):
        for i,node in enumerate(items):
            p=f'{base}[{i}]'
            if not isinstance(node,dict):
                issue('NODE_NOT_OBJECT',p);continue
            identity=node.get('id')
            if not isinstance(identity,str) or not identity:
                issue('MISSING_NODE_ID',p+'.id');continue
            if identity in nodes:
                duplicate_ids.add(identity)
                issue('DUPLICATE_NODE_ID',p+'.id',related_paths=[paths[identity]+'.id'],node_id=identity)
            else:nodes[identity]=node;paths[identity]=p
            if is_region:region_ids.add(identity)
            source_ok[identity]=evidence(node.get('evidence'),p+'.evidence',identity==root) and source_ok.get(identity,True)
            if 'source_evidence' in node:evidence(node['source_evidence'],p+'.source_evidence')
            changes=node.get('change_sources',{})
            if isinstance(changes,dict):
                for field,value in changes.items():
                    if isinstance(value,dict):quote(value.get('quote'),p+'.change_sources.'+str(field)+'.quote')
            ordered.append((identity,node,p))
    if root not in region_ids:
        issue('INVALID_ROOT_ID','$.region_contract.root_id',root_id=root)
    sibling_groups=defaultdict(list);bad_order_parents=set()
    for identity,node,p in ordered:
        parent=node.get('parent')
        if identity==root:
            if parent is not None:issue('INVALID_ROOT_PARENT',p+'.parent',node_id=identity)
            continue
        if not isinstance(parent,str) or parent not in region_ids:
            issue('INVALID_PARENT',p+'.parent',node_id=identity,parent=parent)
        order=node.get('order')
        if type(order) is not int or order<0:
            issue('INVALID_SIBLING_ORDER',p+'.order',node_id=identity,parent=parent)
            if isinstance(parent,str):bad_order_parents.add(parent)
        elif isinstance(parent,str):sibling_groups[(parent,order)].append((identity,p))
    for (parent,order),members in sibling_groups.items():
        if len(members)>1:
            bad_order_parents.add(parent)
            issue('AMBIGUOUS_SIBLING_ORDER',members[0][1]+'.order',
                  related_paths=[p+'.order' for _,p in members[1:]],
                  parent=parent,order=order,node_ids=[n for n,_ in members])
    for identity in region_ids:
        layout=nodes[identity].get('layout')
        if not isinstance(layout,dict) or layout.get('direction') not in {'row','column'}:
            issue('INVALID_LAYOUT_DIRECTION',paths[identity]+'.layout.direction',node_id=identity)

    def ancestor_path(identity):
        result=[];seen=set();current=identity
        while current is not None:
            if current in seen:return None,'REGION_CYCLE'
            if not isinstance(current,str) or current not in nodes:return None,'INVALID_PARENT'
            if current in duplicate_ids:return None,'DUPLICATE_NODE_ID'
            seen.add(current);result.append(current)
            parent=nodes[current].get('parent')
            if current!=root and (not isinstance(parent,str) or parent not in region_ids):return None,'INVALID_PARENT'
            if current==root and parent is not None:return None,'INVALID_ROOT_PARENT'
            current=parent
        if not result or result[-1]!=root or root not in region_ids:return None,'ROOT_NOT_REACHABLE'
        return list(reversed(result)),None

    for identity in nodes:
        _,error=ancestor_path(identity)
        if error:issue(error,paths[identity]+'.parent',node_id=identity)

    plan=state.get('relation_plan')
    if plan is None:
        checks.append({'status':'UNKNOWN','code':'RELATION_PLAN_NOT_SUPPLIED',
                       'field_path':'$.relation_plan'})
        return _result(issues,checks)
    claims=plan.get('relations') if isinstance(plan,dict) else None
    if not isinstance(claims,list):
        issue('RELATION_LIST_REQUIRED','$.relation_plan.relations');return _result(issues,checks)
    seen_claims=set();seen_ids=set()
    for i,claim in enumerate(claims):
        p=f'$.relation_plan.relations[{i}]'
        if not isinstance(claim,dict):issue('INVALID_RELATION',p);continue
        cid=claim.get('id');a=claim.get('subject');b=claim.get('object');kind=claim.get('kind')
        status=claim.get('status');valid_source=evidence(claim.get('evidence'),p+'.evidence')
        base={'relation_id':cid,'field_path':p,'kind':kind,'subject':a,'object':b,
              'source_validation':'VALID_FORMAT_AND_LOCATION_ONLY' if valid_source else 'INVALID',
              'semantic_support':'UNKNOWN','production_gate':'NOT_EXECUTED_BY_DIAGNOSTIC'}
        if not isinstance(cid,str) or not cid.startswith('rel_') or cid in seen_ids:
            issue('INVALID_RELATION_ID',p+'.id');checks.append(dict(base,status='BLOCKED'));continue
        seen_ids.add(cid)
        if not isinstance(a,str) or not isinstance(b,str) or a not in nodes or b not in nodes or a==b:
            issue('INVALID_RELATION_ENDPOINTS',p);checks.append(dict(base,status='BLOCKED'));continue
        key=(kind,a,b)
        if not isinstance(kind,str) or kind not in {'left_of','above','contains'}:
            issue('UNSUPPORTED_SPATIAL_RELATION',p+'.kind');checks.append(dict(base,status='BLOCKED'));continue
        claim_unique=key not in seen_claims
        if not claim_unique:issue('DUPLICATE_RELATION_CLAIM',p)
        seen_claims.add(key)
        if not isinstance(status,str) or status not in {'proposed','unknown'}:
            issue('INVALID_RELATION_CLAIM_STATUS',p+'.status');checks.append(dict(base,status='BLOCKED'));continue
        pa,ea=ancestor_path(a);pb,eb=ancestor_path(b)
        if ea or eb:
            checks.append(dict(base,status='BLOCKED',code='INVALID_TREE_DEPENDENCY',
                               dependency_errors=[e for e in (ea,eb) if e],
                               related_paths=[paths[a]+'.parent',paths[b]+'.parent']));continue
        tree_paths=[]
        for n in dict.fromkeys(pa+pb):
            tree_paths.append(paths[n]+'.parent')
            if n!=root:tree_paths.append(paths[n]+'.order')
            if n in region_ids:tree_paths.append(paths[n]+'.layout.direction')
        if kind!='contains' and any(
            (n!=root and (type(nodes[n].get('order')) is not int or nodes[n]['order']<0
                          or nodes[n].get('parent') in bad_order_parents))
            or (n in region_ids and (not isinstance(nodes[n].get('layout'),dict)
                or nodes[n]['layout'].get('direction') not in {'row','column'}))
            for n in set(pa+pb)
        ):
            checks.append(dict(base,status='BLOCKED',code='INVALID_ANCESTOR_LAYOUT_OR_ORDER',
                               related_paths=tree_paths));continue
        if kind=='contains':
            consistent=a in region_ids and a in pb[:-1]
            fact={'subject_is_region':a in region_ids,'object_ancestor_path':pb}
        else:
            shared=0
            while shared<min(len(pa),len(pb)) and pa[shared]==pb[shared]:shared+=1
            if shared==min(len(pa),len(pb)):
                consistent=False;fact={'reason':'ANCESTOR_NOT_DISTINCT_LAYOUT_BRANCHES'}
            else:
                lca=pa[shared-1];ba=pa[shared];bb=pb[shared]
                layout=nodes[lca].get('layout');direction=layout.get('direction') if isinstance(layout,dict) else None
                oa=nodes[ba].get('order');ob=nodes[bb].get('order')
                tree_paths += [paths[lca]+'.layout.direction',paths[ba]+'.order',paths[bb]+'.order']
                if lca in bad_order_parents or direction not in {'row','column'} or type(oa) is not int or type(ob) is not int:
                    checks.append(dict(base,status='BLOCKED',code='INVALID_LCA_LAYOUT_OR_SIBLING_ORDER',
                                       related_paths=tree_paths));continue
                consistent=direction==('row' if kind=='left_of' else 'column') and oa<ob
                fact={'lowest_common_ancestor':lca,'direction':direction,
                      'subject_branch':ba,'object_branch':bb,'subject_order':oa,'object_order':ob}
        raw='CONSISTENT_WITH_DECLARATION' if consistent else 'CONFLICT_WITH_DECLARATION'
        dependencies_valid=valid_source and all(source_ok.get(n,False) for n in pa+pb)
        if not dependencies_valid:
            checks.append(dict(base,status='BLOCKED',code='INVALID_SOURCE_DEPENDENCY',
                               raw_tree_fact=fact,conditional_tree_consistency=raw,related_paths=tree_paths))
        elif not claim_unique:
            checks.append(dict(base,status='BLOCKED',code='DUPLICATE_RELATION_CLAIM',
                               raw_tree_fact=fact,conditional_tree_consistency=raw,related_paths=tree_paths))
        elif status=='unknown':
            checks.append(dict(base,status='UNKNOWN',code='UNKNOWN_NOT_ENFORCED',
                               raw_tree_fact=fact,related_paths=tree_paths))
        else:
            checks.append(dict(base,status='OBSERVED' if consistent else 'ERROR',
                               code='DECLARED_TREE_CONSISTENT' if consistent else 'RELATION_TREE_CONFLICT',
                               raw_tree_fact=fact,related_paths=tree_paths))
            if not consistent:
                issue('RELATION_TREE_CONFLICT',p,related_paths=tree_paths,
                      relation_id=cid,subject=a,object=b,tree_fact=fact)
    return _result(issues,checks)


def _result(issues,checks):
    return {'version':'region-plan-diagnostics-v1','kind':'READ_ONLY_DIAGNOSTIC_NOT_GATE',
            'issues':issues,'relation_checks':checks,'production_acceptance':'NOT_DECIDED',
            'semantic_support':'UNKNOWN','source_coverage':'NOT_EVALUATED',
            'repair_performed':False,'can_generate_page':False}
