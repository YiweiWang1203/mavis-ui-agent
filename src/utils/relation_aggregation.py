"""Retain independently validated source evidence; conflicts fail, never vote."""
import copy
from src.utils.pipeline_trace import traced_stage
from src.utils.relation_evidence import apply_relation_evidence


@traced_stage('architect.relation_aggregation')
def aggregate_relation_sources(state, user_intent):
    sources=state.get('relation_evidence_sources')
    if not isinstance(sources,list) or len(sources)!=2 or [s.get('source') for s in sources]!=['architect','specialist']:
        raise ValueError('Expected architect and specialist relation sources')
    aliases={e.get('vision_id') or e['id']:e['id'] for e in state['elements']}
    parents={};accepted={};support={};unresolved=[];reports=[]
    for source in sources:
        checked=apply_relation_evidence(dict(copy.deepcopy(state),relationships=source['relationships']),user_intent,isolate_source_errors=True)
        meta=checked['page_meta']['relation_evidence']
        # The existing validator has already preflighted all proposals in this source.
        # Cross-source disagreement also fails even when one quote is unresolved.
        for edge in source['relationships']:
            child=aliases.get(edge['child_id'],edge['child_id']);parent=aliases.get(edge['parent_id'],edge['parent_id'])
            if child in parents and parents[child]!=parent:raise ValueError('Conflicting parent claims across relation sources')
            parents[child]=parent
        for edge in meta['edges']:
            key=(edge['parent_id'],edge['child_id'])
            accepted.setdefault(key,edge)
            support.setdefault(key,[]).append({'source':source['source'],'evidence_quote':edge['evidence_quote']})
        unresolved.extend(dict(e,source_stage=source['source']) for e in meta['unresolved_edges'])
        reports.append({'source':source['source'],'proposed_count':len(source['relationships']),
            'accepted_count':meta['accepted_count'],'unresolved_edges':meta['unresolved_edges']})
    for child in parents:
        seen={child};parent=parents[child]
        while parent is not None:
            if parent in seen:raise ValueError('Cross-source relation cycle')
            seen.add(parent);parent=parents.get(parent)
    merged=copy.deepcopy(state)
    merged['relationships']=[{k:e[k] for k in ('parent_id','child_id','evidence_quote')} for e in accepted.values()]
    merged=apply_relation_evidence(merged,user_intent,isolate_source_errors=True)
    unique_unresolved={}
    for edge in unresolved:
        key=(edge['parent_id'],edge['child_id'])
        if key not in accepted:unique_unresolved.setdefault(key,edge)
    meta=merged['page_meta']['relation_evidence']
    meta.update(unresolved_count=len(unique_unresolved),unresolved_edges=list(unique_unresolved.values()),
        validation_status='partial_evidence_unresolved' if unique_unresolved else 'accepted_entries_only')
    merged['page_meta']['relation_aggregation']={'version':'validated-source-union-v1',
        'source_reports':reports,'accepted_union_count':len(accepted),
        'support':[{'parent_id':p,'child_id':c,'sources':values} for (p,c),values in support.items()],
        'limits':'All sources pass original structural checks. Lexical acceptance still requires semantic review.'}
    return merged
