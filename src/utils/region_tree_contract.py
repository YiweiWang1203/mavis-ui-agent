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
    from src.utils.region_relations import enabled as relations_enabled
    relations_enabled()  # Reject an invalid or incompatible opt-in, including tree-off.
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


def locate_quote(quote, intent):
    """Exact, unique source location; not a judgment of semantic support."""
    result={'quote':quote,'semantic_support':'UNKNOWN',
            'source_scope':'provided_user_intent_not_independent_asr_channel'}
    if not isinstance(quote,str) or not quote.strip():
        return dict(result,status='UNKNOWN_INVALID_QUOTE',occurrences=0)
    starts=[];offset=0
    while True:
        start=intent.find(quote,offset)
        if start<0:break
        starts.append(start);offset=start+1
    if len(starts)!=1:
        return dict(result,status='UNKNOWN_QUOTE_ABSENT' if not starts else 'UNKNOWN_QUOTE_AMBIGUOUS',occurrences=len(starts))
    return dict(result,status='UNIQUE_EXACT_QUOTE',occurrences=1,start=starts[0],end=starts[0]+len(quote))


def evidence(items, intent, visual_ids, root=False):
    if root and items==[{'source':'system_root'}]:return copy.deepcopy(items)
    if not isinstance(items,list) or not items:raise ValueError('MISSING_RELATION_EVIDENCE')
    resolved=[]
    for item in items:
        if not isinstance(item,dict):raise ValueError('INVALID_EVIDENCE_ITEM')
        source=item.get('source')
        if source=='asr':
            if set(item)!={'source','quote'}:raise ValueError('QUOTE_ONLY_SOURCE_REQUIRED_NO_MODEL_OFFSETS')
            location=locate_quote(item.get('quote'),intent)
            trace_event('region_tree.quote_location',location=location)
            if location['status']!='UNIQUE_EXACT_QUOTE':raise ValueError(location['status'])
            resolved.append(dict(location,source='asr'))
        elif source=='sketch':
            refs=item.get('visual_ids')
            if not isinstance(refs,list) or not refs or any(x not in visual_ids for x in refs) or not item.get('reason'):
                raise ValueError('INVALID_SKETCH_REFERENCE')
            resolved.append(dict(copy.deepcopy(item),semantic_support='UNKNOWN'))
        elif source=='model_inference':
            if not isinstance(item.get('reason'),str) or not item['reason'].strip():raise ValueError('UNEXPLAINED_INFERENCE')
            resolved.append(dict(copy.deepcopy(item),semantic_support='UNKNOWN'))
        else:raise ValueError('INVALID_EVIDENCE_SOURCE')
    return resolved


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
    """Compute field diff once; model supplies only per-field quote and reason."""
    planned={e['id']:e for e in state.get('elements',[])}
    ledger=[]
    for original in vision.get('elements',[]):
        target=planned.get(original['id'],{})
        sources=target.get('change_sources',{})
        if not isinstance(sources,dict):raise ValueError('INVALID_CHANGE_SOURCES')
        used=set()
        for field in ('type','text','action','actions','rpa_action'):
            if field not in original and field not in target:continue
            before={'present':field in original,'value':copy.deepcopy(original.get(field))}
            after={'present':field in target,'value':copy.deepcopy(target.get(field))}
            if before==after:continue
            row={'id':original['id'],'field':field,'before':before,'after':after,'semantic_support':'UNKNOWN'}
            if field=='actions' and not before['present'] and after['value']==[]:
                row.update(status='NO_ADDITIONAL_ACTION_PLAN',reason='empty plan only; original missing observation preserved')
                ledger.append(row);continue
            try:
                if before['value'] not in (None,'',[],{}) and (not after['present'] or after['value'] in (None,'',[],{})):
                    raise ValueError('OBSERVED_CONTENT_LOST')
                declaration=sources.get(field);used.add(field)
                if not isinstance(declaration,dict) or set(declaration)!={'quote','reason'}:
                    raise ValueError('FIELD_QUOTE_AND_REASON_REQUIRED')
                if not isinstance(declaration['reason'],str) or not declaration['reason'].strip():raise ValueError('CHANGE_REASON_REQUIRED')
                location=locate_quote(declaration['quote'],intent);row['source_location']=location
                if location['status']!='UNIQUE_EXACT_QUOTE':raise ValueError(location['status'])
                row.update(status='SOURCED_PLANNING_PROPOSAL',reason=declaration['reason'])
            except ValueError as exc:row.update(status='REJECTED_CHANGE',reason=str(exc))
            ledger.append(row)
        for field in sorted(set(sources)-used):
            ledger.append({'id':original['id'],'field':field,'status':'REJECTED_CHANGE',
                           'semantic_support':'UNKNOWN','reason':'unused change source for unchanged/normalization/unsupported field'})
    trace_event('region_tree.observation_changes',ledger=ledger,original_vision=vision)
    if any(x['status']=='REJECTED_CHANGE' for x in ledger):raise ValueError('UNSOURCED_OBSERVATION_CHANGE')
    return ledger


