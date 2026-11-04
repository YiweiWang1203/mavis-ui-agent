"""Validate the optional small static SVG subset in quoted CSS URLs."""
import re
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree


MAX_SVG_BYTES = 2048
MAX_TOTAL_SVG_BYTES = 8192
MAX_URI_BYTES = 3 * MAX_SVG_BYTES + len("data:image/svg+xml;charset=utf-8,")
SVG_NS = "{http://www.w3.org/2000/svg}"
STATIC_TAGS = frozenset("svg g path circle ellipse rect line polyline polygon title desc text tspan".split())
STATIC_ATTRS = frozenset(
    "viewBox width height x y x1 y1 x2 y2 cx cy r rx ry d points fill fill-rule fill-opacity "
    "stroke stroke-width stroke-opacity stroke-linecap stroke-linejoin stroke-dasharray opacity "
    "transform preserveAspectRatio text-anchor font-size".split()
)
QUOTED_SVG_URL = re.compile(
    r"""(?<![\w-])url\(\s*(?P<quote>['"])(?P<uri>data:image/svg\+xml(?:;utf8|;charset=utf-8)?,[^\r\n]*?)(?P=quote)\s*\)""",
    re.I,
)
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-f]{1,6})(?:\r\n|[ \t\n\r\f])?|([^\n\r\f])|\r\n|[\n\r\f])", re.I)


def decoded_css_escapes(css):
    def decode(match):
        digits, literal = match.groups()
        if digits:
            code = int(digits, 16)
            return chr(code) if 0 < code <= 0x10FFFF else "\ufffd"
        return literal or ""
    return CSS_ESCAPE.sub(decode, css)


def validate_uri(uri, allowed_tags):
    _, payload = uri.split(",", 1)
    if (len(uri.encode("utf-8")) > MAX_URI_BYTES or re.search(r"%(?![0-9a-f]{2})|[\\#]", payload, re.I)):
        raise ValueError("REGION_BUNDLE_SVG_URI_ENCODING")
    svg = unquote_to_bytes(payload)
    if len(svg) > MAX_SVG_BYTES:
        raise ValueError("REGION_BUNDLE_SVG_URI_SIZE")
    try:
        text = svg.decode("utf-8", "strict")
        if re.search(r"<[!?]|&|%[0-9a-f]{2}|[\x00-\x08\x0b\x0c\x0e-\x1f]", text, re.I):
            raise ValueError("REGION_BUNDLE_SVG_URI_ENCODING")
        root = ElementTree.fromstring(text)
    except (UnicodeError, ElementTree.ParseError) as error:
        raise ValueError("REGION_BUNDLE_SVG_URI_PARSE") from error
    if root.tag not in {"svg", SVG_NS + "svg"}:
        raise ValueError("REGION_BUNDLE_SVG_URI_ROOT")
    for node in root.iter():
        tag = node.tag.removeprefix(SVG_NS)
        if tag not in STATIC_TAGS or tag.lower() not in allowed_tags:
            raise ValueError("REGION_BUNDLE_SVG_URI_TAG")
        for name, value in node.attrib.items():
            if (name not in STATIC_ATTRS or not re.fullmatch(r"[\w\s.,+#%()/\-]*", value, flags=re.ASCII)
                    or re.search(r"\burl\s*\(", value, re.I)):
                raise ValueError("REGION_BUNDLE_SVG_URI_ATTRIBUTE")
    return len(svg)


def validate_css_svg_urls(css, allowed_tags, reject_opaque):
    total = 0
    end = 0

    def check_other_css(value):
        value = decoded_css_escapes(value)
        reject_opaque(value, "css")
        if re.search(r"<svg\b", value, re.I):
            raise ValueError("REGION_BUNDLE_SVG_LOCATION: css")

    for match in QUOTED_SVG_URL.finditer(css):
        check_other_css(css[end:match.start()])
        total += validate_uri(match.group("uri"), allowed_tags)
        if total > MAX_TOTAL_SVG_BYTES:
            raise ValueError("REGION_BUNDLE_SVG_URI_TOTAL_SIZE")
        end = match.end()
    check_other_css(css[end:])
