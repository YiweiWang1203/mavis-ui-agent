"""Observable line-supported page boundary, separate from semantic UI objects."""
import math


def intersection(a,b):
    x1,y1,x2,y2=a; x3,y3,x4,y4=b
    denominator=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
    if abs(denominator)<1e-6:raise ValueError('Parallel boundary sides')
    v=x1*y2-y1*x2; w=x3*y4-y3*x4
    return [(v*(x3-x4)-(x1-x2)*w)/denominator,(v*(y3-y4)-(y1-y2)*w)/denominator]


def compile_boundary(lines,selection,width,height):
    if not isinstance(selection,dict) or set(selection)!={'side_ids','unresolved_reason'}:
        raise ValueError('Expected selected side IDs and unresolved reason')
    if selection['side_ids'] is None:
        return {'status':'unresolved','reason':selection['unresolved_reason'],'quad':None}
    sides=selection['side_ids']
    if set(sides)!={'top','right','bottom','left'} or len(set(sides.values()))!=4:
        raise ValueError('Four distinct side IDs required')
    index={r['id']:r for r in lines}
    if any(k not in index for k in sides.values()):raise ValueError('Unknown line reference')
    selected={role:index[key]['endpoints'] for role,key in sides.items()}
    quad=[intersection(selected['top'],selected['left']),intersection(selected['top'],selected['right']),
          intersection(selected['bottom'],selected['right']),intersection(selected['bottom'],selected['left'])]
    if any(not math.isfinite(v) for p in quad for v in p) or any(not(0<=p[0]<width and 0<=p[1]<height) for p in quad):
        raise ValueError('Line intersections outside image; no clamping')
    crosses=[]
    for i in range(4):
        a,b,c=quad[i],quad[(i+1)%4],quad[(i+2)%4]
        crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    if not(all(v>0 for v in crosses) or all(v<0 for v in crosses)):
        raise ValueError('Boundary is not convex')
    if quad[0][1]>=quad[3][1] or quad[1][1]>=quad[2][1] or quad[0][0]>=quad[1][0]:
        raise ValueError('Side ordering invalid')
    area=abs(sum(quad[i][0]*quad[(i+1)%4][1]-quad[(i+1)%4][0]*quad[i][1] for i in range(4)))/2
    if area<.02*width*height:raise ValueError('Boundary area too small for page candidate')
    # Long extensions indicate a speculative closure rather than observed sides.
    supports={}
    for i,role in enumerate(['top','right','bottom','left']):
        a,b=quad[i],quad[(i+1)%4];line=selected[role]
        length=math.dist(a,b);observed=math.dist(line[:2],line[2:])
        supports[role]={'line_id':sides[role],'side_length':length,'observed_segment_length':observed,
                        'length_ratio':observed/length}
        if observed/length<.35:raise ValueError('Insufficient observed side length')
    return {'status':'candidate_requires_visual_review','quad':quad,
        'normalized_quad':[[x/width,y/height] for x,y in quad],
        'bbox':[min(x for x,y in quad)/width,min(y for x,y in quad)/height,
                max(x for x,y in quad)/width,max(y for x,y in quad)/height],
        'area_fraction':area/(width*height),'side_support':supports,
        'limits':'Detected line references do not prove semantic page identity or complete visibility.'}


def detect_line_candidates(image):
    import cv2
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    h,w=gray.shape
    raw=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    retained=[]
    for row in ([] if raw is None else raw):
        x1,y1,x2,y2=map(float,row[0]);dx=x2-x1;dy=y2-y1
        length=math.hypot(dx,dy)
        if length<.12*min(w,h):continue
        angle=abs(math.degrees(math.atan2(dy,dx)))%180
        orientation='horizontal' if min(angle,180-angle)<20 else 'vertical' if abs(angle-90)<20 else None
        if orientation:retained.append({'endpoints':[x1,y1,x2,y2],'length':length,'orientation':orientation})
    result=[]
    for r in sorted(retained,key=lambda r:-r['length']):
        a=r['endpoints'];mid=[(a[0]+a[2])/2,(a[1]+a[3])/2]
        if any(q['orientation']==r['orientation'] and math.dist(mid,[(q['endpoints'][0]+q['endpoints'][2])/2,(q['endpoints'][1]+q['endpoints'][3])/2])<5 for q in result):continue
        if sum(q['orientation']==r['orientation'] for q in result)>=24:continue
        r['id']='line_'+str(len(result)+1);result.append(r)
    return result
