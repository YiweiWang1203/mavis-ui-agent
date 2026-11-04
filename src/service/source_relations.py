"""Extract spoken relations and optionally link their names to observed object IDs."""
from collections import Counter
import json
from typing import Literal

from pydantic import Field

from src.agents.region_review import request_region_review
from src.schemas.region_plan import Contract
from src.service.main_model_runtime import MODEL
from src.utils.pipeline_trace import traced_stage
from src.utils.region_audit_input import observation_content


class SourceRelation(Contract):
    source_id: str
    source_quote: str = Field(min_length=1)
    subject: str | None
    reference: str | None
    frame: str | None
    relation: str | None
    certainty: Literal["explicit", "inferred", "unknown"]


class SourceRelations(Contract):
    relations: list[SourceRelation]


class RelationLink(Contract):
    relation_index: int = Field(ge=0)
    subject_id: str | None
    reference_id: str | None
    subject_basis: str
    reference_basis: str


class RelationLinks(Contract):
    links: list[RelationLink]


@traced_stage("source_relations.extract")
def extract_relations(numbered, vision):
    payload = {"asr_segments": numbered, "object_evidence": observation_content(vision)}
    system = (
        "Extract spoken spatial relations from the numbered ASR. Object evidence helps identify referents "
        "but does not specify the requested geometry. For each relation record the exact source segment ID and "
        "verbatim quote, subject, reference object, local or page reference frame, direction or placement, "
        "and certainty. Prefer the named local reference when supported. Mark genuinely unresolved bindings "
        "unknown and use null for unresolved fields. Do not produce layout instructions, tree nodes, geometry, "
        "or a patch. Return one JSON object matching this schema:\n" + json.dumps(SourceRelations.model_json_schema())
    )
    value = request_region_review(MODEL, "source_relation_extract", system, payload)
    SourceRelations.model_validate(value)
    return value


def object_table(elements):
    for item in elements:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("id"), str) and item["id"]:
            yield {key: item[key] for key in ("id", "type", "text", "description") if key in item}
        if isinstance(item.get("items"), list):
            yield from object_table(item["items"])


@traced_stage("source_relations.bind")
def bind_relations(extraction, numbered, vision):
    objects = list(object_table(vision.get("elements", [])))
    counts = Counter(row["id"] for row in objects)
    unique = [row for row in objects if counts[row["id"]] == 1]
    system = (
        "Link each supplied immutable relation to observed object IDs. Use its zero-based relation_index. "
        "Return one link per relation, with evidence for each subject and reference choice. Use null for an "
        "absent or ambiguous ID, even when the direction is clear. Never invent objects or relations, "
        "change a direction, or produce regions, axes, placements, or patches. Return one JSON object "
        "matching this schema:\n" + json.dumps(RelationLinks.model_json_schema())
    )
    raw = request_region_review(MODEL, "source_relation_bind", system, {
        "relation_records": extraction, "asr_segments": numbered, "observed_objects": unique,
    })
    links = RelationLinks.model_validate(raw).links
    relations = extraction["relations"]
    if sorted(link.relation_index for link in links) != list(range(len(relations))):
        raise ValueError("SOURCE_RELATION_LINK_INDEX_COVERAGE")
    accepted, rejected = [], []
    for link in sorted(links, key=lambda row: row.relation_index):
        relation = relations[link.relation_index]
        source_ok = relation["source_quote"] in numbered.get(relation["source_id"], "")
        row = {"relation_index": link.relation_index}
        for role in ("subject", "reference"):
            key = role + "_id"
            value = getattr(link, key)
            if value is not None and (counts[value] != 1 or not source_ok):
                rejected.append({"relation_index": link.relation_index, "field": key, "value": value,
                                 "reason": "UNVERIFIED_SOURCE_QUOTE" if not source_ok else "NON_UNIQUE_OR_MISSING_ID"})
                value = None
            row[key] = value
        accepted.append(row)
    return {"id_links": accepted, "raw_links": raw, "rejected_links": rejected}
