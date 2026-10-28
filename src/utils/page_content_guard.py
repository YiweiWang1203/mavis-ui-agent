"""Veto a proposed page when independently observed UI content lies outside it."""
import math
from src.utils.closed_page_candidates import select_candidate


def validate_regions(declaration):
    if not isinstance(declaration, dict) or set(declaration) != {'regions', 'uncertain'} or type(declaration['uncertain']) is not bool:
        raise ValueError('Expected regions and boolean uncertain')
    rows = declaration['regions']
    if not isinstance(rows, list):
        raise ValueError('regions must be an array')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'name', 'point', 'visual_evidence'}:
            raise ValueError('Incomplete region evidence schema')
        for key in ['id', 'name', 'visual_evidence']:
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError('Region strings must be nonempty')
        if row['id'] in ids:
            raise ValueError('Duplicate region ID')
        ids.add(row['id'])
        point = row['point']
        if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
            raise ValueError('Region point outside normalized image; no repair')
    return rows


def region_audit(proposals, declaration, width, height):
    rows = validate_regions(declaration)
    results = []
    for candidate in proposals['candidates']:
        q = candidate['quad']
        signed_area = sum(q[i][0]*q[(i+1)%4][1]-q[(i+1)%4][0]*q[i][1] for i in range(4))
        sign = 1 if signed_area > 0 else -1
        if not signed_area:
            raise ValueError('Degenerate candidate')
        checks = []
        for row in rows:
            x, y = row['point'][0]*width, row['point'][1]*height
            distances = {}
            for i, side in enumerate(['top', 'right', 'bottom', 'left']):
                a, b = q[i], q[(i+1)%4]
                length = math.dist(a, b)
                if not length:
                    raise ValueError('Degenerate side')
                distances[side] = sign*((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]))/length
            outside = [side for side, distance in distances.items() if distance < -1e-9]
            checks.append(dict(region_id=row['id'], inside=not outside, outside_sides=outside, inward_signed_distance_pixels=distances))
        results.append(dict(candidate_id=candidate['id'], points=checks,
                            compatible_with_observed_points=bool(rows) and not declaration['uncertain'] and all(p['inside'] for p in checks)))
    return results


def guard_selection(proposals, selection, declaration, width, height):
    audits = region_audit(proposals, declaration, width, height)
    original = select_candidate(proposals, selection)
    common = dict(content_audit=audits, observation=declaration, limits='Point containment is a necessary consistency check; it does not prove full region coverage or page identity')
    if original.get('quad') is None:
        return dict(original, **common)
    chosen = next(row for row in audits if row['candidate_id'] == selection['candidate_id'])
    if not chosen['compatible_with_observed_points']:
        hints = []
        q = original['quad']
        sign = 1 if sum(q[i][0]*q[(i+1)%4][1]-q[(i+1)%4][0]*q[i][1] for i in range(4)) > 0 else -1
        for i, side in enumerate(['top', 'right', 'bottom', 'left']):
            offending = [p for p in chosen['points'] if side in p['outside_sides']]
            if not offending:
                continue
            a, b = q[i], q[(i+1)%4]; length = math.dist(a, b)
            hints.append(dict(side=side, outside_region_ids=[p['region_id'] for p in offending],
                outward_unit_vector=[sign*(b[1]-a[1])/length, -sign*(b[0]-a[0])/length],
                minimum_parallel_outward_shift_to_include_observed_points_pixels=max(-p['inward_signed_distance_pixels'][side] for p in offending),
                instruction='Seek supported page boundary outward on this side; this lower bound only covers observed points and is not a new edge location'))
        return dict(status='unresolved', quad=None, reason='Selected page is refuted by outside UI points or content observation is insufficient',
                    rejected_candidate_id=selection['candidate_id'], outside_region_ids=[r['region_id'] for r in chosen['points'] if not r['inside']],
                    correction_hints=hints, **common)
    return dict(original, **common, content_guard_status='not_refuted_by_observed_points')
