"""Compile authored leaf content into the DOM owned by the region plan."""
from html import escape
from html.parser import HTMLParser
import json
import re

from src.schemas.region_plan import Contract
from src.utils.region_tree import check_region_markup


RENDERER = "region_bundle_v1"
LEAF_TAGS = frozenset("a article button div figure footer header img input label main nav p section select span textarea ul ol".split())
VOID_TAGS = frozenset("br hr img input".split())
SVG_TAGS = frozenset("svg g path circle ellipse rect line polyline polygon title desc defs lineargradient radialgradient stop text tspan clippath".split())
CONTENT_TAGS = LEAF_TAGS | VOID_TAGS | SVG_TAGS | frozenset(
    "b blockquote dialog em fieldset form h1 h2 h3 h4 h5 h6 i legend li option small strong time".split()
)
PARAGRAPH_BREAKERS = frozenset(
    "article blockquote dialog div fieldset figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p section ul".split()
)
NODE_STYLE = ("position:relative", "inset:auto", "order:0", "box-sizing:border-box")
REGION_STYLE = ("display:flex", "align-items:stretch", "direction:ltr", "writing-mode:horizontal-tb")
PAGE_STYLE = ("width:100%", "min-height:100dvh")
ALIGNMENTS = {"start": "flex-start", "end": "flex-end", "center": "center", "stretch": "stretch"}
FIXED_CSS = (
    "Program-owned CSS properties by scope. All layout nodes: "
    + ", ".join(rule.split(":")[0] for rule in NODE_STYLE) + ", align-self, flex. Regions: "
    + ", ".join(rule.split(":")[0] for rule in REGION_STYLE) + ", flex-flow. Page: "
    + ", ".join(rule.split(":")[0] for rule in PAGE_STYLE) + ". Bottom slots: margin-top."
)


class Component(Contract):
    leaf_id: str
    tag: str
    attrs: dict[str, str]
    inner: str


class Panel(Contract):
    id: str
    inner: str


class Bundle(Contract):
    components: list[Component]
    panels: list[Panel]
    css: str
    js: str


def validate_attrs(attrs, owner, ids, *, root=False):
    seen = set()
    for name, value in attrs:
        if (not re.fullmatch(r"[a-z][a-z0-9_:-]*", name) or name in seen
                or name.startswith(("data-ui-", "on")) or name in {"is", "srcdoc"}
                or (root and name in {"id", "style"})):
            raise ValueError(f"REGION_BUNDLE_ATTRIBUTE: {owner}: {name}")
        seen.add(name)
        if name == "id":
            prefix = owner + "--"
            if (not value or not value.startswith(prefix) or len(value) == len(prefix)
                    or re.search(r"[\s\x00-\x1f\x7f]", value) or value in ids):
                raise ValueError(f"REGION_BUNDLE_CONTENT_ID: {owner}: {value}")
            ids.add(value)


class Fragment(HTMLParser):
    def __init__(self, owner, ids, root):
        super().__init__(convert_charrefs=False)
        self.owner, self.ids = owner, ids
        self.stack = [root]

    def start(self, tag, attrs, self_closing=False):
        svg = "svg" in self.stack
        if (tag not in CONTENT_TAGS or (tag in SVG_TAGS - {"svg"} and not svg)
                or (svg and tag not in SVG_TAGS)
                or ("textarea" in self.stack or "option" in self.stack)
                or ("select" in self.stack and tag != "option")
                or ("p" in self.stack and tag in PARAGRAPH_BREAKERS)
                or (tag in {"a", "button", "form", "li", "label"} and tag in self.stack)
                or ("button" in self.stack and tag in {"a", "input", "select", "textarea"})
                or (self_closing and tag not in VOID_TAGS and not (svg or tag == "svg"))):
            raise ValueError(f"REGION_BUNDLE_TAG: {self.owner}: {tag}")
        validate_attrs(attrs, self.owner, self.ids)
        if tag not in VOID_TAGS and not self_closing:
            self.stack.append(tag)

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        if len(self.stack) == 1 or self.stack.pop() != tag:
            raise ValueError(f"REGION_BUNDLE_UNBALANCED: {self.owner}: {tag}")

    def handle_decl(self, decl):
        raise ValueError(f"REGION_BUNDLE_DECLARATION: {self.owner}")

    unknown_decl = handle_decl
    handle_pi = handle_decl
    handle_comment = handle_decl

    def handle_data(self, data):
        if "<" in data:
            raise ValueError(f"REGION_BUNDLE_UNESCAPED_TEXT: {self.owner}")


