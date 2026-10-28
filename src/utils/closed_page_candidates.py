"""Bounded geometric proposals; closure does not establish UI-page identity."""
import itertools
import math
from src.utils.page_line_boundary import compile_boundary


def side_overlap(segment, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return 0
    ts = [((x-a[0])*dx+(y-a[1])*dy)/(length*length)
          for x, y in [segment[:2], segment[2:]]]
    return max(0, min(1, max(ts))-max(0, min(ts)))


def closed_candidates(lines, width, height, limit=16):
    if len(lines) > 48 or limit > 16 or limit < 1:
        raise ValueError('Bounded proposal budget exceeded')
    horizontal = [r for r in lines if r['orientation']=='horizontal']
    vertical = [r for r in lines if r['orientation']=='vertical']
    if len(horizontal)>24 or len(vertical)>24:
        raise ValueError('Orientation budget exceeded')
    index = {r['id']:r for r in lines}
    if len(index)!=len(lines):
        raise ValueError('Duplicate source line IDs')
    valid = []
    rejected = 0
    for hs, vs in itertools.product(itertools.combinations(horizontal, 2),
                                     itertools.combinations(vertical, 2)):
        top, bottom = sorted(hs,key=lambda r:(r['endpoints'][1]+r['endpoints'][3])/2)
        left, right = sorted(vs,key=lambda r:(r['endpoints'][0]+r['endpoints'][2])/2)
        ids = dict(top=top['id'],right=right['id'],bottom=bottom['id'],left=left['id'])
        try:
            result = compile_boundary(lines,dict(side_ids=ids,unresolved_reason=None),width,height)
            q = result['quad']
            coverage = {role:side_overlap(index[ids[role]]['endpoints'],q[i],q[(i+1)%4])
                        for i,role in enumerate(['top','right','bottom','left'])}
            if min(coverage.values()) < .60:
                raise ValueError('Projected support below 60 percent on a side')
            result.update(side_ids=ids,projected_support=coverage,
                          ranking_score=result['area_fraction']*min(coverage.values()))
            valid.append(result)
        except ValueError:
            rejected += 1
    unique = []
    for r in sorted(valid,key=lambda r:-r['ranking_score']):
        # Suppress near-identical double-stroke proposals, not nested UI regions.
        if any(max(math.dist(a,b) for a,b in zip(r['quad'],s['quad'])) < .012*min(width,height)
               for s in unique):
            continue
        unique.append(r)
    selected = unique[:limit]
    for i,r in enumerate(selected):
        r['id']='page_candidate_'+str(i+1)
    return dict(candidates=selected,valid_combinations=len(valid),
                unique_before_cap=len(unique),rejected_combinations=rejected,
                candidate_cap=limit,limits='Geometry only; ranking is not semantic correctness.')


def select_candidate(proposals, declaration):
    if not isinstance(declaration,dict) or set(declaration)!={'candidate_id','unresolved_reason'}:
        raise ValueError('Invalid candidate selection schema')
    key = declaration['candidate_id']
    if key is None:
        if not isinstance(declaration['unresolved_reason'],str) or not declaration['unresolved_reason'].strip():
            raise ValueError('Unresolved selection requires reason')
        return dict(status='unresolved',quad=None,reason=declaration['unresolved_reason'])
    index = {r['id']:r for r in proposals['candidates']}
    if key not in index or declaration['unresolved_reason'] is not None:
        raise ValueError('Unknown candidate or inconsistent reason')
    return dict(index[key],status='candidate_requires_visual_review')
