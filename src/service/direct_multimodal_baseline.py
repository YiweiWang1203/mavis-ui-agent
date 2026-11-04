"""One multimodal production request over the video recognizer's selected frame."""
import base64
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image

from src.renderers.bounded_svg_uri import decoded_css_escapes, validate_css_svg_urls
from src.renderers.region_bundle import SVG_TAGS, check_asset_text
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
DIRECT_ASSET_POLICY = "direct_icon_catalog_v1"
BOUNDED_CSS_COMPATIBILITY = "direct_bounded_css_svg_compatibility_v1"
ICON_CATALOG = {
    "back": '<path d="m14 6-6 6 6 6"/>',
    "forward": '<path d="m10 6 6 6-6 6"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "location": '<path d="M20 10c0 6-8 11-8 11s-8-5-8-11a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2"/>',
    "search": '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4"/>',
    "add": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "mic": '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0m-7 7v3"/>',
    "send": '<path d="m3 4 18 8-18 8 3-8-3-8Zm3 8h15"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "user": '<circle cx="12" cy="8" r="3"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="9" r="1"/><path d="m3 17 5-4 4 3 4-5 5 5"/>',
}
ASSET_RULES = (
    f"Asset rules ({DIRECT_ASSET_POLICY}) replace the earlier inline SVG option. For a vector icon, use exactly "
    '<span data-ui-icon="NAME"></span> as markup, optionally wrapped in your own styled element. '
    f"Supported NAME values: {', '.join(ICON_CATALOG)}. The program inserts a 1em inline SVG inside the span. "
    "Use plain text or ordinary CSS shapes for other visuals. Do not author SVG, paths, CSS d declarations, "
    "data URLs, base64, or opaque encoded assets in HTML, CSS or JavaScript."
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


class CompactAssets(HTMLParser):
    def __init__(self, html, *, allow_bounded_css_svg=False):
        super().__init__()
        self.html = html
        self.insertions = []
        self.line_starts = [0, *(match.end() for match in re.finditer("\n", html))]
        self.raw_text_tag = None
        self.allow_bounded_css_svg = allow_bounded_css_svg
        self.styles = []

    def source_index(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag in {"svg", "path"}:
            raise ValueError("DIRECT_BASELINE_AUTHORED_VECTOR")
        for name, value in attrs:
            check_asset_text(value, tag)
            if name == "style" and value:
                self.check_css(value)
            if name == "data-ui-icon":
                if value not in ICON_CATALOG:
                    raise ValueError("DIRECT_BASELINE_UNKNOWN_ICON")
                opening = self.get_starttag_text()
                end = self.source_index() + len(opening)
                if (tag != "span" or opening != f'<span data-ui-icon="{value}">'
                        or not self.html.startswith("</span>", end)):
                    raise ValueError("DIRECT_BASELINE_ICON_REFERENCE")
                self.insertions.append((end, value))
        if tag in {"style", "script"}:
            self.raw_text_tag = tag

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == self.raw_text_tag:
            self.raw_text_tag = None

    @staticmethod
    def check_css(css, *, allow_bounded_css_svg=False):
        if allow_bounded_css_svg:
            validate_css_svg_urls(css, SVG_TAGS, CompactAssets.check_non_asset_css)
        else:
            CompactAssets.check_non_asset_css(decoded_css_escapes(css), "css")

    @staticmethod
    def check_non_asset_css(css, scope):
        check_asset_text(css, scope)
        if re.search(r"(?<![\w-])d\s*:|\bpath\s*\(", css, re.I):
            raise ValueError("DIRECT_BASELINE_CSS_VECTOR_DATA")

    def handle_data(self, data):
        if self.raw_text_tag == "style" and self.allow_bounded_css_svg:
            self.styles.append(data)
            return
        if self.raw_text_tag is not None:
            check_asset_text(data, self.raw_text_tag)
            if re.search(r"<\s*(?:svg|path)\b|createElementNS\s*\(", data, re.I):
                raise ValueError("DIRECT_BASELINE_AUTHORED_VECTOR")
        if self.raw_text_tag == "style":
            self.check_css(data)


def expand_catalog_icons(html, *, allow_bounded_css_svg=False):
    parser = CompactAssets(html, allow_bounded_css_svg=allow_bounded_css_svg)
    parser.feed(html)
    parser.close()
    if allow_bounded_css_svg:
        parser.check_css("\n".join(parser.styles), allow_bounded_css_svg=True)
    for offset, name in reversed(parser.insertions):
        svg = (
            '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + ICON_CATALOG[name] + "</svg>"
        )
        html = html[:offset] + svg + html[offset:]
    return html, [name for _, name in parser.insertions]


def require_complete_html(html):
    if not re.match(r"\s*<!doctype\s+html\s*>\s*<html(?:\s|>)", html, re.I) or not re.search(
            r"</html\s*>\s*\Z", html, re.I):
        raise ValueError("DIRECT_BASELINE_INCOMPLETE_DOCUMENT")
    boundary = DocumentBoundary()
    boundary.feed(html)
    boundary.close()
    if boundary.events != ["html", "head", "/head", "body", "/body", "/html"]:
        raise ValueError("DIRECT_BASELINE_INCOMPLETE_DOCUMENT")


HTML_FENCE = re.compile(
    r"\s*```html[ \t]*\r?\n(?P<html>.*?)\r?\n```[ \t]*\s*\Z",
    re.I | re.S,
)
NESTED_FENCE_LINE = re.compile(r"(?m)^[ \t]*(?:`{3,}|~{3,})")


def save_direct_html(raw, finish_reason, output, *, compact_assets=False, allow_bounded_css_svg=False):
    if finish_reason != "stop":
        raise ValueError("DIRECT_BASELINE_INCOMPLETE_RESPONSE")
    envelope = HTML_FENCE.fullmatch(raw)
    start, end = (0, len(raw)) if envelope is None else envelope.span("html")
    html = raw[start:end]
    if envelope is not None and NESTED_FENCE_LINE.search(html):
        raise ValueError("DIRECT_BASELINE_MULTIPLE_FENCES")
    require_complete_html(html)
    model_payload = html.encode("utf-8")
    icons = []
    if compact_assets or allow_bounded_css_svg:
        html, icons = expand_catalog_icons(html, allow_bounded_css_svg=allow_bounded_css_svg)
    artifact = output / "final.html"
    payload = html.encode("utf-8")
    with artifact.open("xb") as stream:
        stream.write(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "status": "HTML_GENERATED_PENDING_BROWSER_ACCEPTANCE", "html_generated": True,
        "html_contract_passed": True, "html_contract_scope": "document_boundary",
        "html_path": str(artifact), "html_sha256": digest,
        "renderer": "direct_multimodal_baseline_v1",
        "response_envelope": "single_html_fence" if envelope is not None else "raw_html",
        "response_utf8_start": len(raw[:start].encode("utf-8")),
        "response_utf8_end": len(raw[:end].encode("utf-8")),
        **({"model_html_sha256": hashlib.sha256(model_payload).hexdigest(),
            "expanded_icons": icons} if compact_assets or allow_bounded_css_svg else {}),
        **({"asset_compatibility": BOUNDED_CSS_COMPATIBILITY} if allow_bounded_css_svg else {}),
    }


def submit_direct_html(request, output, *, compact_assets=False):
    client = main_client("direct_coder")
    if client is None:
        raise RuntimeError("DIRECT_BASELINE_REQUIRES_BOUNDED_RUNTIME")
    if compact_assets:
        system, *rest = request["messages"]
        request = {**request, "messages": [{**system, "content": system["content"] + "\n\n" + ASSET_RULES}, *rest]}
    choice = client.chat.completions.create(**request).choices[0]
    result = save_direct_html(choice.message.content, choice.finish_reason, output, compact_assets=compact_assets)
    if compact_assets:
        result["asset_policy"] = DIRECT_ASSET_POLICY
    trace_event("direct_multimodal_baseline.html", **result)
    return result


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
    result = submit_direct_html({
        "model": MODEL, "temperature": 0.2,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": [
            {"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }, output, compact_assets=True)
    return {**result, "input_frame": source}
