import ast
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class CandidatePersistenceTests(unittest.TestCase):
    def run_candidate(self, html):
        source_path = Path("src/agents/coder.py").resolve()
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        names = {"generate_frontend_code", "strip_markdown_code_fence",
                 "save_html_asset", "is_complete_html_document"}
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for function in functions:
            function.decorator_list = []
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=html), finish_reason="stop")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
        state = {"page_meta": {"structure_mode": "region_tree_v1", "contract_version": 2},
                 "region_tree": {"id": "page", "axis": "column", "children": [{"id": "x"}]},
                 "elements": [{"id": "x", "type": "button"}], "requirements": [], "actions": []}
        with tempfile.TemporaryDirectory() as directory:
            namespace = {"__file__": str(source_path), "os": os, "json": json, "Path": Path,
                         "datetime": datetime, "logging": logging, "HTML_OUTPUT_DIR": Path(directory),
                         "DEFAULT_CODER_MODEL": "test", "_get_openai_client": lambda: client,
                         "trace_html_contract": lambda *args, **kwargs: None}
            exec(compile(ast.Module(body=functions, type_ignores=[]), str(source_path), "exec"), namespace)
            with patch.dict(os.environ, {"UI_RENDERER_MODE": "llm", "UI_CODER_CONTRACT_MODE": "main_system_v1",
                                        "UI_INPUT_CONTRACT_MODE": "off", "MAVIS_MAIN_RUN_ID": "fixture"}):
                result = namespace["generate_frontend_code"](state)
            raw = Path(result["raw_candidate_path"]).read_text(encoding="utf-8")
            saved = Path(result["file_path"]).read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                # The same frozen timestamp/name must never overwrite a candidate.
                stamp = Path(result["raw_candidate_path"]).stem.removeprefix("html_raw_candidate_")
                class FrozenClock:
                    @staticmethod
                    def now():
                        return datetime.strptime(stamp, "%Y%m%d_%H%M%S")
                namespace["datetime"] = FrozenClock
                with patch.dict(os.environ, {"MAVIS_MAIN_RUN_ID": "fixture"}):
                    namespace["save_html_asset"]("replacement", raw_candidate=True)
            self.assertEqual(Path(result["raw_candidate_path"]).read_text(encoding="utf-8"), raw)
            return result, raw, saved

    def test_duplicate_marker_is_preserved_as_failed_complete_candidate(self):
        html = '<html><head></head><body><main data-ui-id="page" data-ui-axis="column"><div data-ui-id="x"><button data-ui-id="x">Go</button></div></main></body></html>'
        result, raw, saved = self.run_candidate(html)
        self.assertFalse(result["html_validation"]["passed"])
        self.assertEqual(raw, html)
        self.assertEqual(saved, html)
        self.assertEqual(result["code"], html)
        self.assertNotIn('data-region-contract="2"', saved)
        self.assertNotEqual(result["html_validation"]["expected"], result["html_validation"]["actual"])

    def test_valid_candidate_keeps_raw_and_compiles_separate_html(self):
        html = '<html><head></head><body><main data-ui-id="page" data-ui-axis="column"><button data-ui-id="x">Go</button></main></body></html>'
        result, raw, saved = self.run_candidate(html)
        self.assertTrue(result["html_validation"]["passed"])
        self.assertEqual(raw, html)
        self.assertIn('data-region-contract="2"', saved)
        self.assertEqual(result["code"], saved)
        self.assertNotEqual(result["file_path"], result["raw_candidate_path"])

    def test_missing_head_returns_saved_raw_with_compilation_failure(self):
        html = '<html><body><main data-ui-id="page" data-ui-axis="column"><button data-ui-id="x">Go</button></main></body></html>'
        result, raw, saved = self.run_candidate(html)
        self.assertFalse(result["html_validation"]["passed"])
        self.assertEqual(result["html_validation"]["error"], "REGION_HTML_REQUIRES_ONE_HEAD")
        self.assertEqual(raw, html)
        self.assertEqual(saved, html)

    def test_incomplete_document_still_fails(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_HTML"):
            self.run_candidate("<html><head>")
