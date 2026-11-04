"""Lower the model's local layout decisions into the production region tree."""
from graphlib import CycleError, TopologicalSorter
from typing import Literal

from pydantic import Field

from src.schemas.region_plan import Action, Contract, Element, PageMeta, Requirement
from src.utils.region_tree import compile_region_tree


class Frame(Contract):
    id: str
    flow: Literal["horizontal", "vertical"]


class Relation(Contract):
    id: str
    source_id: str
    quote: str | None = None
    subject: str
    frame: str
    reference: str | None = None
    kind: Literal[
        "inside", "same_group", "left_of", "right_of", "above", "below",
        "at_left", "at_right", "at_top", "at_bottom", "bottom_left", "bottom_right",
        "center_across", "fill_along",
    ]


class SemanticLayout(Contract):
    page_meta: PageMeta
    elements: list[Element] = Field(min_length=1)
    content_requirements: list[Requirement]
    actions: list[Action]
    frames: list[Frame] = Field(min_length=1)
    relations: list[Relation]


class MemberFrame(Frame):
    parent: str | None
    membership_source_id: str = "inferred"


class MemberElement(Element):
    parent: str
    membership_source_id: str = "inferred"


class LocalRelation(Relation):
    kind: Literal[
        "same_group", "left_of", "right_of", "above", "below",
        "at_left", "at_right", "at_top", "at_bottom", "bottom_left", "bottom_right",
        "center_across", "fill_along",
    ]


class SemanticMembershipLayout(Contract):
    page_meta: PageMeta
    elements: list[MemberElement] = Field(min_length=1)
    content_requirements: list[Requirement]
    actions: list[Action]
    frames: list[MemberFrame] = Field(min_length=1)
    relations: list[LocalRelation]


DIRECTIONS = {
    "left_of": ("horizontal", False), "right_of": ("horizontal", True),
    "above": ("vertical", False), "below": ("vertical", True),
}
EDGES = {
    "at_left": (("horizontal", "start"),), "at_right": (("horizontal", "end"),),
    "at_top": (("vertical", "start"),), "at_bottom": (("vertical", "end"),),
    "bottom_left": (("horizontal", "start"), ("vertical", "end")),
    "bottom_right": (("horizontal", "end"), ("vertical", "end")),
}


def compile_semantic_membership(raw, segments, request):
    plan = SemanticMembershipLayout.model_validate(raw)
    nodes = [*plan.frames, *plan.elements]
    if any((node.parent is None) != (node.id == "page") for node in nodes):
        raise ValueError("SEMANTIC_MEMBERSHIP_INVALID_ROOT_PARENT")
    if any(row.id.startswith("membership:") for row in plan.relations):
        raise ValueError("SEMANTIC_MEMBERSHIP_RESERVED_RELATION_ID")
    # Lower explicit node parents to the shared compiler's internal edge representation.
    lowered = plan.model_dump()
    for field in ("frames", "elements"):
        for node in lowered[field]:
            del node["parent"], node["membership_source_id"]
    lowered["relations"] = [
        {"id": f"membership:{node.id}", "source_id": node.membership_source_id,
         "subject": node.id, "frame": node.parent, "kind": "inside"}
        for node in nodes if node.parent is not None
    ] + lowered["relations"]
    return compile_semantic_layout(lowered, segments, request, derive_source_evidence=True)


