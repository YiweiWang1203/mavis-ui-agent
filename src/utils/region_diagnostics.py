"""Independent dynamic constraints, reported without rewriting a plan."""
from src.schemas.region_plan import RegionPlan


def region_diagnostics(plan, segments):
    try:
        normalized = RegionPlan.model_validate(plan).model_dump(exclude_none=True)
    except ValueError as error:
        return [{"path": "", "actual": plan, "expected": str(error)}]
    issues = []

    def report(path, actual, expected):
        issues.append({"path": path, "actual": actual, "expected": expected})

    inventory = [element["id"] for element in normalized["elements"]]
    ids = set(inventory)
    seen = set()
    regions = set()

    def visit(node, path, parent_axis=None, last=False):
        key = node["id"]
        if key in seen:
            report(path + "/id", key, "Globally unique tree ID")
        seen.add(key)
        if node.get("slot") == "bottom" and not (parent_axis == "column" and last):
            report(path + "/slot", "bottom", "Only the final child of a column may use bottom")
        children = node.get("children")
        if children is not None:
            regions.add(key)
            if key in ids:
                report(path + "/id", key, "Region ID distinct from inventory leaf IDs")
            for index, child in enumerate(children):
                visit(child, f"{path}/children/{index}", node["axis"], index == len(children) - 1)
        elif key not in ids:
            report(path + "/id", key, "Leaf ID must exist in elements")

    visit(normalized["region_tree"], "/region_tree")
    if normalized["region_tree"]["id"] != "page":
        report("/region_tree/id", normalized["region_tree"]["id"], "Root ID must be page")
    if len(ids) != len(inventory) or "page" in ids:
        report("/elements", inventory, "Unique inventory IDs, excluding reserved page")
    for missing in sorted(ids - seen):
        report("/region_tree", missing, "Inventory object must occur once in the tree")
    for index, requirement in enumerate(normalized["requirements"]):
        path = f"/requirements/{index}"
        if not set(requirement["sources"]) <= segments.keys():
            report(path + "/sources", requirement["sources"], "Existing ASR segment IDs")
        if requirement.get("scope") is not None and requirement["scope"] not in regions:
            report(path + "/scope", requirement["scope"], "Existing region ID or null")
        targets = requirement["targets"]
        if not set(targets) <= seen or (requirement["status"] == "bound") != bool(targets):
            report(path + "/targets", targets, "Bound needs existing tree targets; unknown needs []")
        if not set(requirement["references"]) <= seen:
            report(path + "/references", requirement["references"], "Existing tree IDs")
    for index, action in enumerate(normalized["actions"]):
        if action["target"] not in ids:
            report(f"/actions/{index}/target", action["target"], "Top-level inventory ID; for repeated rows target their list control")
        if not set(action["sources"]) <= segments.keys():
            report(f"/actions/{index}/sources", action["sources"], "Existing ASR segment IDs")
    return issues
