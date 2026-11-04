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


def run_native_html_autoreview(frozen_request, initial_html, screenshot):
    original_text, original_image = frozen_request["messages"][1]["content"]
    if (original_text["type"], original_image["type"]) != ("text", "image_url"):
        raise ValueError("NATIVE_AUTOREVIEW_MULTIMODAL_INPUT")
    source = json.loads(original_text["text"])
    required = ("original_user_request", "asr_transcript", "target_viewport_hint", "preferred_locale")
    evidence = {key: source[key] for key in required}
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
        messages=[{"role": "system", "content": REVIEW_PROMPT}, {"role": "user", "content": [
            {"type": "text", "text": json.dumps({**evidence, "initial_html": initial_html}, ensure_ascii=False)},
            original_image,
            {"type": "image_url", "image_url": {"url": screenshot_data}},
        ]}],
    ).choices[0]
    review = NativeReview.model_validate(parse_semantic_json(choice.message.content))
    for issue in review.issues:
        quote = issue.source_quote
        if quote is not None and (not quote.strip() or not any(
                quote in evidence[key] for key in ("asr_transcript", "original_user_request"))):
            raise ValueError("NATIVE_AUTOREVIEW_SOURCE_QUOTE")
    return review.model_dump()
