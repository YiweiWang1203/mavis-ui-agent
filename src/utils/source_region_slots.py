"""Source-backed region evidence, without inventing page geometry or layout."""
import math
import copy


def decode_region_coordinates(declaration, scale):
    """Decode the declared experiment convention; never infer scale from values."""
    if scale not in (1, 1000) or isinstance(scale, bool):
        raise ValueError('Unsupported explicit grounding scale')
    if not isinstance(declaration, dict) or set(declaration) != {'bindings'} or not isinstance(declaration['bindings'], list):
        raise ValueError('Expected bindings for explicit coordinate decode')
    result = copy.deepcopy(declaration)
    for row in result['bindings']:
        if not isinstance(row, dict) or 'bbox' not in row:
            raise ValueError('Binding bbox missing')
        box = row['bbox']
        if box is None:
            continue
        if not isinstance(box, list) or len(box) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
            raise ValueError('Expected four finite coordinate values')
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= scale and 0 <= y0 < y1 <= scale):
            raise ValueError('Coordinates outside declared scale; no clamping or unit guessing')
        row['bbox'] = [v / scale for v in box]
    return result


def inventory_slots(declaration, transcript):
    if not isinstance(declaration, dict) or set(declaration) != {'regions'}:
        raise ValueError('Expected only regions')
    rows = declaration['regions']
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError('Expected at most twenty regions')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'name', 'source_quote'}:
            raise ValueError('Invalid source region fields')
        if any(not isinstance(row[k], str) or not row[k].strip() for k in row):
            raise ValueError('Region strings must be nonempty')
        if row['id'] in seen or row['id'] == 'page':
            raise ValueError('Duplicate or reserved region ID')
        seen.add(row['id'])
        quote = row['source_quote']
        start = transcript.find(quote)
        if start < 0 or transcript.find(quote, start + 1) >= 0:
            raise ValueError('Source quote must be a unique verbatim transcript substring')
        result.append({**row, 'source_start': start, 'source_end': start + len(quote)})
    return result


def bind_regions(slots, declaration):
    if not isinstance(declaration, dict) or set(declaration) != {'bindings'}:
        raise ValueError('Expected only bindings')
    rows = declaration['bindings']
    if not isinstance(rows, list):
        raise ValueError('Expected bindings list')
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'region_id', 'bbox', 'visual_evidence'}:
            raise ValueError('Invalid binding fields')
        rid = row['region_id']
        if not isinstance(rid, str) or rid in by_id:
            raise ValueError('Invalid or duplicate region ID')
        if not isinstance(row['visual_evidence'], str) or not row['visual_evidence'].strip():
            raise ValueError('Binding needs visible evidence or unresolved reason')
        box = row['bbox']
        if box is not None:
            if not isinstance(box, list) or len(box) != 4 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
                raise ValueError('Expected four finite normalized coordinates')
            x0, y0, x1, y1 = box
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError('Invalid normalized bbox; no automatic clamping')
        by_id[rid] = row
    if set(by_id) != {row['id'] for row in slots}:
        raise ValueError('Every source slot requires exactly one binding, including unresolved slots')
    return {'regions': [{**s, 'parent_id': 'page', 'bbox': by_id[s['id']]['bbox'],
                         'visual_evidence': by_id[s['id']]['visual_evidence']} for s in slots],
            'proposed_count': len(slots),
            'localized_count': sum(by_id[s['id']]['bbox'] is not None for s in slots),
            'unresolved_count': sum(by_id[s['id']]['bbox'] is None for s in slots),
            'limits': 'Evidence parent only; not inferred page boundary, semantic accuracy or HTML layout'}
