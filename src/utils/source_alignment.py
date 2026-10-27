"""Conservative cross-source identity alignment, without case labels or API calls."""
import copy
import math
import unicodedata


def _family(value):
    value = str(value or '').lower()
    return {'search_bar': 'input', 'search_input': 'input', 'text_input': 'input',
            'navigation_bar': 'navigation', 'nav': 'navigation'}.get(value, value)


def _text(element):
    return ''.join(unicodedata.normalize('NFKC', str(element.get('text') or '')).split()).lower()


def _model_box(element, viewport):
    spatial = element.get('spatial_info')
    if not isinstance(spatial, dict):
        return None
    box = spatial.get('bbox')
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        values = [float(v) for v in box]
        box = [values[0]/viewport['width'], values[1]/viewport['height'],
               values[2]/viewport['width'], values[3]/viewport['height']]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return box if all(math.isfinite(x) for x in box) and box[0] < box[2] and box[1] < box[3] else None


def _score(model, vision, viewport):
    family = _family(model.get('type'))
    if family in {'', 'unknown'} or family != _family(vision.get('type')):
        return None
    a = _model_box(model, viewport)
    raw = vision.get('bbox') or {}
    try:
        b = [float(raw[k]) for k in ('x_min', 'y_min', 'x_max', 'y_max')]
    except (KeyError, TypeError, ValueError):
        return None
    if a is None or not all(math.isfinite(x) for x in b) or b[0] >= b[2] or b[1] >= b[3]:
        return None
    ta, tb = _text(model), _text(vision)
    if ta and tb and ta != tb:
        return None
    aw, ah, bw, bh = a[2]-a[0], a[3]-a[1], b[2]-b[0], b[3]-b[1]
    dx, dy = abs(a[0]+a[2]-b[0]-b[2])/2, abs(a[1]+a[3]-b[1]-b[3])/2
    if dx > .08 or dy > .08 or not (.25 <= aw/bw <= 4 and .25 <= ah/bh <= 4):
        return None
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    iou = intersection / (aw*ah+bw*bh-intersection)
    if iou < .1:
        return None
    center = 1-min(math.hypot(dx, dy)/.12, 1)
    size = 1-min((abs(aw-bw)+abs(ah-bh))/.35, 1)
    return min(1, .55*iou+.25*center+.20*size+(.1 if ta and ta == tb else 0))


def align_source_ids(model_elements, vision_elements, viewport):
    """Keep exact ids, then accept only reciprocal, unambiguous geometric matches.

    Unresolved objects are retained; the caller's normal fallback remains visible.
    Returns a copy plus auditable decisions, never changes the input evidence.
    """
    models = copy.deepcopy(model_elements)
    vision = {e['id']: e for e in vision_elements if isinstance(e, dict) and e.get('id')}
    if len(vision) != sum(isinstance(e, dict) and bool(e.get('id')) for e in vision_elements):
        raise ValueError('Duplicate vision ids cannot be aligned safely')
    mids = [e.get('id') for e in models if isinstance(e, dict) and e.get('id')]
    if len(mids) != len(set(mids)):
        raise ValueError('Duplicate model ids cannot be aligned safely')
    matches = {i: e['id'] for i, e in enumerate(models) if isinstance(e, dict) and e.get('id') in vision}
    reserved = set(matches.values())
    pairs = {}
    for i, element in enumerate(models):
        if i in matches or not isinstance(element, dict):
            continue
        for vid, candidate in vision.items():
            if vid not in reserved:
                score = _score(element, candidate, viewport)
                if score is not None:
                    pairs[i, vid] = score
    def unique_best(options):
        options = sorted(options, key=lambda x: x[0], reverse=True)
        if not options or options[0][0] < .45 or len(options) > 1 and options[0][0]-options[1][0] < .12:
            return None
        return options[0][1]
    for i in range(len(models)):
        if i in matches:
            continue
        vid = unique_best([(s, v) for (j, v), s in pairs.items() if j == i])
        if vid is not None and unique_best([(s, j) for (j, v), s in pairs.items() if v == vid]) == i:
            matches[i] = vid
    aliases, decisions = {}, []
    for i, element in enumerate(models):
        if not isinstance(element, dict):
            continue
        old = element.get('id')
        vid = matches.get(i)
        if vid is not None:
            if old:
                aliases[old] = vid
            element['id'] = vid
            element['source_refs'] = [{'source': 'vision', 'id': vid},
                                      {'source': 'architect', 'index': i, 'id': old}]
            if old != vid:
                element['model_id'] = old
            reason = 'exact_id' if old == vid else 'reciprocal_geometry_type_text'
        else:
            if not old:
                eid = 'architect_only_' + str(i)
                occupied = set(mids) | set(vision)
                while eid in occupied:
                    eid += '_'
                element['id'] = eid
            element['source_refs'] = [{'source': 'architect', 'index': i, 'id': old}]
            reason = 'unresolved_candidates' if any(j == i for j, v in pairs) else 'no_compatible_candidate'
        decisions.append({'model_index': i, 'model_id': old, 'vision_id': vid,
                          'reason': reason, 'score': pairs.get((i, vid)),
                          'candidates': [{'vision_id': v, 'score': s} for (j, v), s in pairs.items() if j == i]})
    for element in models:
        if not isinstance(element, dict):
            continue
        if element.get('parent_id') in aliases:
            element['parent_id'] = aliases[element['parent_id']]
        if isinstance(element.get('children_ids'), list):
            element['children_ids'] = [aliases.get(x, x) for x in element['children_ids']]
    return models, decisions
