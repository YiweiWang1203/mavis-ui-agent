"""One multimodal production request over the video recognizer's selected frame."""
import base64
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image

from src.service.main_model_runtime import MODEL, main_client
from src.utils.pipeline_trace import trace_event


PROMPT = (
    "Create the requested runnable UI using the attached sketch, original request and full video transcript. "
    "Treat the spoken instructions as guidance for interpreting and correcting the sketch. "
    "Return one complete self-contained HTML document with a doctype, head and body, and explicit closing tags. "
    "Use inline CSS and JavaScript, with working native controls and the requested observable interactions. "
    "Use the intended viewport and language. Keep styling compact and use simple CSS or compact inline SVG "
    "for visual assets. Do not rely on external resources, packages, services or large encoded assets. "
    "Return only the HTML document."
)


class DocumentBoundary(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events = []

    def handle_starttag(self, tag, attrs):
        if tag in {"html", "head", "body"}:
            self.events.append(tag)

    def handle_endtag(self, tag):
        if tag in {"html", "head", "body"}:
            self.events.append("/" + tag)

    def handle_startendtag(self, tag, attrs):
        if tag in {"html", "head", "body"}:
            self.events.append(tag + "/")


def require_complete_html(html):
    if not re.match(r"\s*<!doctype\s+html\s*>\s*<html(?:\s|>)", html, re.I) or not re.search(
            r"</html\s*>\s*\Z", html, re.I):
        raise ValueError("DIRECT_BASELINE_INCOMPLETE_DOCUMENT")
    boundary = DocumentBoundary()
    boundary.feed(html)
    boundary.close()
    if boundary.events != ["html", "head", "/head", "body", "/body", "/html"]:
        raise ValueError("DIRECT_BASELINE_INCOMPLETE_DOCUMENT")


def run_direct_baseline(prepared, output):
    state = prepared["state"]
    image = Path(state["image_path"]).resolve()
    recognition = Path(prepared["recognition_image_path"]).resolve()
    if (prepared["selected_source"] != "video_preprocessed_sketch" or image != recognition
            or prepared["vision_image_mode"] != "recognition"):
        raise ValueError("DIRECT_BASELINE_REQUIRES_VIDEO_RECOGNITION_FRAME")
    transcript = state["asr_transcript"]
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("DIRECT_BASELINE_REQUIRES_CURRENT_ASR")
    image_bytes = image.read_bytes()
    with Image.open(BytesIO(image_bytes)) as selected:
        mime = Image.MIME.get(selected.format)
        width, height = selected.size
        selected.verify()
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("DIRECT_BASELINE_UNSUPPORTED_IMAGE")
    source = {
        "path": str(image), "source": prepared["selected_source"], "mime": mime,
        "sha256": hashlib.sha256(image_bytes).hexdigest(), "width": width, "height": height,
        "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
    }
    trace_event("direct_multimodal_baseline.input", **source)
    hint = state["preprocess_platform_hint"] or {}
    text = json.dumps({
        "original_user_request": state["original_user_request"],
        "asr_transcript": transcript,
        "target_viewport_hint": hint.get("target_size"),
        "preferred_locale": state["preferred_locale"],
    }, ensure_ascii=False)
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    client = main_client("direct_coder")
    if client is None:
        raise RuntimeError("DIRECT_BASELINE_REQUIRES_BOUNDED_RUNTIME")
    response = client.chat.completions.create(
        model=MODEL, temperature=0.2,
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": [
            {"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    )
    html = response.choices[0].message.content
    require_complete_html(html)
    artifact = output / "final.html"
    payload = html.encode("utf-8")
    with artifact.open("xb") as stream:
        stream.write(payload)
    digest = hashlib.sha256(payload).hexdigest()
    trace_event("direct_multimodal_baseline.html", path=str(artifact), sha256=digest)
    return {
        "status": "HTML_GENERATED_PENDING_BROWSER_ACCEPTANCE", "html_generated": True,
        "html_contract_passed": True, "html_contract_scope": "document_boundary",
        "html_path": str(artifact), "html_sha256": digest, "input_frame": source,
        "renderer": "direct_multimodal_baseline_v1",
    }
