"""Build a coordinate-free observation view for the planner request."""
import math


def _list(value):
    return value if isinstance(value, list) else []


def relative_vision_observations(vision):
    elements = vision.get("elements", [])
    ids = set()
    for element in elements:
        element_id = element.get("id") if isinstance(element, dict) else None
        if not isinstance(element_id, str) or not element_id.strip():
            raise ValueError("Planner observation requires a nonempty object ID")
        if element_id in ids:
            raise ValueError("Duplicate object ID in planner observation: " + element_id)
        ids.add(element_id)
    objects = []
    boxes = {}
    for element in elements:
        element_id = element["id"]
        row = {key: element[key] for key in ("id", "type", "text", "description", "visible", "source", "confidence")
               if key in element}
        parent = element.get("parent_id")
        row["observed_parent_id"] = parent if isinstance(parent, str) and parent in ids and parent != element_id else None
        row["observed_children_ids"] = [child for child in _list(element.get("children_ids"))
                                        if isinstance(child, str) and child in ids and child != element_id]
        objects.append(row)
        raw = element.get("bbox")
        if not isinstance(raw, dict):
            continue
        box = tuple(raw.get(key) for key in ("x_min", "y_min", "x_max", "y_max"))
        if (all(type(v) in (int, float) and math.isfinite(v) for v in box)
                and box[0] < box[2] and box[1] < box[3]):
            boxes[element_id] = box

    relations = []
    for source, (x1, y1, x2, y2) in boxes.items():
        nearest = {}
        containers = []
        for target, (a1, b1, a2, b2) in boxes.items():
            if source == target:
                continue
            if a1 <= x1 and b1 <= y1 and a2 >= x2 and b2 >= y2 and (a1,b1,a2,b2) != (x1,y1,x2,y2):
                containers.append(((a2-a1)*(b2-b1), target))
            if min(y2, b2) > max(y1, b1) and x2 <= a1:
                nearest.setdefault("left_of", []).append((a1-x2, target))
            if min(x2, a2) > max(x1, a1) and y2 <= b1:
                nearest.setdefault("above", []).append((b1-y2, target))
        if containers:
            nearest["geometrically_inside"] = containers
        for relation, candidates in nearest.items():
            ranked = sorted(candidates)
            if len(ranked) == 1 or not math.isclose(ranked[0][0], ranked[1][0], abs_tol=1e-9):
                relations.append({"object_id": source, "relation": relation, "other_id": ranked[0][1]})
    return {
        "elements": objects,
        "observed_reading_order": [item for item in _list(vision.get("reading_order")) if isinstance(item, str) and item in ids],
        "spatial_observations": relations,
        "interpretation": "Geometry relations describe only the source observation. Geometric containment does not establish a parent. Missing or ambiguous relations are unknown. Use the target viewport in User Intent to plan placement."
    }

