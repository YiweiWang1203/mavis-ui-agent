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


@traced_stage('architect.relation_evidence')
def apply_relation_evidence(state, user_intent):
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
    accepted = []; owners = {}; pairs = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError('Invalid relation evidence entry')
        parent = aliases.get(edge.get('parent_id'), edge.get('parent_id'))
        child = aliases.get(edge.get('child_id'), edge.get('child_id'))
        if parent not in index or child not in index or parent == child:
            raise ValueError('Invalid relation endpoint')
        container = index[parent]
        if container.get('type') not in DESCRIPTORS:
            raise ValueError('Relation parent is not a container')
        quote = edge.get('evidence_quote')
        if not isinstance(quote,str) or not 2 <= len(quote) <= 400 or quote not in user_intent:
            raise ValueError('Relation quote is not a bounded source substring')
        q = normalized(quote)
        child_label = normalized(index[child].get('text') or '')
        if not child_label or child_label not in q:
            raise ValueError('Relation evidence lacks literal child label')
        # A quote is a traceable anchor, not proof of semantic correctness.
        parent_label = normalized(container.get('text') or '')
        descriptors = (parent_label,) if parent_label else DESCRIPTORS[container['type']]
        if not any(normalized(word) in q for word in descriptors):
            raise ValueError('Relation evidence lacks parent description')
        if (parent,child) in pairs or child in owners:
            raise ValueError('Duplicate or conflicting relation parent')
        pairs.add((parent,child)); owners[child] = parent
        index[child]['parent_id'] = parent
        accepted.append({'parent_id':parent,'child_id':child,'evidence_quote':quote,
                         'source':'user_intent','start':user_intent.index(quote)})
    for child in owners:
        seen = {child}; parent = owners[child]
        while parent is not None:
            if parent in seen:
                raise ValueError('Relation evidence cycle')
            seen.add(parent); parent = owners.get(parent)
    result.setdefault('page_meta',{})['relation_evidence'] = {
        'version':'source-quotes-v1','accepted_count':len(accepted),'edges':accepted,
        'semantic_review':'required; substring and anchors do not prove intent entailment'}
    return result
