from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from src.agents.coder import generate_frontend_code
from src.renderers.region_bundle import RENDERER, layout_style_targets, render_region_bundle, repeated_content_identities
from src.service.main_model_runtime import MODEL, MainModelRuntime


TREE = {"id": "page", "axis": "row", "children": [
    {"id": "main", "axis": "column", "grow": True, "children": [
        {"id": "results"}, {"id": "memo"}, {"id": "choice"},
        {"id": "entry"}, {"id": "photo"}, {"id": "submit", "slot": "bottom"}]},
    {"id": "aside", "axis": "column", "cross_align": "start", "children": [{"id": "icon"}]},
]}
BUNDLE = {
    "components": [
        {"leaf_id": "submit", "tag": "button", "attrs": {"type": "button"}, "inner": "Submit"},
        {"leaf_id": "entry", "tag": "input", "attrs": {"type": "text"}, "inner": ""},
        {"leaf_id": "photo", "tag": "img", "attrs": {"alt": "Photo"}, "inner": ""},
        {"leaf_id": "memo", "tag": "textarea", "attrs": {}, "inner": "Draft"},
        {"leaf_id": "choice", "tag": "select", "attrs": {}, "inner": "<option>One</option>"},
        {"leaf_id": "results", "tag": "div", "attrs": {}, "inner":
         '<p id="results--row-1"><i>First</i></p><p id="results--row-2">Second</p>'},
        {"leaf_id": "icon", "tag": "figure", "attrs": {}, "inner":
         '<svg viewBox="0 0 40 20"><defs><linearGradient id="icon--gradient">'
         '<stop offset="0" stop-color="red"/></linearGradient></defs>'
         '<rect width="40" height="20" fill="url(#icon--gradient)"/>'
         '<text x="1" y="14"><tspan>Icon</tspan></text></svg>'},
    ],
    "panels": [{"id": "panel--detail", "inner": '<dialog id="panel--detail--dialog">Details'
                '<button id="panel--detail--close" type="button">Close</button></dialog>'}],
    "css": "#aside{min-height:100px}",
    "js": 'document.getElementById("submit").addEventListener("click",()=>'
          'document.getElementById("panel--detail--dialog").showModal());'
          'document.getElementById("panel--detail--close").addEventListener("click",()=>'
          'document.getElementById("panel--detail--dialog").close());',
}


