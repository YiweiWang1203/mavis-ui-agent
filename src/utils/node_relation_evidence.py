"""Compile a single authoritative per-child parent/evidence declaration."""
import copy
from src.utils.pipeline_trace import traced_stage


@traced_stage('architect.node_relation_compile')
def compile_node_relations(state):
    result = copy.deepcopy(state)
    if result.get('relationships') not in (None, []):
        raise ValueError('Node-owned relations forbid a parallel relationship ledger')
    elements = result.get('elements')
    if not isinstance(elements, list):
        raise ValueError('Missing relation node table')
    ids = set(); edges = []
    for node in elements:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id'] or node['id'] in ids:
            raise ValueError('Invalid or duplicate relation node identity')
        ids.add(node['id'])
        parent = node.get('parent_id')
        quote = node.get('parent_evidence_quote')
        if parent is None:
            if quote not in (None, ''):
                raise ValueError('Parent evidence has no parent declaration')
            continue
        if not isinstance(parent, str) or not parent:
            raise ValueError('Invalid node parent identity')
        # Missing or unusable quotes remain proposed edges. The existing source
        # validator records them as unresolved; never silently accept the parent.
        edges.append({'parent_id': parent, 'child_id': node['id'], 'evidence_quote': quote})
    result['relationships'] = edges
    result.setdefault('page_meta', {})['relation_declarations'] = {
        'version': 'node-owned-v1', 'proposed_count': len(edges),
        'status': 'source_validation_pending', 'coverage': 'not_established_by_compilation'}
    return result
