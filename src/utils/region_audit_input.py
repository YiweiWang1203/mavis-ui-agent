"""Content-only observation view and executable-plan evidence pointers."""
import re


def observation_content(value):
    if isinstance(value, list):
        return [observation_content(item) for item in value]
    if isinstance(value, dict):
        return {key: observation_content(item) for key, item in value.items()
                if not is_geometry_metadata(key, item)}
    return value


def is_geometry_metadata(key, value):
    if key in {"bbox", "pixel_bbox"}:
        return ((isinstance(value, list) and len(value) == 4
                 and all(isinstance(number, (int, float)) for number in value))
                or (isinstance(value, dict) and
                    ({"x_min", "y_min", "x_max", "y_max"} <= value.keys()
                     or {"x", "y", "width", "height"} <= value.keys())))
    if key == "canvas":
        return isinstance(value, dict) and {"width", "height"} <= value.keys()
    if key == "coordinate_mapping":
        return isinstance(value, dict) and "source" in value and (
            "scale" in value or "recognition_size" in value)
    return False


def audit_plan_view(plan):
    return observation_content(plan)


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


def plan_references(plan):
    references = {"plan": {"path": "", "value": plan}}
    if not isinstance(plan, dict):
        return references

    def add(ref, path, value):
        # Duplicate model IDs must not overwrite an earlier evidence binding.
        if ref in references:
            ref += "@" + path
        references[ref] = {"path": path, "value": value}

    def tree(node, path):
        if not isinstance(node, dict):
            return
        add("tree:" + str(node.get("id", path)), path, node)
        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                tree(child, f"{path}/children/{index}")

    tree(plan.get("region_tree"), "/region_tree")
    for field in ("elements", "requirements", "actions"):
        values = plan.get(field)
        if isinstance(values, list):
            add(field, "/" + field, values)
            for index, value in enumerate(values):
                label = value.get("id", str(index + 1)) if isinstance(value, dict) else str(index + 1)
                add(f"{field}:{label}", f"/{field}/{index}", value)
    return references
