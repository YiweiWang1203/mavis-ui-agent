"""Candidate-blind page extent observation; match existing evidence, never create a quad."""
import math


def match_observation(proposals, declaration, width, height):
    if not isinstance(declaration, dict) or set(declaration) != {'page_bbox', 'visible_ui_evidence', 'uncertain'}:
        raise ValueError('Expected complete candidate-blind observation schema')
    if type(declaration['uncertain']) is not bool:
        raise ValueError('uncertain must be boolean')
    if not isinstance(declaration['visible_ui_evidence'], str) or not declaration['visible_ui_evidence'].strip():
        raise ValueError('Visible UI evidence or uncertainty explanation required')
    box = declaration['page_bbox']
    if box is None:
        if not declaration['uncertain']:
            raise ValueError('Null bbox requires uncertainty')
        return dict(status='unresolved', quad=None, reason=declaration['visible_ui_evidence'], scores=[])
    if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box):
        raise ValueError('Normalized page bbox outside image; no rescaling or clamping')
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError('Invalid bbox order')
    if declaration['uncertain']:
        return dict(status='unresolved', quad=None, reason=declaration['visible_ui_evidence'], scores=[])
    scores = []
    for row in proposals['candidates']:
        q = row['quad']
        b = [min(p[0] for p in q)/width, min(p[1] for p in q)/height,
             max(p[0] for p in q)/width, max(p[1] for p in q)/height]
        intersection = max(0, min(box[2], b[2])-max(box[0], b[0])) * max(0, min(box[3], b[3])-max(box[1], b[1]))
        union = (box[2]-box[0])*(box[3]-box[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
        scores.append(dict(candidate_id=row['id'], bbox_iou=intersection/union))
    scores.sort(key=lambda r: -r['bbox_iou'])
    thresholds = dict(min_bbox_iou=.85, min_winner_margin=.02)
    if not scores or scores[0]['bbox_iou'] < .85 or (len(scores)>1 and scores[0]['bbox_iou']-scores[1]['bbox_iou'] < .02):
        return dict(status='unresolved', quad=None, reason='No sufficiently close unambiguous existing candidate', scores=scores, thresholds=thresholds)
    chosen = next(r for r in proposals['candidates'] if r['id'] == scores[0]['candidate_id'])
    return dict(chosen, status='candidate_requires_visual_review', scores=scores, thresholds=thresholds,
                matching_limits='bbox IoU is a matching score, not ground-truth localization accuracy')
