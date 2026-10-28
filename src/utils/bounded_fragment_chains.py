"""At most two observed short strokes per endpoint, with final global-fit validation."""
import copy
import math
from src.utils.fragment_boundary import direction,union_intervals


def recruit_fragment_chains(support,selected,raw_segments,width,height):
    distance=.012*min(width,height);gap_cap=.06*min(width,height);cosine=math.cos(math.radians(8))
    selected_coords={tuple(r['endpoints']) for r in selected};short=[]
    for i,s in enumerate(raw_segments):
        length=math.hypot(s[2]-s[0],s[3]-s[1])
        if tuple(s) not in selected_coords and 0<length<.12*min(width,height):
            short.append(dict(raw_id='raw_'+str(i+1),segment=s[:],length=length))
    rows=[];logs=[];observed=set()
    for group in support['lines']:
        out=copy.deepcopy(group);ux,uy=direction(group);ax,ay=group['endpoints'][:2]
        def project(s):return sorted((x-ax)*ux+(y-ay)*uy for x,y in [s[:2],s[2:]])
        original=project(group['endpoints']);chains=[]
        for side in ['start','end']:
            paths=[]
            def visit(previous,edge,path):
                if len(path)==2:return
                vx,vy=direction(dict(endpoints=previous));px,py=previous[:2];prev=project(previous)
                for r in short:
                    if r['raw_id'] in {q['raw_id'] for q in path}:continue
                    s=r['segment'];dx,dy=s[2]-s[0],s[3]-s[1]
                    if abs((ux*dx+uy*dy)/r['length'])<cosine or abs((vx*dx+vy*dy)/r['length'])<cosine:continue
                    if max(abs((x-px)*vy-(y-py)*vx) for x,y in [s[:2],s[2:]])>distance:continue
                    lo,hi=project(s)
                    if max(prev[0]-hi,lo-prev[1],0)>gap_cap:continue
                    boundary=lo if side=='start' else hi
                    if not (boundary<edge-1e-9 if side=='start' else boundary>edge+1e-9):continue
                    new=path+[r];extension=original[0]-lo if side=='start' else hi-original[1]
                    paths.append((extension,new));visit(s,boundary,new)
            visit(group['endpoints'],original[0] if side=='start' else original[1],[])
            chain=sorted(paths,key=lambda z:(-z[0],-sum(r['length'] for r in z[1]),tuple(r['raw_id'] for r in z[1])))[0][1] if paths else []
            chains.append(dict(side=side,raw_ids=[r['raw_id'] for r in chain],path=chain))
        chosen={r['raw_id']:r for c in chains for r in c['path']}
        log=dict(support_id=group['id'],chains=[{k:v for k,v in c.items() if k!='path'} for c in chains],proposed=list(chosen),applied=[],status='no_extension')
        if chosen:
            segments=group['source_segments']+[r['segment'] for r in chosen.values()]
            pts=[p for s in segments for p in [s[:2],s[2:]]];cx=sum(x for x,y in pts)/len(pts);cy=sum(y for x,y in pts)/len(pts)
            xx=sum((x-cx)**2 for x,y in pts);yy=sum((y-cy)**2 for x,y in pts);xy=sum((x-cx)*(y-cy) for x,y in pts)
            angle=.5*math.atan2(2*xy,xx-yy);fx,fy=math.cos(angle),math.sin(angle)
            if fx*ux+fy*uy<0:fx,fy=-fx,-fy
            residual=max(abs((x-cx)*fy-(y-cy)*fx) for x,y in pts);log['max_fit_residual']=residual
            if residual>distance:log['status']='refit_rejected_distance'
            else:
                ts=[(x-cx)*fx+(y-cy)*fy for x,y in pts];lo,hi=min(ts),max(ts)
                intervals=union_intervals([[(s[0]-cx)*fx+(s[1]-cy)*fy,(s[2]-cx)*fx+(s[3]-cy)*fy] for s in segments])
                out.update(endpoints=[cx+lo*fx,cy+lo*fy,cx+hi*fx,cy+hi*fy],source_segments=segments,source_line_ids=group['source_line_ids']+list(chosen),length=hi-lo,observed_union_length=sum(b-a for a,b in intervals))
                log.update(status='applied',applied=list(chosen));observed.update(chosen)
        rows.append(out);logs.append(log)
    return dict(lines=rows,recruitment_log=logs,unique_added_raw_count=len(observed),max_hops_per_end=2,proposed_source_reference_cap=4*len(rows),max_total_source_observations=48+4*len(rows),limits='Observed bounded paths only; local adjacency differs from global one-hop eligibility; final fit and closure constraints unchanged.')
