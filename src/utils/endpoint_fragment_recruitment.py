"""Observe nearby short strokes at existing support ends; never draw missing lines."""
import copy
import math
from src.utils.fragment_boundary import direction, union_intervals


def recruit_endpoint_fragments(support, selected, raw_segments, width, height):
    limit=.012*min(width,height);gap_cap=.06*min(width,height)
    selected_coords={tuple(r['endpoints']) for r in selected}
    rows=[];log=[];observed=set()
    for group in support['lines']:
        out=copy.deepcopy(group);ux,uy=direction(group);ax,ay=group['endpoints'][:2]
        lo0,hi0=sorted((x-ax)*ux+(y-ay)*uy for x,y in [group['endpoints'][:2],group['endpoints'][2:]])
        options={'start':[],'end':[]}
        for i,segment in enumerate(raw_segments):
            if tuple(segment) in selected_coords:continue
            dx,dy=segment[2]-segment[0],segment[3]-segment[1];length=math.hypot(dx,dy)
            if length<=0 or length>=.12*min(width,height):continue
            if abs((ux*dx+uy*dy)/length)<math.cos(math.radians(8)):continue
            if max(abs((x-ax)*uy-(y-ay)*ux) for x,y in [segment[:2],segment[2:]])>limit:continue
            lo,hi=sorted((x-ax)*ux+(y-ay)*uy for x,y in [segment[:2],segment[2:]])
            if max(lo0-hi,lo-hi0,0)>gap_cap:continue
            record=dict(raw_id='raw_'+str(i+1),segment=segment[:],length=length)
            if lo<lo0:options['start'].append(dict(record,extension=lo0-lo))
            if hi>hi0:options['end'].append(dict(record,extension=hi-hi0))
        chosen={}
        for side in ['start','end']:
            if options[side]:
                r=sorted(options[side],key=lambda r:(-r['extension'],-r['length'],r['raw_id']))[0]
                chosen[r['raw_id']]=r
        decision=dict(support_id=group['id'],proposed=list(chosen),applied=[],status='no_short_extension')
        if chosen:
            segments=group['source_segments']+[r['segment'] for r in chosen.values()]
            points=[p for s in segments for p in [s[:2],s[2:]]]
            cx=sum(p[0] for p in points)/len(points);cy=sum(p[1] for p in points)/len(points)
            xx=sum((x-cx)**2 for x,y in points);yy=sum((y-cy)**2 for x,y in points);xy=sum((x-cx)*(y-cy) for x,y in points)
            angle=.5*math.atan2(2*xy,xx-yy);fx,fy=math.cos(angle),math.sin(angle)
            if fx*ux+fy*uy<0:fx,fy=-fx,-fy
            if max(abs((x-cx)*fy-(y-cy)*fx) for x,y in points)>limit:
                decision['status']='refit_rejected_distance'
            else:
                ts=[(x-cx)*fx+(y-cy)*fy for x,y in points];lo,hi=min(ts),max(ts)
                intervals=union_intervals([[(s[0]-cx)*fx+(s[1]-cy)*fy,(s[2]-cx)*fx+(s[3]-cy)*fy] for s in segments])
                out.update(endpoints=[cx+lo*fx,cy+lo*fy,cx+hi*fx,cy+hi*fy],source_segments=segments,
                    source_line_ids=group['source_line_ids']+list(chosen),length=hi-lo,
                    observed_union_length=sum(b-a for a,b in intervals))
                decision.update(status='applied',applied=list(chosen));observed.update(chosen)
        rows.append(out);log.append(decision)
    return dict(lines=rows,recruitment_log=log,unique_added_raw_count=len(observed),
        proposed_source_reference_cap=2*len(rows),max_total_source_observations=48+2*len(rows),
        limits='Existing support anchors only; at most one observed short segment per end, no iterative growth or invented strokes.')
