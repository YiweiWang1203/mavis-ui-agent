"""Observed collinear support for boundary proposals; never modifies input strokes."""
import math


def union_intervals(intervals):
    result=[]
    for a,b in sorted((min(a,b),max(a,b)) for a,b in intervals):
        if not result or a>result[-1][1]:result.append([a,b])
        else:result[-1][1]=max(result[-1][1],b)
    return result


def direction(row):
    a=row['endpoints'];dx,dy=a[2]-a[0],a[3]-a[1];n=math.hypot(dx,dy)
    if n<=0:raise ValueError('Zero length source line')
    if dx<0 or (dx==0 and dy<0):dx,dy=-dx,-dy
    return dx/n,dy/n


def support_on_side(row,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if length<=0:raise ValueError('Degenerate boundary side')
    intervals=[]
    for segment in row.get('source_segments',[row['endpoints']]):
        ts=[((x-a[0])*dx+(y-a[1])*dy)/length for x,y in [segment[:2],segment[2:]]]
        lo,hi=max(0,min(ts)),min(length,max(ts))
        if hi>lo:intervals.append([lo,hi])
    merged=union_intervals(intervals)
    if not merged:return dict(fraction=0,start_extension=length,end_extension=length,max_internal_gap=length,intervals=[])
    return dict(fraction=sum(y-x for x,y in merged)/length,start_extension=merged[0][0],
                end_extension=length-merged[-1][1],
                max_internal_gap=max([merged[i+1][0]-merged[i][1] for i in range(len(merged)-1)]+[0]),
                intervals=merged)


def aggregate_fragments(lines,width,height):
    """Anchor bounded neighborhoods avoid transitive drift across parallel frames."""
    if len(lines)>48:raise ValueError('Source line cap exceeded')
    distance_limit=.012*min(width,height)
    gap_limit=.06*min(width,height)
    groups={}
    for anchor in lines:
        ux,uy=direction(anchor);ax,ay=anchor['endpoints'][:2]
        nearby=[]
        for row in lines:
            if row['orientation']!=anchor['orientation']:continue
            vx,vy=direction(row)
            if abs(ux*vx+uy*vy)<math.cos(math.radians(8)):continue
            pts=[row['endpoints'][:2],row['endpoints'][2:]]
            if max(abs((x-ax)*uy-(y-ay)*ux) for x,y in pts)>distance_limit:continue
            ts=sorted((x-ax)*ux+(y-ay)*uy for x,y in pts)
            nearby.append((ts[0],ts[1],row))
        components=[]
        for lo,hi,row in sorted(nearby,key=lambda r:r[0]):
            if not components or lo>components[-1]['end']+gap_limit:
                components.append(dict(end=hi,rows=[row]))
            else:
                components[-1]['end']=max(hi,components[-1]['end']);components[-1]['rows'].append(row)
        for component in components:
            rows=component['rows']
            if anchor['id'] not in {r['id'] for r in rows}:continue
            key=tuple(sorted(r['id'] for r in rows))
            if key in groups:continue
            points=[p for r in rows for p in [r['endpoints'][:2],r['endpoints'][2:]]]
            cx=sum(p[0] for p in points)/len(points);cy=sum(p[1] for p in points)/len(points)
            xx=sum((x-cx)**2 for x,y in points);yy=sum((y-cy)**2 for x,y in points)
            xy=sum((x-cx)*(y-cy) for x,y in points)
            angle=.5*math.atan2(2*xy,xx-yy);fx,fy=math.cos(angle),math.sin(angle)
            if fx*ux+fy*uy<0:fx,fy=-fx,-fy
            if max(abs((x-cx)*fy-(y-cy)*fx) for x,y in points)>distance_limit:continue
            projections=[(x-cx)*fx+(y-cy)*fy for x,y in points];lo,hi=min(projections),max(projections)
            segment=[cx+lo*fx,cy+lo*fy,cx+hi*fx,cy+hi*fy]
            observation=union_intervals([[(r['endpoints'][0]-cx)*fx+(r['endpoints'][1]-cy)*fy,
                                          (r['endpoints'][2]-cx)*fx+(r['endpoints'][3]-cy)*fy] for r in rows])
            groups[key]=dict(endpoints=segment,orientation=anchor['orientation'],
                source_line_ids=list(key),source_segments=[r['endpoints'][:] for r in rows],
                observed_union_length=sum(b-a for a,b in observation),length=hi-lo)
    retained=[]
    for orientation in ['horizontal','vertical']:
        subset=sorted([r for r in groups.values() if r['orientation']==orientation],
                      key=lambda r:(-r['observed_union_length'],r['source_line_ids']))[:24]
        retained.extend(subset)
    for i,r in enumerate(retained):r['id']='support_'+str(i+1)
    return dict(lines=retained,groups_before_cap=len(groups),distance_limit_px=distance_limit,
                local_gap_limit_px=gap_limit,angle_limit_degrees=8,
                limits='Fitted support proposals only. Gaps remain unobserved; original strokes unchanged.')


def validate_fragment_sides(lines,result,width,height):
    index={r['id']:r for r in lines};details={};all_ids=[]
    q=result['quad']
    for i,role in enumerate(['top','right','bottom','left']):
        row=index[result['side_ids'][role]]
        all_ids.extend(row['source_line_ids'])
        detail=support_on_side(row,q[i],q[(i+1)%4]);length=math.dist(q[i],q[(i+1)%4])
        extension_cap=min(.12*length,.05*min(width,height))
        if detail['fraction']<.60:raise ValueError('Observed union below 60 percent')
        if max(detail['start_extension'],detail['end_extension'])>extension_cap:
            raise ValueError('Corner extension limit exceeded')
        if detail['max_internal_gap']>.15*length:raise ValueError('Unobserved internal gap too large')
        detail.update(source_line_ids=row['source_line_ids'],extension_cap=extension_cap)
        details[role]=detail
    if len(set(all_ids))!=len(all_ids):raise ValueError('Source line reused across sides')
    return details
