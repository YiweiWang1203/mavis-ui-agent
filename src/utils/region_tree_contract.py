"""Opt-in semantic-region layout; never infers containment from coordinates."""
import copy
import math
import os
from collections import defaultdict
from src.utils.pipeline_trace import trace_event

NEUTRAL = {'primary_surface':'#FFFFFF','secondary_surface':'#F5F6F8','divider':'#E2E5EA',
           'primary_action':'#2563EB','body_text':'#1F2937','secondary_text':'#5F6B7A'}


def enabled():
    mode=os.getenv('UI_REGION_TREE_MODE','off')
    if mode not in {'off','region_tree_v1'}:raise ValueError('INVALID_REGION_TREE_MODE')
    if mode=='off':return False
    forbidden={'UI_STRUCTURE_MODE':'baseline','UI_RELATION_SPECIALIST_MODE':'off',
        'UI_INPUT_SEMANTIC_AUDIT_MODE':'off','UI_SEMANTIC_TYPE_MODE':'off',
        'UI_COORDINATE_RESPONSIBILITY_MODE':'off','UI_RELATION_AGGREGATION_MODE':'off',
        'UI_FUSION_MODE':'exact_id','UI_CODER_CONTRACT_MODE':'baseline'}
    for key,default in forbidden.items():
        if os.getenv(key,default)!=default:raise ValueError('CONFLICTING_LEGACY_MODE:'+key)
    return True


def neutral_instructions():
    mode=os.getenv('UI_NEUTRAL_VISUAL_MODE','off')
    if mode not in {'off','neutral_v1'}:raise ValueError('INVALID_NEUTRAL_MODE')
    return '' if mode=='off' else '\nShared neutral visual specification, authoritative for colors: '+str(NEUTRAL)+'. Use by semantic responsibility, not fixed left/right or a different color per depth. No added user requirements.'


def number(value, name, minimum=0):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<minimum:
        raise ValueError('INVALID_NUMBER:'+name)
    return value


def evidence(items, intent, visual_ids, root=False):
    if root and items==[{'source':'system_root'}]:return
    if not isinstance(items,list) or not items:raise ValueError('MISSING_RELATION_EVIDENCE')
    for item in items:
        source=item.get('source')
        if source=='asr':
            start,end=item.get('start'),item.get('end');quote=item.get('quote')
            if type(start)!=int or type(end)!=int or not 0<=start<end<=len(intent) or not quote or intent[start:end]!=quote:
                raise ValueError('ASR_QUOTE_NOT_IN_SOURCE')
        elif source=='sketch':
            refs=item.get('visual_ids')
            if not isinstance(refs,list) or not refs or any(x not in visual_ids for x in refs) or not item.get('reason'):
                raise ValueError('INVALID_SKETCH_REFERENCE')
        elif source=='model_inference':
            if not isinstance(item.get('reason'),str) or not item['reason'].strip():raise ValueError('UNEXPLAINED_INFERENCE')
        else:raise ValueError('INVALID_EVIDENCE_SOURCE')


def sizing(spec):
    if not isinstance(spec,dict):raise ValueError('MISSING_SIZING')
    basis=spec.get('basis_px')
    if basis!='auto':number(basis,'basis_px')
    grow=number(spec.get('grow'),'grow');shrink=number(spec.get('shrink'),'shrink')
    cross=spec.get('cross','stretch')
    if cross not in {'stretch','intrinsic'}:raise ValueError('INVALID_CROSS_POLICY')
    return {'flexBasis':'auto' if basis=='auto' else f'{basis}px','flexGrow':grow,
            'flexShrink':shrink,'alignSelf':'stretch' if cross=='stretch' else 'flex-start'}


