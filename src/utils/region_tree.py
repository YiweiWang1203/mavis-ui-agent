"""Validate the production region tree and derive source evidence."""
import re
from html.parser import HTMLParser

from src.utils.pipeline_trace import trace_event


def speech_segments(speech):
    segments = {}
    for match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", speech):
        value = match.group().strip()
        if value:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            segments[f"s{len(segments) + 1}"] = {
                "text": value, "start": start, "end": start + len(value),
            }
    return segments


def compile_region_tree(plan, segments):
    def require(condition, path):
        if not condition:
            raise ValueError(f"REGION_CONTRACT_INVALID: {path}")

    require(isinstance(plan, dict), "plan")
    meta = plan.get("page_meta")
    viewport = meta.get("viewport") if isinstance(meta, dict) else None
    require(isinstance(viewport, dict) and all(
        type(viewport.get(key)) is int and viewport[key] > 0
        for key in ("width", "height")
    ), "page_meta.viewport")
    elements = plan.get("elements")
    require(isinstance(elements, list) and elements, "elements")
    inventory = {}
    for index, element in enumerate(elements):
        path = f"elements[{index}]"
        require(isinstance(element, dict), path)
        key = element.get("id")
        require(isinstance(key, str) and key and key != "page" and key not in inventory, path + ".id")
        require(isinstance(element.get("type"), str) and element["type"].strip(), path + ".type")
        origin = element.get("origin")
        require(origin in ("speech", "vision", "both", "request"), path + ".origin")
        inventory[key] = {field: element[field] for field in (
            "id", "type", "text", "rpa_action", "origin", "placeholder", "input_type"
        ) if field in element}

    seen = set()

    def visit(node, path, allow_bottom=False):
        require(isinstance(node, dict), path)
        key = node.get("id")
        require(isinstance(key, str) and key and key not in seen, path + ".id")
        seen.add(key)
        slot = node.get("slot")
        require(slot is None or (slot == "bottom" and allow_bottom), path + ".slot")
        result = {"id": key}
        if slot is not None:
            result["slot"] = slot
        if key in inventory:
            require(set(node) <= {"id", "slot"}, path + ".leaf")
            return result
        axis = node.get("axis")
        children = node.get("children")
        require(axis in ("row", "column") and isinstance(children, list) and children, path + ".region")
        result.update(axis=axis, children=[
            visit(child, f"{path}.children[{index}]", axis == "column" and index == len(children) - 1)
            for index, child in enumerate(children)
        ])
        return result

    tree = visit(plan.get("region_tree"), "region_tree")
    require(tree["id"] == "page" and "children" in tree, "region_tree.root")
    require(inventory.keys() <= seen, f"missing element IDs: {sorted(inventory.keys() - seen)}")
    requirements = plan.get("requirements")
    require(isinstance(requirements, list), "requirements")
    compiled = []
    for index, row in enumerate(requirements):
        path = f"requirements[{index}]"
        require(isinstance(row, dict), path)
        sources, intent, status, targets = (row.get(key) for key in ("sources", "intent", "status", "targets"))
        require(isinstance(sources, list) and sources and all(
            isinstance(key, str) and key in segments for key in sources
        ), path + ".sources")
        require(isinstance(intent, str) and intent.strip(), path + ".intent")
        certainty = row.get("certainty")
        require(certainty in ("explicit", "inferred", "conflicting"), path + ".certainty")
        scope = row.get("scope")
        require(scope is None or isinstance(scope, str) and scope in seen - inventory.keys(), path + ".scope")
        references = row.get("references")
        require(isinstance(references, list) and all(
            isinstance(key, str) and key in seen for key in references
        ), path + ".references")
        require(isinstance(targets, list) and all(isinstance(key, str) and key in seen for key in targets)
                and ((status == "bound" and targets) or (status == "unknown" and not targets)), path + ".binding")
        compiled.append({"id": f"req{index + 1}", "intent": intent, "status": status,
                         "certainty": certainty, "scope": scope, "references": list(dict.fromkeys(references)),
                         "evidence": [{"id": key, **segments[key]} for key in dict.fromkeys(sources)],
                         "targets": list(dict.fromkeys(targets))})
    return {"page_meta": {"viewport": viewport, "structure_mode": "region_tree_v1"},
            "region_tree": tree, "elements": list(inventory.values()), "requirements": compiled}


def check_region_markup(code, tree):
    """Check ID, nesting and order markers in the HTML before saving."""
    expected = []

    def visit(node, parent=None):
        expected.append((node["id"], parent, node.get("axis"), node.get("slot")))
        for child in node.get("children", []):
            visit(child, node["id"])

    visit(tree)

    class Markup(HTMLParser):
        void_tags = set("area base br col embed hr img input link meta param source track wbr".split())

        def __init__(self):
            super().__init__()
            self.stack = []
            self.nodes = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            key = attrs.get("data-ui-id")
            if key is not None:
                parent = next((key for _, key in reversed(self.stack) if key is not None), None)
                self.nodes.append((key, parent, attrs.get("data-ui-axis"), attrs.get("data-ui-slot")))
            if tag not in self.void_tags:
                self.stack.append((tag, key))

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in self.void_tags:
                self.handle_endtag(tag)

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    parser = Markup()
    parser.feed(code)
    parser.close()
    matches = parser.nodes == expected
    trace_event("coder.region_markup", matches=matches, expected=expected, actual=parser.nodes)
    if not matches:
        raise ValueError("HTML_REGION_TREE_MISMATCH")
