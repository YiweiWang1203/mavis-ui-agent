"""Extract spoken relations and optionally link their names to observed object IDs."""
from collections import Counter
import hashlib
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
    relation_key: str
    subject: str | None
    reference: str | None
    frame: str | None
    relation: str | None
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


IDENTITY_FIELDS = ("subject", "reference", "frame", "relation")


def keyed_relations(extraction):
    occurrences = Counter()
    result = {}
    for record in extraction["relations"]:
        content = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        occurrences[digest] += 1
        result[f"rel-{digest}-{occurrences[digest]}"] = record
    return result


def validate_relation_links(raw, relations, numbered, object_counts):
    links = RelationLinks.model_validate(raw).links
    key_counts = Counter(link.relation_key for link in links)
    unique_links = {link.relation_key: link for link in links if key_counts[link.relation_key] == 1}
    rejected = [{"relation_key": key, "reason": "UNKNOWN_RELATION_KEY", "rows": count}
                for key, count in key_counts.items() if key not in relations]
    accepted, identity_verified = [], 0
    for key, record in relations.items():
        identity = {field: record[field] for field in IDENTITY_FIELDS}
        link = unique_links.get(key)
        row = {"relation_key": key, "source_id": record["source_id"], **identity,
               "subject_id": None, "reference_id": None}
        accepted.append(row)
        if link is None:
            rejected.append({"relation_key": key, "reason": "DUPLICATE_RELATION_KEY" if key in key_counts
                             else "MISSING_LINK"})
            continue
        if any(getattr(link, field) != value for field, value in identity.items()):
            rejected.append({"relation_key": key, "reason": "RELATION_IDENTITY_MISMATCH"})
            continue
        identity_verified += 1
        if record["source_quote"] not in numbered.get(record["source_id"], ""):
            rejected.append({"relation_key": key, "reason": "UNVERIFIED_SOURCE_QUOTE"})
            continue
        for field in ("subject_id", "reference_id"):
            value = getattr(link, field)
            if value is not None and object_counts.get(value, 0) != 1:
                rejected.append({"relation_key": key, "field": field, "value": value,
                                 "reason": "NON_UNIQUE_OR_MISSING_ID"})
            else:
                row[field] = value
    bound = sum(row["subject_id"] is not None and row["reference_id"] is not None for row in accepted)
    return {"id_links": accepted, "raw_links": raw, "rejected_links": rejected,
            "counts": {"expected": len(relations), "returned_rows": len(links),
                       "covered_keys": len(relations.keys() & key_counts.keys()),
                       "identity_verified": identity_verified, "structurally_bound": bound,
                       "unknown": len(relations) - bound}}


@traced_stage("source_relations.bind")
def bind_relations(extraction, numbered, vision):
    objects = list(object_table(vision.get("elements", [])))
    counts = Counter(row["id"] for row in objects)
    unique = [row for row in objects if counts[row["id"]] == 1]
    relations = keyed_relations(extraction)
    system = (
        "Link each supplied immutable relation to observed object IDs. Copy the exact relation_key and echo "
        "the original subject, reference, frame and relation exactly, including nulls. "
        "Return one link per key, with evidence for each subject and reference choice. Use null for an "
        "absent or ambiguous ID, even when the direction is clear. Never invent objects or relations, "
        "change a direction, or produce regions, axes, placements, or patches. Return one JSON object "
        "matching this schema:\n" + json.dumps(RelationLinks.model_json_schema())
    )
    raw = request_region_review(MODEL, "source_relation_bind", system, {
        "relation_records_by_key": relations, "asr_segments": numbered, "observed_objects": unique,
    })
    return {"keyed_relations": relations, **validate_relation_links(raw, relations, numbered, counts)}