def observation_changes(state, vision, intent):
    """Compare same-ID semantic fields; quotes establish provenance, not truth."""
    planned={e['id']:e for e in state.get('elements',[])}
    declarations=state.get('observation_change_evidence',[])
    ledger=[];used=set()
    for original in vision.get('elements',[]):
        target=planned.get(original['id'],{})
        for field in ('type','text','action','actions','rpa_action'):
            if field not in original and field not in target:continue
            before={'present':field in original,'value':copy.deepcopy(original.get(field))}
            after={'present':field in target,'value':copy.deepcopy(target.get(field))}
            if before==after:continue
            matches=[(i,d) for i,d in enumerate(declarations) if d.get('id')==original['id'] and d.get('field')==field]
            row={'id':original['id'],'field':field,'before':before,'after':after}
            if len(matches)!=1:
                row.update(status='UNSOURCED_CHANGE',reason='exactly one declaration required')
            else:
                i,d=matches[0];used.add(i);refs=d.get('evidence',[])
                try:
                    if d.get('before')!=before or d.get('after')!=after:raise ValueError('DECLARATION_VALUE_MISMATCH')
                    if not d.get('reason') or not refs or any(x.get('source')!='asr' for x in refs):raise ValueError('ASR_REQUIRED_FOR_SEMANTIC_CHANGE')
                    evidence(refs,intent,{e['id'] for e in vision['elements']})
                    if field in original and (field not in target or target[field] in (None,'',[],{})) and original[field] not in (None,'',[],{}):raise ValueError('OBSERVED_CONTENT_LOST')
                    row.update(status='ASR_SOURCED_PROPOSAL_NOT_SEMANTICALLY_CONFIRMED',evidence=copy.deepcopy(refs),reason=d['reason'])
                except ValueError as exc:row.update(status='UNSOURCED_CHANGE',reason=str(exc))
            ledger.append(row)
    for i,d in enumerate(declarations):
        if i not in used:ledger.append({'declaration':copy.deepcopy(d),'status':'UNSOURCED_CHANGE','reason':'unused or duplicate declaration'})
    trace_event('region_tree.observation_changes',ledger=ledger,original_vision=vision)
    if any(x['status']=='UNSOURCED_CHANGE' for x in ledger):raise ValueError('UNSOURCED_OBSERVATION_CHANGE')
    return ledger