class RegionBundleTests(unittest.TestCase):
    def render(self, bundle):
        return render_region_bundle(json.dumps(bundle), TREE)

    def test_layout_owned_by_tree_and_native_content_preserved(self):
        html, report = self.render(BUNDLE)
        self.assertTrue(report["passed"])
        self.assertEqual(report["actual"][:4], [
            ("page", None, "row", None), ("main", "page", "column", None),
            ("results", "main", None, None), ("memo", "main", None, None)])
        self.assertIn('id="submit" data-ui-id="submit" data-ui-slot="bottom"', html)
        self.assertIn("flex-flow:row nowrap !important", html)
        self.assertIn("margin-top:auto !important", html)
        self.assertNotIn("fit-content", html)
        self.assertIn('<input id="entry" data-ui-id="entry"', html)
        self.assertIn('<img id="photo" data-ui-id="photo"', html)
        self.assertIn(">Draft</textarea>", html)
        self.assertIn("<option>One</option></select>", html)
        self.assertIn('<p id="results--row-1"><i>First</i></p>', html)
        self.assertIn('<text x="1" y="14"><tspan>Icon</tspan></text>', html)
        self.assertIn('fill="url(#icon--gradient)"', html)
        self.assertGreater(html.index(BUNDLE["js"]), html.index('id="panel--detail"'))

    def test_missing_duplicate_and_extra_leaf_rejected(self):
        for parts in (BUNDLE["components"][:-1], BUNDLE["components"] + BUNDLE["components"][:1],
                      BUNDLE["components"] + [BUNDLE["components"][0] | {"leaf_id": "aside"}]):
            with self.subTest(parts=len(parts)), self.assertRaisesRegex(ValueError, "LEAF_COVERAGE"):
                self.render(BUNDLE | {"components": parts})

    def test_catalog_matches_rendered_identity_and_fixed_properties(self):
        html, _ = self.render(BUNDLE)
        targets = layout_style_targets(TREE)
        main = targets["main"]
        self.assertEqual(main["selector"], "#main")
        self.assertEqual(main["tag"], "div")
        self.assertEqual(main["program_attributes"], {"id": "main", "data-ui-id": "main", "data-ui-axis": "column"})
        self.assertEqual(main["fixed_css"]["flex"], "1 1 0%")
        self.assertNotIn("width", main["fixed_css"])
        self.assertEqual(targets["submit"]["fixed_css"]["margin-top"], "auto")
        self.assertEqual(targets["page"]["fixed_css"]["width"], "100%")
        for row in targets.values():
            attrs = " ".join(f'{key}="{value}"' for key, value in row["program_attributes"].items())
            style = ";".join(f"{prop}:{value} !important" for prop, value in row["fixed_css"].items())
            self.assertRegex(html, re.escape(attrs) + r'[^>]*' + re.escape(f' style="{style}"'))

    def test_selector_diagnostic_reports_only_simple_initial_markup_misses(self):
        css = """
            /* .ghost { color:red } */ .main { padding:8px }
            #main { overflow:auto } #wrong { margin:0 }
            #results--row-1 { color:blue } #panel--detail { padding:8px }
            .later:hover, .combo { color:green }
            @media(min-width:500px) { .inside { color:blue } }
            .bad-value { content: "} .not-a-rule { "; }
            [data-name="{.attribute}"] { color: green }
        """
        _, report = self.render(BUNDLE | {"css": css})
        self.assertTrue(report["passed"])
        self.assertEqual(report["css_selector_diagnostic"]["unmatched_warnings"],
                         ["#wrong", ".bad-value", ".main"])

    def test_content_cannot_claim_layout_or_duplicate_ids(self):
        for inner in ('<span id="page">bad</span>', '<span data-ui-id="entry">bad</span>',
                      '<span id="submit--one"></span><span id="submit--one"></span>',
                      '</button><button>', '<p><div>bad</div></p>'):
            bundle = deepcopy(BUNDLE)
            bundle["components"][0]["inner"] = inner
            with self.subTest(inner=inner), self.assertRaises(ValueError):
                self.render(bundle)
        with self.assertRaisesRegex(ValueError, "PANEL_ID"):
            self.render(BUNDLE | {"panels": [{"id": "main", "inner": ""}]})
        with self.assertRaisesRegex(ValueError, "RAW_TEXT_BOUNDARY"):
            self.render(BUNDLE | {"js": 'const x = "</script>";'})

    def test_inline_handlers_rejected_across_authored_markup(self):
        for scope in ("leaf root", "component descendant", "panel descendant"):
            bundle = deepcopy(BUNDLE)
            if scope == "leaf root":
                bundle["components"][0]["attrs"]["onclick"] = "close()"
            elif scope == "component descendant":
                bundle["components"][0]["inner"] = '<span OnClick="close()">Close</span>'
            else:
                bundle["panels"][0]["inner"] = '<div><button onclick="close()">Close</button></div>'
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "REGION_BUNDLE_ATTRIBUTE: .*: onclick"):
                self.render(bundle)

    def test_repeated_identity_reserves_layout_ids_and_distinguishes_nested_source_items(self):
        elements = [{"id": "results", "items": [{"id": "source", "items": [{"id": "source"}]}, {}]}]
        self.assertEqual(repeated_content_identities(elements, {"results", "results--item-1"}), {"results": [
            {"item_path": [0], "source_item_id": "source", "dom_id": "results--item-2"},
            {"item_path": [0, 0], "source_item_id": "source", "dom_id": "results--item-3"},
            {"item_path": [1], "source_item_id": None, "dom_id": "results--item-4"},
        ]})

    def test_repeated_content_rejects_bare_duplicate_and_cross_owner_ids(self):
        for label, ids in (("bare", ("results_1", "results--item-2")),
                           ("duplicate", ("results--item-1", "results--item-1")),
                           ("cross owner", ("submit--item-1", "results--item-2"))):
            bundle = deepcopy(BUNDLE)
            results = next(part for part in bundle["components"] if part["leaf_id"] == "results")
            results["inner"] = "".join(f'<p id="{key}">Row</p>' for key in ids)
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "REGION_BUNDLE_CONTENT_ID: results"):
                self.render(bundle)

    @patch.dict("os.environ", {"UI_RENDERER_MODE": RENDERER, "UI_CODER_CONTRACT_MODE": "main_system_v1",
                              "CODER_MODEL": MODEL})
    def test_production_coder_keeps_response_separate_and_rejects_failed_compile(self):
        elements = [{"id": "results", "items": [{"id": "results_1"}]}]
        state = {"region_tree": TREE, "page_meta": {"contract_version": 2}, "elements": elements}
        valid = deepcopy(BUNDLE)
        results = next(part for part in valid["components"] if part["leaf_id"] == "results")
        results["inner"] = ('<label id="results--name" for="results--item-1">First</label>'
                            '<input id="results--item-1" aria-labelledby="results--name">')
        valid["css"] += " #results--item-1{color:red}"
        valid["js"] += 'document.getElementById("results--item-1").addEventListener("change",()=>{});'
        for success in (True, False):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = json.dumps(valid if success else BUNDLE | {"components": []})

                def dispatch(request, **kwargs):
                    return {"ok": True, "response": {"choices": [
                        {"finish_reason": "stop", "message": {"content": raw}}]}}

                with MainModelRuntime(root / "requests", dispatch, profile="semantic7") as runtime:
                    for stage in ("vision", "architect", "semantic_audit"):
                        runtime.create(stage, model=MODEL)
                    with patch("src.agents.coder.HTML_OUTPUT_DIR", root / "html"):
                        if success:
                            output = generate_frontend_code(state)
                            self.assertEqual(output["renderer"], RENDERER)
                            html = Path(output["file_path"]).read_text(encoding="utf-8")
                            self.assertIn("<!doctype html>", html)
                            self.assertIn(results["inner"], html)
                            self.assertIn(valid["css"], html)
                            self.assertIn(valid["js"], html)
                        else:
                            with self.assertRaisesRegex(ValueError, "LEAF_COVERAGE"):
                                generate_frontend_code(state)
                            self.assertFalse((root / "html").exists())
                request = json.loads((root / "requests/coder_request.json").read_text(encoding="utf-8"))
                self.assertEqual(request["response_format"], {"type": "json_object"})
                user = json.loads(request["messages"][1]["content"])
                self.assertEqual(user["layout_style_targets"], layout_style_targets(TREE))
                self.assertEqual(user["execution"]["elements"], elements)
                self.assertEqual(user["repeated_content_identities"], {"results": [
                    {"item_path": [0], "source_item_id": "results_1", "dom_id": "results--item-1"},
                ]})
                system = request["messages"][0]["content"]
                self.assertIn("It has no class", system)
                self.assertIn("leaf roots (attrs), component descendants (inner), "
                              "and panel descendants (panels[].inner): no data-ui-*, on* attributes", system)
                self.assertIn('id="panel--example--close"', system)
                self.assertIn('getElementById("panel--example--close").addEventListener("click"', system)
                self.assertIn("source_item_id identifies the source item and is never an HTML id", system)
                packet = json.loads((root / "requests/coder_response.json").read_text(encoding="utf-8"))
                self.assertEqual(packet["response"]["choices"][0]["message"]["content"], raw)
