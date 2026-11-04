"""Content-only observation view and executable-plan evidence pointers."""
import re


CONTENT_FIELDS = {
    "id", "type", "text", "label", "description", "items", "elements",
    "source", "confidence", "visible", "items_source", "parent_id",
}


def observation_content(value):
    if isinstance(value, list):
        return [observation_content(item) for item in value]
    if isinstance(value, dict):
        return {key: observation_content(item) for key, item in value.items()
                if key in CONTENT_FIELDS}
    return value


def audit_plan_view(plan):
    if isinstance(plan, list):
        return [audit_plan_view(item) for item in plan]
    if isinstance(plan, dict):
        geometry = {"bbox", "pixel_bbox", "spatial_info", "canvas", "coordinate_mapping",
                    "x_min", "x_max", "y_min", "y_max"}
        return {key: audit_plan_view(value) for key, value in plan.items() if key not in geometry}
    return plan


def resolve_pointer(document, pointer):
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("REVIEW_INVALID_PLAN_POINTER")
    value = document
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("REVIEW_INVALID_PLAN_POINTER")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token) or int(token) >= len(value):
                raise ValueError("REVIEW_PLAN_POINTER_NOT_FOUND")
            value = value[int(token)]
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise ValueError("REVIEW_PLAN_POINTER_NOT_FOUND")
    return value