def compile_region_tree(state, vision, intent):
    trace_event('region_tree.before',state=state,vision=vision)
    out=copy.deepcopy(state);elements=out.get('elements',[])
    vids=[e.get('id') for e in vision.get('elements',[])]
    ids=[e.get('id') for e in elements]
    if any(not isinstance(x,str) or not x for x in vids+ids) or len(set(vids))!=len(vids) or len(set(ids))!=len(ids):raise ValueError('DUPLICATE_OR_MISSING_OBJECT_ID')
    if not set(vids)<=set(ids):raise ValueError('SOURCE_OBJECT_LOST')
    for item in elements:
        if item['id'] not in vids:
            if item.get('origin')!='spoken' or not item['id'].startswith('u_'):raise ValueError('UNSOURCED_BUSINESS_OBJECT')
            refs=item.get('source_evidence',[])
            if not refs or any(x.get('source')!='asr' for x in refs):raise ValueError('NEW_OBJECT_REQUIRES_ASR')
            evidence(refs,intent,set(vids))
    changes=observation_changes(out,vision,intent)
    out['observation_provenance']={'original_vision':copy.deepcopy(vision),'changes':changes,'semantic_confirmation':'NOT_CONFIRMED_BY_REFERENCE_EXISTENCE'}
    contract=out.get('region_contract',{})
    if contract.get('version')!='region-tree-v1':raise ValueError('MISSING_REGION_CONTRACT')
    regions=contract.get('regions',[]);rids=[r.get('id') for r in regions];root=contract.get('root_id')
    if not root or root not in rids or len(set(rids))!=len(rids) or set(rids)&set(ids):raise ValueError('INVALID_REGION_IDENTITIES')
    if any(not isinstance(r,str) or not r.startswith('region_') for r in rids):raise ValueError('REGION_ID_NAMESPACE')
    assignments=contract.get('objects',[])
    if sorted(x.get('id','') for x in assignments)!=sorted(ids):raise ValueError('OBJECT_PARENT_COVERAGE')
    assigned={item['id']:item for item in assignments}
    for item in elements:
        if item.get('parent_id') is not None and item['parent_id']!=assigned[item['id']]['parent']:
            raise ValueError('CONFLICTING_OBJECT_PARENT')
    nodes={r['id']:r for r in regions};nodes.update({a['id']:a for a in assignments})
    children=defaultdict(list);styles={};parents={};reviews=[]
    for identity,node in nodes.items():
        is_root=identity==root;parent=node.get('parent')
        if (is_root and parent is not None) or (not is_root and parent not in rids):raise ValueError('INVALID_PARENT')
        parents[identity]=parent
        evidence(node.get('evidence'),intent,set(vids),root=is_root)
        status=node.get('relation_status','proposed')
        if status not in {'proposed','unknown'}:raise ValueError('INVALID_RELATION_STATUS')
        if not is_root and status=='unknown' and parent!=root:raise ValueError('UNKNOWN_MEMBERSHIP_MUST_STAY_AT_ROOT')
        reviews.append({'id':identity,'evidence':copy.deepcopy(node['evidence']),
                        'status':'system_organization' if is_root else 'unknown' if status=='unknown' else 'model_proposed_not_human_confirmed'})
        css={'boxSizing':'border-box','minWidth':0,'minHeight':0,'margin':0,'position':'relative'}
        if not is_root:
            order=node.get('order')
            if type(order)!=int or order<0:raise ValueError('INVALID_SIBLING_ORDER')
            children[parent].append((order,identity));css.update(sizing(node.get('sizing')))
        if identity in rids:
            if node.get('kind')!='semantic_region':raise ValueError('REGIONS_MUST_BE_ORGANIZATIONAL')
            layout=node.get('layout',{})
            if layout.get('direction') not in {'row','column'} or layout.get('overflow') not in {'visible','auto','hidden'}:raise ValueError('UNSUPPORTED_REGION_LAYOUT')
            css.update(display='flex',flexDirection=layout['direction'],gap=f"{number(layout.get('gap_px'),'gap')}px",padding=f"{number(layout.get('padding_px'),'padding')}px",overflow=layout['overflow'])
            # These policies are engineering adaptations, not original demands.
            reviews[-1]['layout_policy_status']='engineering_proposal_unless_explicitly_sourced'
        styles[identity]=css
    for identity in nodes:
        seen=set();current=identity
        while current is not None:
            if current in seen:raise ValueError('REGION_CYCLE')
            seen.add(current);current=parents[current]
        if root not in seen:raise ValueError('ROOT_NOT_REACHABLE')
    for parent,items in children.items():
        if len({order for order,_ in items})!=len(items):raise ValueError('AMBIGUOUS_SIBLING_ORDER')
    view=out.get('page_meta',{}).get('viewport',{})
    width=number(view.get('width'),'viewport.width',1);height=number(view.get('height'),'viewport.height',1)
    styles[root].update(width=f'{width}px',height=f'{height}px')
    out['region_layout']={'version':'region-flex-v1','root_id':root,
        'children':{p:[identity for _,identity in sorted(items)] for p,items in children.items()},
        'css_by_id':styles,'parent_by_id':parents,'review':reviews,
        'kind_by_id':{identity:'semantic_region' if identity in rids else 'leaf' for identity in nodes},
        'coordinate_policy':'source boxes are retained evidence/soft proposals, not hard rendered positions',
        'unverified_scope':'semantic truth, rendered overflow and browser behavior require independent acceptance'}
    out['source_coordinate_evidence']={'vision':copy.deepcopy(vision),
        'architect_spatial_by_id':{e['id']:copy.deepcopy(e.get('spatial_info')) for e in elements}}
    if out['elements']!=state['elements']:raise AssertionError('BUSINESS_OBJECT_MUTATED')
    trace_event('region_tree.after',state=out)
    return out
