"""Fixed-budget spatial coverage; no paper or UI-page coordinates are supplied."""
import math


def spatial_retention(eligible, width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Positive image dimensions required')
    result=[]
    for orientation in ['horizontal','vertical']:
        buckets={}
        for r in sorted(eligible,key=lambda r:-r['length']):
            if r['orientation']!=orientation:continue
            a=r['endpoints'];x=(a[0]+a[2])/2;y=(a[1]+a[3])/2
            cell=(min(3,max(0,int(4*y/height))),min(3,max(0,int(4*x/width))))
            buckets.setdefault(cell,[]).append(r)
        chosen=[]
        while len(chosen)<24:
            heads=[]
            for cell,rows in buckets.items():
                while rows:
                    a=rows[0]['endpoints'];mid=[(a[0]+a[2])/2,(a[1]+a[3])/2]
                    if any(math.dist(mid,[(q['endpoints'][0]+q['endpoints'][2])/2,
                                          (q['endpoints'][1]+q['endpoints'][3])/2])<5 for q in chosen):
                        rows.pop(0)
                    else:break
                if rows:heads.append((cell,rows.pop(0)))
            if not heads:break
            for cell,r in sorted(heads,key=lambda item:(-item[1]['length'],item[0])):
                if len(chosen)>=24:break
                a=r['endpoints'];mid=[(a[0]+a[2])/2,(a[1]+a[3])/2]
                if any(math.dist(mid,[(q['endpoints'][0]+q['endpoints'][2])/2,
                                      (q['endpoints'][1]+q['endpoints'][3])/2])<5 for q in chosen):continue
                chosen.append(r)
        result.extend(dict(r,endpoints=r['endpoints'][:]) for r in chosen)
    for i,r in enumerate(result):r['id']='line_'+str(i+1)
    return result
