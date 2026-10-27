"""Apply source-grounded relation declarations before source/geometry validation."""
import copy
from src.utils.pipeline_trace import traced_stage

CONTAINER_ALIASES = {'nav_bar':'navigation_bar'}
DESCRIPTORS = {
    'card': ('卡片','card'), 'navigation_bar': ('导航','navigation','navbar'),
    'navigation': ('导航','navigation'), 'container': ('区域','容器','region','container','panel'),
    'toolbar': ('工具栏','toolbar'), 'header': ('顶部','页头','header'),
    'footer': ('底部','页脚','footer'), 'list': ('列表','list'),
    'modal': ('弹窗','modal','dialog'), 'page': ('页面','page'),
}


def normalized(text):
    return ''.join(str(text).casefold().split())


class SourceEvidenceError(ValueError):
    """A single proposed relation lacks a usable source anchor."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_source(edge, parent, child, user_intent):
    quote = edge.get('evidence_quote')
    if not isinstance(quote,str) or not 2 <= len(quote) <= 400 or quote not in user_intent:
        raise SourceEvidenceError('source_quote_not_found', 'Relation quote is not a bounded source substring')
    q = normalized(quote)
    label = normalized(child.get('text') or '')
    if not label or label not in q:
        raise SourceEvidenceError('child_label_not_anchored', 'Relation evidence lacks literal child label')
    parent_label = normalized(parent.get('text') or '')
    descriptors = (parent_label,) if parent_label else DESCRIPTORS[parent['type']]
    if not any(normalized(word) in q for word in descriptors):
        raise SourceEvidenceError('parent_description_not_anchored', 'Relation evidence lacks parent description')
    return quote


@traced_stage('architect.relation_evidence')
def apply_relation_evidence(state, user_intent, isolate_source_errors=False):
    if not isinstance(isolate_source_errors,bool):
        raise ValueError('Invalid relation evidence policy')
    result = copy.deepcopy(state)
    edges = result.get('relationships')
    if not isinstance(edges, list):
        raise ValueError('Missing relation evidence ledger')
    index = {e['id']:e for e in result['elements']}
    if len(index) != len(result['elements']):
        raise ValueError('Duplicate relation identities')
    aliases = {e.get('vision_id') or e['id']:e['id'] for e in result['elements']}
    for e in index.values():
        e['parent_id'] = None
        e['type'] = CONTAINER_ALIASES.get(e.get('type'), e.get('type'))
    # Preflight global structure before isolating any source error. A bad quote
    # must never hide competing parents, duplicate endpoints or a cycle.
    proposed = {}; entries = []
    for edge in edges:
        if not isinstance(edge,dict) or not all(isinstance(edge.get(k),str) for k in ('parent_id','child_id')):
            raise ValueError('Invalid relation evidence entry')
        parent = aliases.get(edge['parent_id'],edge['parent_id'])
        child = aliases.get(edge['child_id'],edge['child_id'])
        if parent not in index or child not in index or parent == child:
            raise ValueError('Invalid relation endpoint')
        if index[parent].get('type') not in DESCRIPTORS:
            raise ValueError('Relation parent is not a container')
        if child in proposed:
            raise ValueError('Duplicate or conflicting relation parent')
        proposed[child] = parent
        entries.append((parent,child,edge))
    for child in proposed:
        seen = {child}; parent = proposed[child]
        while parent is not None:
            if parent in seen:
                raise ValueError('Relation evidence cycle')
            seen.add(parent); parent = proposed.get(parent)
    accepted = []; unresolved = []
    for parent,child,edge in entries:
        try:
            quote = validate_source(edge,index[parent],index[child],user_intent)
        except SourceEvidenceError as error:
            if not isolate_source_errors:
                raise
            unresolved.append({'parent_id':parent,'child_id':child,'reason':error.code,
                               'message':str(error),'proposed_quote':edge.get('evidence_quote')})
            continue
        index[child]['parent_id'] = parent
        accepted.append({'parent_id':parent,'child_id':child,'evidence_quote':quote,
                         'source':'user_intent','start':user_intent.index(quote)})
    result.setdefault('page_meta',{})['relation_evidence'] = {
        'version':'source-quotes-partial-v1' if isolate_source_errors else 'source-quotes-v1',
        'validation_status':'partial_evidence_unresolved' if unresolved else 'accepted_entries_only',
        'accepted_count':len(accepted),'edges':accepted,
        'unresolved_count':len(unresolved),'unresolved_edges':unresolved,
        'semantic_review':'required; substring and anchors do not prove intent entailment'}
    return result
