"""Read-only geometric containment context; never labels or filters page candidates."""
import copy
import hashlib
import json


def area(poly):
    return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly))))/2 if len(poly)>2 else 0


def convex_intersection(subject,clip):
    output=[list(p) for p in subject]
    signed=sum(clip[i][0]*clip[(i+1)%len(clip)][1]-clip[(i+1)%len(clip)][0]*clip[i][1] for i in range(len(clip)))
    sign=1 if signed>=0 else -1
    for i,a in enumerate(clip):
        b=clip[(i+1)%len(clip)]
        def distance(p):return sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        current=output;output=[]
        if not current:break
        prev=current[-1];dp=distance(prev)
        for point in current:
            dc=distance(point)
            if (dc>=0)!=(dp>=0):
                t=dp/(dp-dc);output.append([prev[0]+t*(point[0]-prev[0]),prev[1]+t*(point[1]-prev[1])])
            if dc>=0:output.append(point)
            prev,dp=point,dc
    return output


def shared_candidate_order(proposals):
    out=copy.deepcopy(proposals)
    def key(r):return hashlib.sha256(json.dumps(r['quad'],separators=(',',':')).encode()).hexdigest()
    out['candidates'].sort(key=key);mapping=[]
    for i,r in enumerate(out['candidates']):
        new='page_candidate_'+str(i+1);mapping.append(dict(original_id=r['id'],shared_id=new));r['id']=new
    return out,mapping


def containment_context(proposals):
    rows=proposals['candidates']
    if len(rows)>16:raise ValueError('Candidate cap exceeded')
    result=[]
    for small in rows:
        small_area=area(small['quad'])
        if small_area<=0:raise ValueError('Degenerate candidate')
        covering=[]
        for large in rows:
            large_area=area(large['quad'])
            if small['id']==large['id'] or large_area/small_area<1.05:continue
            fraction=min(1,max(0,area(convex_intersection(small['quad'],large['quad']))/small_area))
            if fraction>=.95:
                covering.append(dict(candidate_id=large['id'],fraction_inside=round(fraction,6),area_ratio=round(large_area/small_area,6)))
        result.append(dict(candidate_id=small['id'],possible_covering_candidates=covering))
    return dict(rows=result,thresholds=dict(min_area_ratio=1.05,min_covered_fraction=.95),limits='Geometry only: a larger covering polygon can be paper or background. No UI identity labels and no candidates filtered.')