class RegionStructureError(ValueError):
    """Original failure code plus non-mutating, independently checkable fields."""
    def __init__(self, diagnostics):
        self.diagnostics = copy.deepcopy(diagnostics)
        super().__init__(diagnostics[0]['error'])


def preflight_required_fields(elements, regions, root):
    # Presence only. Invalid values, provenance and tree semantics remain later gates.
    diagnostics = []
    codes = {'parent':'EXPLICIT_PARENT_REQUIRED', 'relation_status':'INVALID_RELATION_STATUS',
             'order':'INVALID_SIBLING_ORDER', 'sizing':'MISSING_SIZING',
             'evidence':'MISSING_RELATION_EVIDENCE', 'kind':'REGIONS_MUST_BE_ORGANIZATIONAL',
             'layout':'UNSUPPORTED_REGION_LAYOUT'}
    for collection, nodes in (('regions', regions), ('elements', elements)):
        for index, node in enumerate(nodes):
            is_root = collection == 'regions' and node.get('id') == root
            required = ['parent', 'evidence'] if is_root else ['parent','relation_status','order','sizing','evidence']
            if collection == 'regions': required += ['kind','layout']
            base = f"region_contract.regions[{index}]" if collection == 'regions' else f"elements[{index}]"
            for field in required:
                if field not in node:
                    diagnostics.append({'node_id':node.get('id'), 'node_kind':collection,
                        'field_path':base+'.'+field, 'field':field, 'error':codes[field],
                        'status':'MISSING_REQUIRED_FIELD'})
            for container, fields in (('sizing', ('basis_px','grow','shrink')),
                                      ('layout', ('direction','gap_px','padding_px','overflow'))):
                if container == 'sizing' and is_root: continue
                if container == 'layout' and collection != 'regions': continue
                if isinstance(node.get(container), dict):
                    for field in fields:
                        if field not in node[container]:
                            diagnostics.append({'node_id':node.get('id'), 'node_kind':collection,
                                'field_path':base+'.'+container+'.'+field, 'field':container+'.'+field,
                                'error':codes[container], 'status':'MISSING_REQUIRED_FIELD'})
    if diagnostics: raise RegionStructureError(diagnostics)


