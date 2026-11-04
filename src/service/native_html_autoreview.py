"""Review an initial native HTML page without changing it."""
import base64
import hashlib
from io import BytesIO
import json
from typing import Annotated, Literal

from PIL import Image
from pydantic import Field

from src.schemas.region_plan import Contract
from src.service.main_model_runtime import MODEL, main_client
from src.utils.pipeline_trace import trace_event
from src.utils.region_tree import speech_segments
from src.utils.semantic_page_plan import parse_semantic_json


ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class ReviewIssue(Contract):
    source_quote: ShortText | None
    target_locator: ShortText
    observation: ShortText
    discrepancy: ShortText
    expected: ShortText
    confidence: Literal["high", "medium", "low"]


class NativeReview(Contract):
    issues: list[ReviewIssue] = Field(max_length=8)
    preserve: list[ShortText] = Field(max_length=8)
    uncertainty: list[ShortText] = Field(max_length=6)


Aspect = Literal["layout", "content", "behavior", "visual"]
EvidenceType = Literal["static_dom", "screenshot_visible", "not_tested"]


class SourceRequirement(Contract):
    source_segment_id: ShortText | None
    exact_quote: ShortText | None = None
    subject: ShortText
    relation: ShortText
    reference: ShortText | None
    scope: ShortText | None
    uncertainty: ShortText | None


class ObservedRelation(Contract):
    subject_locator: ShortText
    reference_locator: ShortText | None
    scope_locator: ShortText | None
    observed_relation: ShortText
    evidence_type: EvidenceType
    evidence: ShortText


class RelationFinding(Contract):
    source_requirement: SourceRequirement
    observed: ObservedRelation
    aspect: Aspect
    verdict: Literal["discrepancy", "unsupported", "uncertain"]
    explanation: ShortText


class PreserveEvidence(Contract):
    target_locator: ShortText
    aspect: Aspect
    evidence_type: EvidenceType
    evidence: ShortText


class NativeRelationAudit(Contract):
    issues: list[RelationFinding] = Field(max_length=8)
    preserve: list[PreserveEvidence] = Field(max_length=8)
    uncertainty: list[ShortText] = Field(max_length=6)


REVIEW_PROMPT = (
    "Audit the supplied initial web page against the original request, spoken transcript and video sketch. "
    "The first image is the video sketch. The second image is the initial browser rendering. "
    "Use initial_html to identify the affected element by CSS selector or distinctive existing text. "
    "Report only supported discrepancies, with observed evidence and expected result. Cite a literal excerpt "
    "from the transcript or original request when it supports the issue, otherwise use null and explain uncertainty. "
    "Distinguish observable initial state from interaction behavior inferred from source. State which visibly "
    "correct parts should be preserved. An empty issues list is valid. Do not write code, a patch, or a repaired page. "
    "Return one JSON object matching this schema.\n" + json.dumps(NativeReview.model_json_schema())
)
RELATION_AUDIT_PROMPT = (
    "Audit the initial page against the original request and transcript. The first image is the source sketch. "
    "The second is the initial browser rendering. For each candidate, select a numbered ASR source_segment_id "
    "or use request for the original user request. Use null when no source supports the candidate. An optional "
    "quote must be literal within the selected source. State the subject, relationship, reference and local scope. "
    "Separately identify the existing "
    "DOM elements using CSS selectors or distinctive text, and describe the actual relationship and its evidence. "
    "Then classify the comparison. Use discrepancy only when the source and observation support it; "
    "use uncertain if the source admits multiple readings, and unsupported if an alleged requirement lacks a source. "
    "The expected relation is the source relation you stated. Do not infer new copy or content. "
    "Static HTML can support a statement about implementation; "
    "neither it nor an initial screenshot proves a click occurred or what happened after it. Do not claim an action "
    "was tested. Provide evidence for each preserved aspect. Never list the same element and aspect as both a "
    "discrepancy and a preserve item. Use at most eight issues, eight preserve items and six uncertainty notes. "
    "Empty lists are allowed. Return only JSON in this schema. Do not output a patch, code, or a revised page.\n"
    + json.dumps(NativeRelationAudit.model_json_schema())
)


