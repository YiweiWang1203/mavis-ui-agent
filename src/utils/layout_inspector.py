import json
from pathlib import Path
from typing import List, Dict


def _area(bbox):
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def _intersect(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0
    return (x2 - x1) * (y2 - y1)


def inspect_ui_contract(contract: Dict) -> List[Dict]:
    """Given a ui contract dict with 'elements' list where each element has 'id' and 'spatial_info':{'bbox':[x1,y1,x2,y2]}
    BBoxes are assumed to be absolute pixels or normalized (0-1). If normalized, we map to 375x812.
    Returns list of overlap records.
    """
    elements = contract.get("elements") or contract.get("components") or []
    # infer viewport
    viewport = contract.get("page_meta", {}).get("viewport") or {"width": 375, "height": 812}
    w = viewport.get("width", 375)
    h = viewport.get("height", 812)

    boxes = []
    for e in elements:
        eid = e.get("id") or e.get("type")
        bbox = None
        si = e.get("spatial_info") or {}
        b = si.get("bbox")
        if b and isinstance(b, list) and len(b) == 4:
            # detect normalized (0-1) if values <=1
            if max(b) <= 1.01:
                bbox = [b[0] * w, b[1] * h, b[2] * w, b[3] * h]
            else:
                bbox = b
        else:
            # try other keys
            for key in ["bbox", "pixel_bbox", "box"]:
                if key in e:
                    b = e[key]
                    if isinstance(b, list) and len(b) == 4:
                        bbox = b
                        break
        if bbox:
            boxes.append({"id": eid, "bbox": [float(x) for x in bbox]})

    overlaps = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a = boxes[i]["bbox"]
            b = boxes[j]["bbox"]
            inter = _intersect(a, b)
            if inter > 0:
                area_a = _area(a)
                area_b = _area(b)
                ratio_a = inter / area_a if area_a > 0 else 0
                ratio_b = inter / area_b if area_b > 0 else 0
                severity = "low"
                if max(ratio_a, ratio_b) > 0.5:
                    severity = "high"
                elif max(ratio_a, ratio_b) > 0.2:
                    severity = "medium"

                overlaps.append({
                    "component_a": boxes[i]["id"],
                    "component_b": boxes[j]["id"],
                    "bbox_a": a,
                    "bbox_b": b,
                    "overlap_area": inter,
                    "overlap_ratio_a": ratio_a,
                    "overlap_ratio_b": ratio_b,
                    "severity": severity,
                    "suspected_reason": "bbox conflict"
                })
    return overlaps

def save_overlap_report(contract: Dict, out_path: str):
    overlaps = inspect_ui_contract(contract)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(overlaps, ensure_ascii=False, indent=2), encoding="utf-8")
    return overlaps