def _compile_region_tree(state, vision, intent):
    trace_event('region_tree.before',state=state,vision=vision)
    if 'observation_change_evidence' in state:raise ValueError('LEGACY_REPEATED_CHANGE_LEDGER')
    out=copy.deepcopy(state);elements=out.get('elements',[])
    contract=out.get('region_contract',{})
    if not isinstance(contract,dict) or set(contract)!={'version','root_id','regions'} or contract.get('version')!='region-tree-v2':
        raise ValueError('SINGLE_CANONICAL_REGION_PLAN_REQUIRED')
    regions=contract['regions']
    if not isinstance(elements,list) or not isinstance(regions,list) or not all(isinstance(x,dict) for x in elements+regions):
        raise ValueError('INVALID_PLAN_NODES')
    preflight_required_fields(elements, regions, contract.get('root_id'))
    for node in elements+regions:
        if any(key in node for key in ('objects','elements','regions','children','children_ids','members','member_ids','parent_id')):
            raise ValueError('NESTED_OR_DUPLICATE_PARENT_MAPPING')
        if 'parent' not in node:raise ValueError('EXPLICIT_PARENT_REQUIRED')
    vids=[e.get('id') for e in vision.get('elements',[])]
    ids=[e.get('id') for e in elements]
    if any(not isinstance(x,str) or not x for x in vids+ids) or len(set(vids))!=len(vids) or len(set(ids))!=len(ids):raise ValueError('DUPLICATE_OR_MISSING_OBJECT_ID')
    if not set(vids)<=set(ids):raise ValueError('SOURCE_OBJECT_LOST')
    for item in elements:
        if item['id'] not in vids:
            if item.get('origin')!='spoken' or not item['id'].startswith('u_'):raise ValueError('UNSOURCED_BUSINESS_OBJECT')
            refs=item.get('source_evidence',[])
            if not isinstance(refs,list) or not refs or any(not isinstance(x,dict) or x.get('source')!='asr' for x in refs):
                raise ValueError('NEW_OBJECT_REQUIRES_ASR')
            evidence(refs,intent,set(vids))
            if item.get('change_sources'):raise ValueError('NEW_OBJECT_HAS_NO_OBSERVATION_TO_CHANGE')
    changes=observation_changes(out,vision,intent)
    out['observation_provenance']={'original_vision':copy.deepcopy(vision),'changes':changes,'semantic_confirmation':'NOT_CONFIRMED_BY_REFERENCE_EXISTENCE'}
    rids=[r.get('id') for r in regions];root=contract.get('root_id')
    if any(not isinstance(r,str) or not r.startswith('region_') for r in rids):raise ValueError('REGION_ID_NAMESPACE')
    if not root or root not in rids or len(set(rids))!=len(rids) or set(rids)&set(ids):raise ValueError('INVALID_REGION_IDENTITIES')
    nodes={r['id']:r for r in regions};nodes.update({item['id']:item for item in elements})
    children=defaultdict(list);styles={};parents={};reviews=[]
    for identity,node in nodes.items():
        is_root=identity==root;parent=node.get('parent')
        if (is_root and parent is not None) or (not is_root and parent not in rids):raise ValueError('INVALID_PARENT')
        parents[identity]=parent
        resolved=evidence(node.get('evidence'),intent,set(vids),root=is_root)
        status=node.get('relation_status')
        if is_root:status='proposed'
        if status not in {'proposed','unknown'}:raise ValueError('INVALID_RELATION_STATUS')
        if not is_root and status=='unknown' and parent!=root:raise ValueError('UNKNOWN_MEMBERSHIP_MUST_STAY_AT_ROOT')
        reviews.append({'id':identity,'evidence':resolved,'semantic_support':'UNKNOWN',
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
    from src.utils.region_relations import enabled as relations_enabled, verify_relation_plan
    if relations_enabled():
        out['relation_review']=verify_relation_plan(out,vision,intent)
    trace_event('region_tree.after',state=out)
    return out


def compile_region_tree(state, vision, intent):
    try:return _compile_region_tree(state,vision,intent)
    except (ValueError,TypeError,KeyError) as exc:
        trace_event('region_tree.rejected',error=str(exc),exception_type=type(exc).__name__,
                    outcome='NO_CODER_NO_AUTOMATIC_REPAIR',semantic_support='UNKNOWN',
                    diagnostics=getattr(exc,'diagnostics',[]),node='architect.finalize.region_tree')
        raise