def check_relation_audit(review, sources):
    discrepancies = set()
    resolved = []
    for row in review.issues:
        source = row.source_requirement
        evidence = sources.get(source.source_segment_id)
        if source.source_segment_id is not None and evidence is None:
            raise ValueError("NATIVE_RELATION_AUDIT_UNKNOWN_SOURCE")
        if source.exact_quote is not None and (evidence is None or not source.exact_quote.strip()
                                               or source.exact_quote not in evidence["text"]):
            raise ValueError("NATIVE_AUTOREVIEW_SOURCE_QUOTE")
        if (source.uncertainty is not None and row.verdict != "uncertain") or (
                row.verdict == "discrepancy" and (evidence is None or row.observed.evidence_type == "not_tested")):
            raise ValueError("NATIVE_RELATION_AUDIT_INCONSISTENT_SOURCE")
        if row.verdict == "discrepancy":
            discrepancies.add((row.observed.subject_locator.strip(), row.aspect))
        resolved.append(evidence)
    if any((row.target_locator.strip(), row.aspect) in discrepancies for row in review.preserve):
        raise ValueError("NATIVE_RELATION_AUDIT_CONFLICTING_PRESERVE")
    if any(row.evidence_type == "not_tested" for row in review.preserve):
        raise ValueError("NATIVE_RELATION_AUDIT_PRESERVE_WITHOUT_EVIDENCE")
    return resolved


def check_source_quote(quote, evidence):
    if quote is not None and (not quote.strip() or not any(
            quote in evidence[key] for key in ("asr_transcript", "original_user_request"))):
        raise ValueError("NATIVE_AUTOREVIEW_SOURCE_QUOTE")


def run_native_html_autoreview(frozen_request, initial_html, screenshot, *, relation_audit=False):
    original_text, original_image = frozen_request["messages"][1]["content"]
    if (original_text["type"], original_image["type"]) != ("text", "image_url"):
        raise ValueError("NATIVE_AUTOREVIEW_MULTIMODAL_INPUT")
    source = json.loads(original_text["text"])
    required = ("original_user_request", "asr_transcript", "target_viewport_hint", "preferred_locale")
    evidence = {key: source[key] for key in required}
    if relation_audit:
        segments = speech_segments(evidence["asr_transcript"])
        evidence["numbered_asr_segments"] = {key: row["text"] for key, row in segments.items()}
        original = evidence["original_user_request"]
        sources = {**segments, "request": {"text": original, "start": 0, "end": len(original)}}
        trace_event("native_html_relation_audit.sources", asr_sha256=hashlib.sha256(
            evidence["asr_transcript"].encode("utf-8")).hexdigest(), segments=segments)
    with Image.open(BytesIO(screenshot)) as image:
        mime = Image.MIME.get(image.format)
        image.verify()
    if mime not in {"image/png", "image/jpeg"}:
        raise ValueError("NATIVE_AUTOREVIEW_SCREENSHOT_FORMAT")
    screenshot_data = f"data:{mime};base64," + base64.b64encode(screenshot).decode("ascii")
    screenshot_sha = hashlib.sha256(screenshot).hexdigest()
    trace_event("native_html_autoreview.input", screenshot_sha256=screenshot_sha,
                initial_model_html_sha256=hashlib.sha256(initial_html.encode("utf-8")).hexdigest())
    client = main_client("native_html_review")
    if client is None:
        raise RuntimeError("NATIVE_AUTOREVIEW_REQUIRES_BOUNDED_RUNTIME")
    choice = client.chat.completions.create(
        model=MODEL, temperature=0.2, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": RELATION_AUDIT_PROMPT if relation_audit else REVIEW_PROMPT},
                  {"role": "user", "content": [
            {"type": "text", "text": json.dumps({**evidence, "initial_html": initial_html}, ensure_ascii=False)},
            original_image,
            {"type": "image_url", "image_url": {"url": screenshot_data}},
        ]}],
    ).choices[0]
    parsed = parse_semantic_json(choice.message.content)
    if relation_audit:
        review = NativeRelationAudit.model_validate(parsed)
        resolved = check_relation_audit(review, sources)
        return {**review.model_dump(), "resolved_sources": resolved}
    else:
        review = NativeReview.model_validate(parsed)
        for issue in review.issues:
            check_source_quote(issue.source_quote, evidence)
    return review.model_dump()
