"""Explicit, reviewed layout-only composite. No identity inference or model calls."""
import copy
import math

CONFIG={'minimum_interactive_width':44,'minimum_interactive_height':44,'gap':8,'minimum_body_height':44}

def compile_composite(source, baseline, contract, transcript):
    if contract.get('status')!='supported':raise ValueError('RELATION_UNKNOWN')
    r=contract['region'];b=r['bbox']
    if not isinstance(b,list) or len(b)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in b):raise ValueError('INVALID_REGION')
    vp=source['page_meta']['viewport'];w,h=vp['width'],vp['height']
    if not(0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h):raise ValueError('INVALID_REGION')
    es={e['id']:e for e in source['elements']};bs={e['id']:e for e in baseline['elements']}
    if len(es)!=len(source['elements']) or set(es)!=set(bs):raise ValueError('IDENTITY_MISMATCH')
    tools=r['tools'];ids=[r['input_id']]+[t['id'] for t in tools]
    if len(set(ids))!=len(ids) or any(i not in es for i in ids):raise ValueError('UNKNOWN_OR_DUPLICATE_MEMBER')
    if es[r['input_id']]['type'] not in ('input','search_input','input_field'):raise ValueError('BODY_TYPE_UNKNOWN')
    for t in tools:
        if t['horizontal_anchor'] not in ('left','right') or t['vertical_anchor']!='bottom':raise ValueError('UNSUPPORTED_ANCHOR')
        if not t.get('quote') or t['quote'] not in transcript:raise ValueError('SOURCE_QUOTE_NOT_FOUND')
    for i in ids:
        a=es[i]['spatial_info']['bbox']
        if not(a[0]<a[2] and a[1]<a[3]):raise ValueError('INVALID_SOURCE_GEOMETRY')
        if not(b[0]<=a[0] and b[1]<=a[1] and a[2]<=b[2] and a[3]<=b[3]):raise ValueError('REGION_DOES_NOT_COVER_MEMBERS')
    gap=CONFIG['gap'];tool_h=CONFIG['minimum_interactive_height']
    if b[3]-b[1] < CONFIG['minimum_body_height']+gap+tool_h:raise ValueError('UNSAT_HEIGHT: requires 96 pixels')
    widths={t['id']:max(CONFIG['minimum_interactive_width'],es[t['id']]['spatial_info']['bbox'][2]-es[t['id']]['spatial_info']['bbox'][0]) for t in tools}
    if sum(widths.values())+gap*max(0,len(tools)-1)>b[2]-b[0]:raise ValueError('UNSAT_WIDTH')
    boxes={r['input_id']:[b[0],b[1],b[2],b[3]-tool_h-gap]}
    for side in ('left','right'):
        group=sorted([t for t in tools if t['horizontal_anchor']==side],key=lambda t:t['order'])
        if len({t['order'] for t in group})!=len(group):raise ValueError('ORDER_AMBIGUOUS')
        total=sum(widths[t['id']] for t in group)+gap*max(0,len(group)-1)
        cursor=b[0] if side=='left' else b[2]-total
        for t in group:
            boxes[t['id']]=[cursor,b[3]-tool_h,cursor+widths[t['id']],b[3]];cursor+=widths[t['id']]+gap
    result=copy.deepcopy(baseline)
    for e in result['elements']:
        if e['id'] not in boxes:continue
        a=boxes[e['id']];s=e.setdefault('spatial_info',{})
        s.update(bbox=a,evidence_bbox=copy.deepcopy(es[e['id']]['spatial_info']['bbox']),source='constraint_layout_solver',
                 center_ratio=[round((a[0]+a[2])/(2*w),4),round((a[1]+a[3])/(2*h),4)],
                 size_ratio=[round((a[2]-a[0])/w,4),round((a[3]-a[1])/h,4)],aspect_ratio=round((a[2]-a[0])/(a[3]-a[1]),4))
    def overlap(a,c):return min(a[2],c[2])>max(a[0],c[0]) and min(a[3],c[3])>max(a[1],c[1])
    for i,a in boxes.items():
        for e in result['elements']:
            if e['id']!=i and overlap(a,e['spatial_info']['bbox']):raise ValueError('UNSAT_COLLISION:'+i+':'+e['id'])
    return result
