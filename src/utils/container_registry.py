"""Compile explicitly declared source-backed containers, never infer missing IDs."""
import copy

from src.utils.hierarchy_contract import box
from src.utils.pipeline_trace import traced_stage
from src.utils.relation_evidence import CONTAINER_ALIASES, DESCRIPTORS, normalized


@traced_stage('architect.container_registry')
def compile_container_registry(state, vision_elements, user_intent, inline=False):
    result = copy.deepcopy(state)
    if not isinstance(inline, bool):
        raise ValueError('Invalid registry representation policy')
    if inline:
        if result.get('containers') not in (None, []):
            raise ValueError('Single node table forbids secondary container declarations')
        nodes = result.get('elements')
        if not isinstance(nodes, list) or any(not isinstance(e, dict) for e in nodes):
            raise ValueError('Missing or invalid single node table')
        # Move declarations, do not copy/add nodes or infer undeclared parents.
        result['containers'] = [e for e in nodes if CONTAINER_ALIASES.get(e.get('type'), e.get('type')) in DESCRIPTORS]
        result['elements'] = [e for e in nodes if CONTAINER_ALIASES.get(e.get('type'), e.get('type')) not in DESCRIPTORS]
    registry = result.get('containers')
    elements = result.get('elements')
    if not isinstance(registry, list) or not isinstance(elements, list):
        raise ValueError('Missing typed container registry')
    visual = {e['id']: e for e in vision_elements['elements']}
    ids = set()
    sources = set()
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError('Invalid registry element')
        if CONTAINER_ALIASES.get(element.get('type'), element.get('type')) in DESCRIPTORS:
            raise ValueError('Container must be declared in registry')
        eid = element.get('id')
        if not isinstance(eid, str) or not eid or eid in ids:
            raise ValueError('Duplicate or missing registry element identity')
        ids.add(eid)
        vid = element.get('vision_id') or (eid if eid in visual else None)
        if vid is not None:
            sources.add(vid)
    declarations = []
    view = result.get('page_meta', {}).get('viewport', {})
    for raw in registry:
        if not isinstance(raw, dict):
            raise ValueError('Invalid container declaration')
        node = copy.deepcopy(raw)
        eid = node.get('id')
        kind = CONTAINER_ALIASES.get(node.get('type'), node.get('type'))
        if not isinstance(eid, str) or not eid or eid in ids:
            raise ValueError('Duplicate or missing container identity')
        if kind not in DESCRIPTORS:
            raise ValueError('Registry declaration is not a container')
        node['type'] = kind
        vid = node.get('vision_id')
        if vid is not None:
            if vid not in visual or vid in sources:
                raise ValueError('Invalid or duplicated registry visual source')
            visual_kind = CONTAINER_ALIASES.get(visual[vid].get('type'), visual[vid].get('type'))
            if visual_kind not in DESCRIPTORS:
                raise ValueError('Visual source is not a container')
            sources.add(vid)
            source = {'source': 'vision', 'id': vid}
        else:
            if node.get('origin') != 'spoken' or not eid.startswith('u_'):
                raise ValueError('Container lacks explicit source')
            quote = node.get('evidence_quote')
            if not isinstance(quote, str) or not 2 <= len(quote) <= 400 or quote not in user_intent:
                raise ValueError('Container lacks bounded source quote')
            words = DESCRIPTORS[kind]
            label = normalized(node.get('text') or '')
            if not any(normalized(word) in normalized(quote) for word in words) or (label and label not in normalized(quote)):
                raise ValueError('Container source lacks type or label anchor')
            bounds = box(node.get('spatial_info', {}).get('bbox'))
            if not (0 <= bounds[0] < bounds[2] <= view.get('width', 0) and
                    0 <= bounds[1] < bounds[3] <= view.get('height', 0)):
                raise ValueError('Spoken container outside viewport')
            source = {'source': 'user_intent', 'evidence_quote': quote, 'start': user_intent.index(quote)}
        ids.add(eid)
        elements.append(node)
        declarations.append({'id': eid, 'type': kind, **source})
    # Endpoint closure is checked before the relation ledger. Never fabricate a
    # declaration from a dangling reference, nor swallow conflicts downstream.
    aliases = {e.get('vision_id') or e['id']: e['id'] for e in elements}
    for edge in result.get('relationships', []):
        if not isinstance(edge, dict) or any(aliases.get(edge.get(k), edge.get(k)) not in ids for k in ('parent_id', 'child_id')):
            raise ValueError('Undeclared registry relationship endpoint')
    result.setdefault('page_meta', {})['container_registry'] = {
        'version': 'source-backed-v1', 'declared_count': len(declarations),
        'representation': 'single_node_table' if inline else 'separate_container_table',
        'declarations': declarations, 'semantic_review': 'required; lexical anchors do not prove container meaning'}
    return result
