import json
from urllib.parse import quote

import pytest

from src.renderers.region_bundle import authored_asset_rules, render_region_bundle


SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="16" fill="#1a73e8"/></svg>'
TREE = {"id": "page", "axis": "row", "children": [{"id": "asset"}]}


def render(*, css="", js="", attrs=None, enabled=True):
    bundle = {"css": css, "js": js, "panels": [], "components": [
        {"leaf_id": "asset", "tag": "img", "attrs": attrs or {}, "inner": ""}]}
    return render_region_bundle(json.dumps(bundle), TREE, bounded_svg_uri=enabled)


def css_uri(svg, mime="data:image/svg+xml;utf8", *, safe=""):
    return f"#asset{{background:url('{mime},{quote(svg, safe=safe)}')}}"


def test_original_short_utf8_svg_allowed_only_by_v2():
    source = css_uri(SVG, safe='<>"/:= ')
    assert len(source.split("'")[1].encode("utf-8")) == 174
    assert len(SVG.encode("utf-8")) == 148
    assert source in render(css=source)[0]
    assert "bounded_svg_uri_v2" in authored_asset_rules(bounded_svg_uri=True)
    with pytest.raises(ValueError, match="OPAQUE_ASSET"):
        render(css=source, enabled=False)


@pytest.mark.parametrize("css", [
    css_uri(SVG, "data:image/svg+xml;base64"),
    css_uri(SVG, "data:image/png"),
    css_uri(SVG, "data:image/svg+xmlx"),
    css_uri("<svg><script>alert(1)</script></svg>"),
    css_uri('<svg><g><use href="https://example.com/asset.svg#shape"/></g></svg>'),
    css_uri('<svg><circle onload="alert(1)"/></svg>'),
    css_uri('<svg><path fill="url(#local)"/></svg>'),
    css_uri('<svg><foreignObject/></svg>'),
    css_uri('<!DOCTYPE svg [<!ENTITY sample "value">]><svg>&sample;</svg>'),
    css_uri(quote(SVG)),
    css_uri('<svg><desc>' + '界' * 690 + '</desc></svg>'),
    css_uri('<svg><desc>' + 'x' * 1700 + '</desc></svg>') * 5,
    r"#asset{background:url('d\61ta:image/svg+xml,%3Csvg/%3E')}",
    "#asset{background:url(data:image/svg+xml,%3Csvg/%3E)}",
    "#asset{background:url('data:image/svg+xml,%ZZ')}",
])
def test_disallowed_assets_are_rejected(css):
    with pytest.raises(ValueError, match="SVG_URI|OPAQUE_ASSET"):
        render(css=css)


def test_html_and_js_data_urls_remain_disallowed():
    uri = css_uri(SVG).split("'")[1]
    with pytest.raises(ValueError, match="OPAQUE_ASSET"):
        render(attrs={"src": uri})
    with pytest.raises(ValueError, match="OPAQUE_ASSET"):
        render(js=f"asset.src = '{uri}'")
