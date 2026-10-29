"""A type-only comparison must not silently change identity or geometry."""
import copy


def validate_requirement_recovery(before, after):
    old, new = before['elements'], after['elements']
    if len(old) != len(new) or [e['id'] for e in old] != [e['id'] for e in new]:
        raise ValueError('Requirement recovery changed inventory')
    accepted = {p['vision_id'] for p in after.get('page_meta', {}).get('spoken_input_evidence', {}).get('accepted', [])}
    changed = []
    for a, b in zip(old, new):
        clean = copy.deepcopy(b)
        if a.get('type') != b.get('type'):
            vid = a.get('vision_id') or a['id']
            if (a.get('type'), b.get('type')) != ('text', 'input') or vid not in accepted:
                raise ValueError('Unaccepted type change')
            clean['type'] = a['type']
            clean.pop('semantic_type_evidence', None)
            changed.append(a['id'])
        if clean != a:
            raise ValueError('Requirement recovery changed immutable element fields')
    return {'changed_ids': changed, 'identity_geometry_text_parent_actions_preserved': True,
            'scope': 'Explicit editable source requirements only; not full semantic recovery'}