def compile_semantic_layout(raw, segments, request, *, derive_source_evidence=False):
    plan = SemanticLayout.model_validate(raw)
    frames = {frame.id: frame.flow for frame in plan.frames}
    elements = {element.id for element in plan.elements}
    nodes = frames.keys() | elements

    def require(valid, reason, key=""):
        if not valid:
            raise ValueError(f"SINGLE_SEMANTIC_LAYOUT_{reason}: {key}")

    require("page" in frames and len(frames) == len(plan.frames) and not frames.keys() & elements
            and len(elements) == len(plan.elements) and "" not in nodes, "IDENTITY")
    members = {key: set() for key in frames}
    parents = {}
    relation_ids = set()
    evidence = {}
    for row in plan.relations:
        require(row.id and row.id not in relation_ids, "RELATION_ID", row.id)
        relation_ids.add(row.id)
        require(row.subject in nodes - {"page"} and row.frame in frames, "SUBJECT_OR_FRAME", row.id)
        source = request if row.source_id == "request" else segments.get(row.source_id, {}).get("text")
        if row.source_id in {"vision", "inferred"}:
            require(row.quote is None, "SOURCE_QUOTE", row.id)
        elif derive_source_evidence:
            require(source is not None and (row.quote is None or
                    (row.quote.strip() and row.quote in source)), "SOURCE_QUOTE", row.id)
            evidence[row.id] = (
                {"text": request, "start": 0, "end": len(request)}
                if row.source_id == "request" else dict(segments[row.source_id])
            )
        else:
            require(source is not None and row.quote and row.quote.strip() and row.quote in source,
                    "SOURCE_QUOTE", row.id)
        if row.kind == "inside":
            require(row.reference is None and row.subject not in parents, "PARENT", row.id)
            parents[row.subject] = row.frame
            members[row.frame].add(row.subject)
    require(parents.keys() == nodes - {"page"} and all(members.values()), "COVERAGE")

    for key in frames:
        seen = set()
        ancestor = key
        while ancestor != "page":
            require(ancestor not in seen, "PARENT_CYCLE", key)
            seen.add(ancestor)
            ancestor = parents[ancestor]

    orders = {key: {child: set() for child in children} for key, children in members.items()}
    placements = {key: {} for key in nodes}
    trace_fields = {}

    def placement(row, field, value):
        subject_fields = placements[row.subject]
        require(subject_fields.get(field, value) == value, "PLACEMENT_CONFLICT", row.id)
        subject_fields[field] = value
        trace_fields[row.id].append((row.subject, field))

    for row in plan.relations:
        children = members[row.frame]
        flow = frames[row.frame]
        predecessors = orders[row.frame]
        require(row.subject in children, "FRAME_MEMBERSHIP", row.id)
        pair = row.kind in DIRECTIONS or row.kind == "same_group"
        if pair:
            require(row.reference in children and row.reference != row.subject, "REFERENCE", row.id)
        else:
            require(row.reference is None, "REFERENCE", row.id)
        trace_fields[row.id] = [(row.subject, ""), (row.frame, "/children")]
        if pair:
            trace_fields[row.id].append((row.reference, ""))
        if row.kind in DIRECTIONS:
            axis, reverse = DIRECTIONS[row.kind]
            require(flow == axis, "DIRECTION_AXIS", row.id)
            before, after = (row.reference, row.subject) if reverse else (row.subject, row.reference)
            predecessors[after].add(before)
        for axis, end in EDGES.get(row.kind, ()):
            if axis != flow:
                placement(row, "/cross_align", end)
            elif end == "start":
                for other in children - {row.subject}:
                    predecessors[other].add(row.subject)
            else:
                predecessors[row.subject].update(children - {row.subject})
                if flow == "vertical":
                    placement(row, "/slot", "bottom")
        if row.kind == "center_across":
            placement(row, "/cross_align", "center")
        if row.kind == "fill_along":
            placement(row, "/grow", True)

    paths = {}

    def build(key, path):
        paths[key] = path
        node = {"id": key, **{field[1:]: value for field, value in placements[key].items()}}
        if key in frames:
            # Choose the smallest currently available ID. Input array order carries no meaning.
            sorter = TopologicalSorter(orders[key])
            try:
                sorter.prepare()
            except CycleError as error:
                raise ValueError(f"SINGLE_SEMANTIC_LAYOUT_ORDER_CONFLICT: {key}") from error
            ready = set(sorter.get_ready())
            children = []
            while ready:
                child = min(ready)
                ready.remove(child)
                children.append(build(child, f"{path}/children/{len(children)}"))
                sorter.done(child)
                ready.update(sorter.get_ready())
            node.update(axis="row" if frames[key] == "horizontal" else "column", children=children)
        return node

    tree = build("page", "/region_tree")
    requirements = [row.model_dump() for row in plan.content_requirements]
    for row in plan.relations:
        if row.source_id in segments:
            requirements.append({
                "sources": [row.source_id], "intent": row.quote or evidence[row.id]["text"], "certainty": "explicit",
                "status": "bound", "scope": row.frame, "targets": [row.subject],
                "references": [row.reference] if row.reference is not None else [],
            })
    execution = compile_region_tree({
        "page_meta": plan.page_meta.model_dump(), "elements": [item.model_dump() for item in plan.elements],
        "requirements": requirements, "actions": [action.model_dump() for action in plan.actions],
        "region_tree": tree,
    }, segments, schema_version=2)
    provenance = {
        "frames": {key: {"flow": flow, "axis_path": paths[key] + "/axis"} for key, flow in frames.items()},
        "relations": [{**row.model_dump(),
                       **({"source_evidence": evidence.get(row.id)} if derive_source_evidence else {}),
                       "compiled_paths": [
            paths[node] + field for node, field in trace_fields[row.id]
        ]} for row in plan.relations],
    }
    return execution, provenance
