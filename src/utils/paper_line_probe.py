"""Visible-paper preprocessing and line evidence; no UI boundary identity claims."""
import math


def visible_paper(image):
    import cv2
    import numpy as np
    # White/neutral paper is an explicit hypothesis, not a universal paper segmenter.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    chroma = np.sqrt((lab[:, :, 1]-128)**2+(lab[:, :, 2]-128)**2)
    threshold, raw = cv2.threshold(np.uint8(np.clip(chroma, 0, 255)), 0, 255,
                                  cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    raw[lab[:, :, 0] < 80] = 0
    raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw)
    if count < 2:
        return None, {'status': 'unresolved', 'reason': 'no neutral component'}
    label = 1+int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.uint8(labels == label)*255
    # Fill internal pen strokes without using the UI boundary or semantic annotations.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(mask, contours, -1, 255, cv2.FILLED)
    fraction = float(np.count_nonzero(mask)/mask.size)
    if not .1 < fraction < .98:
        return None, {'status': 'unresolved', 'reason': 'ambiguous area', 'area_fraction': fraction}
    ys, xs = np.where(mask > 0)
    h, w = mask.shape
    box = [max(0, int(xs.min())-8), max(0, int(ys.min())-8),
           min(w, int(xs.max())+9), min(h, int(ys.max())+9)]
    return mask, {'status': 'candidate_requires_visual_review', 'bbox_xyxy_exclusive': box,
                  'area_fraction': fraction, 'chroma_otsu_threshold': threshold,
                  'touches_photo_edges': {'left': bool(mask[:, 0].any()),
                      'right': bool(mask[:, -1].any()), 'top': bool(mask[0].any()),
                      'bottom': bool(mask[-1].any())},
                  'complete_paper_boundary_verified': False,
                  'limits': 'Visible neutral component only; not a SAM mask or hand-drawn UI boundary.'}


def line_records(raw, offset=(0, 0)):
    result = []
    for line in raw:
        x1, y1, x2, y2 = map(float, line.reshape(-1)[:4])
        values = [x1+offset[0], y1+offset[1], x2+offset[0], y2+offset[1]]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Nonfinite line endpoint')
        result.append({'id': 'line_'+str(len(result)+1), 'endpoints': values,
                       'length': math.hypot(x2-x1, y2-y1)})
    return result