def render_region_bundle(raw, tree):
    def unique_object(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("REGION_BUNDLE_DUPLICATE_JSON_KEY")
        return value

    bundle = Bundle.model_validate(json.loads(raw, object_pairs_hook=unique_object))
    nodes, leaves = set(), set()

    def index(node):
        nodes.add(node["id"])
        if "children" in node:
            for child in node["children"]:
                index(child)
        else:
            leaves.add(node["id"])

    index(tree)
    components = {part.leaf_id: part for part in bundle.components}
    if leaves != components.keys() or len(components) != len(bundle.components):
        raise ValueError(f"REGION_BUNDLE_LEAF_COVERAGE: missing={sorted(leaves - components.keys())} "
                         f"extra={sorted(components.keys() - leaves)} or duplicate leaf")
    ids = set(nodes)
    for panel in bundle.panels:
        if not re.fullmatch(r"panel--[A-Za-z0-9_-]+", panel.id) or panel.id in ids:
            raise ValueError(f"REGION_BUNDLE_PANEL_ID: {panel.id}")
        ids.add(panel.id)

    def check_inner(owner, tag, inner):
        parser = Fragment(owner, ids, tag)
        parser.feed(inner)
        parser.close()
        if len(parser.stack) != 1:
            raise ValueError(f"REGION_BUNDLE_UNBALANCED: {owner}")

    def build(node):
        key = node["id"]
        node_id = escape(key, quote=True)
        attrs = f' id="{node_id}" data-ui-id="{node_id}"'
        style = [*NODE_STYLE, "align-self:" + ALIGNMENTS.get(node.get("cross_align"), "auto")]
        style.append("flex:1 1 0%" if node.get("grow") else "flex:0 1 auto")
        if node.get("slot") == "bottom":
            attrs += ' data-ui-slot="bottom"'
            style.append("margin-top:auto")
        if key == "page":
            style.extend(PAGE_STYLE)
        if "children" in node:
            axis = node["axis"]
            tag = "div"
            attrs += f' data-ui-axis="{axis}"'
            style.extend((*REGION_STYLE, "flex-flow:" + axis + " nowrap"))
            inner = "".join(build(child) for child in node["children"])
        else:
            part = components[key]
            tag, inner = part.tag, part.inner
            if tag not in LEAF_TAGS or (tag in VOID_TAGS and inner):
                raise ValueError(f"REGION_BUNDLE_LEAF_TAG: {key}: {tag}")
            validate_attrs(part.attrs.items(), key, ids, root=True)
            check_inner(key, tag, inner)
            attrs += "".join(f' {name}="{escape(value, quote=True)}"' for name, value in part.attrs.items())
        attrs += ' style="' + ";".join(rule + " !important" for rule in style) + '"'
        return f"<{tag}{attrs}>" + (f"{inner}</{tag}>" if tag not in VOID_TAGS else "")

    body = build(tree)
    for panel in bundle.panels:
        check_inner(panel.id, "div", panel.inner)
        body += f'<div id="{panel.id}">{panel.inner}</div>'
    if re.search(r"</?style\b", bundle.css, re.I) or re.search(r"</?script\b|<!--", bundle.js, re.I):
        raise ValueError("REGION_BUNDLE_RAW_TEXT_BOUNDARY")
    code = ('<!doctype html>\n<html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>body{margin:0}[data-ui-id]{min-width:0;min-height:0}\n'
            + bundle.css + '</style></head><body>'
            + body + '<script>\n' + bundle.js + '\n</script></body></html>')
    validation = check_region_markup(code, tree, direct_parent=True)
    return code, validation
