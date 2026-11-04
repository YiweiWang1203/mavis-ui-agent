from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from src.agents.coder import generate_frontend_code
from src.renderers.region_bundle import RENDERER, layout_style_targets, render_region_bundle
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
    "panels": [{"id": "panel--detail", "inner": '<dialog id="panel--detail--dialog">Details</dialog>'}],
    "css": "#aside{min-height:100px}",
    "js": 'document.getElementById("submit").onclick=()=>document.getElementById("panel--detail--dialog").showModal()',
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

    @patch.dict("os.environ", {"UI_RENDERER_MODE": RENDERER, "UI_CODER_CONTRACT_MODE": "main_system_v1",
                              "CODER_MODEL": MODEL})
    def test_production_coder_keeps_response_separate_and_rejects_failed_compile(self):
        state = {"region_tree": TREE, "page_meta": {"contract_version": 2}}
        for success in (True, False):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = json.dumps(BUNDLE if success else BUNDLE | {"components": []})

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
                            self.assertIn("<!doctype html>", Path(output["file_path"]).read_text(encoding="utf-8"))
                        else:
                            with self.assertRaisesRegex(ValueError, "LEAF_COVERAGE"):
                                generate_frontend_code(state)
                            self.assertFalse((root / "html").exists())
                request = json.loads((root / "requests/coder_request.json").read_text(encoding="utf-8"))
                self.assertEqual(request["response_format"], {"type": "json_object"})
                user = json.loads(request["messages"][1]["content"])
                self.assertEqual(user["layout_style_targets"], layout_style_targets(TREE))
                self.assertIn("It has no class", request["messages"][0]["content"])
                packet = json.loads((root / "requests/coder_response.json").read_text(encoding="utf-8"))
                self.assertEqual(packet["response"]["choices"][0]["message"]["content"], raw)
