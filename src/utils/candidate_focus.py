"""One shared observation window for every candidate, with no semantic labels."""
import math


def focus_bounds(proposals, width, height):
    if width < 1 or height < 1:
        raise ValueError('Invalid image size')
    points=[p for c in proposals['candidates'] for p in c['quad']]
    if not points:
        return [0,0,width,height]
    if any(len(p)!=2 or not all(math.isfinite(v) for v in p) or
           not (0<=p[0]<width and 0<=p[1]<height) for p in points):
        raise ValueError('Candidate outside original evidence')
    xs,ys=zip(*points)
    dx=max(8,(max(xs)-min(xs))*.12);dy=max(8,(max(ys)-min(ys))*.12)
    return [max(0,math.floor(min(xs)-dx)),max(0,math.floor(min(ys)-dy)),
            min(width,math.ceil(max(xs)+dx)),min(height,math.ceil(max(ys)+dy))]
