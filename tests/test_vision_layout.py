import os
import tempfile
from types import SimpleNamespace
import json
from PIL import Image

from src.graph import nodes
from src.tools import vision_tool


def make_valid_layout():
    return {
        "schema_version": "1.0",
        "canvas": {"width": 400, "height": 800, "orientation": "portrait"},
        "elements": [
            {"id": "e1", "type": "text", "text": "标题", "bbox": {"x_min": 0.1, "y_min": 0.02, "x_max": 0.9, "y_max": 0.08}, "confidence": 0.98},
            {"id": "e2", "type": "button", "text": "提交", "bbox": {"x_min": 0.7, "y_min": 0.9, "x_max": 0.95, "y_max": 0.98}, "confidence": 0.92}
        ],
        "reading_order": ["e1", "e2"],
        "validation": {"valid": True, "completeness_score": 0.9, "element_count": 2, "errors": [], "warnings": []}
    }


def test_extract_called_when_image_present(monkeypatch, tmp_path):
    img = tmp_path / "img.png"
    img.write_bytes(b"ok")

    called = {"cnt": 0}

    def fake_extract(image_path, user_context=None, audit_logger=None):
        called["cnt"] += 1
        return make_valid_layout()

    # patch the vision_tool as used by nodes.vision_node
    monkeypatch.setattr(nodes, 'vision_tool', nodes.vision_tool)
    monkeypatch.setattr(nodes.vision_tool, 'extract_ui_layout', fake_extract)

    # create a real PNG image
    Image.new('RGB', (400, 800), 'white').save(img)

    state = {"messages": [SimpleNamespace(content=f"[IMAGE]: {str(img)}")]} 
    cmd = nodes.vision_node(state)
    assert called["cnt"] == 1
    assert cmd.update.get('vision_elements') is not None
    assert cmd.update.get('vision_status')['valid'] is True


def test_bbox_out_of_range_rejected():
    bad = make_valid_layout()
    bad['elements'][0]['bbox']['x_min'] = -0.1
    vl, validation = vision_tool.validate_vision_layout(bad, image_path=None)
    assert validation.valid is False
    assert any('invalid_bbox' in e for e in validation.errors)


def test_duplicate_id_rejected():
    bad = make_valid_layout()
    bad['elements'][1]['id'] = 'e1'
    vl, validation = vision_tool.validate_vision_layout(bad, image_path=None)
    assert validation.valid is False
    assert 'duplicate_ids' in validation.errors


def test_parent_not_exists_rejected():
    bad = make_valid_layout()
    bad['elements'][0]['parent_id'] = 'missing'
    vl, validation = vision_tool.validate_vision_layout(bad, image_path=None)
    assert validation.valid is False
    assert any('missing_parent' in e for e in validation.errors)


def test_retry_once_on_sparse(monkeypatch, tmp_path):
    img = tmp_path / "img2.png"
    Image.new('RGB', (400, 800), 'white').save(img)

    calls = []

    def first_extract(image_path, user_context=None, audit_logger=None):
        calls.append('first')
        # sparse layout
        return {
            "schema_version": "1.0",
            "canvas": {"width": 400, "height": 800, "orientation": "portrait"},
            "elements": [],
            "reading_order": [],
            "validation": {"valid": False, "completeness_score": 0.0, "element_count": 0, "errors": ["no_elements"], "warnings": ["element_count_low"]}
        }

    def second_extract(image_path, user_context=None, audit_logger=None):
        calls.append('second')
        return make_valid_layout()

    # patch nodes.vision_tool.extract_ui_layout to simulate two calls
    monkeypatch.setattr(nodes, 'vision_tool', nodes.vision_tool)

    def extractor_switch(image_path, user_context=None, audit_logger=None):
        if len(calls) == 0:
            return first_extract(image_path, user_context, audit_logger)
        else:
            return second_extract(image_path, user_context, audit_logger)

    monkeypatch.setattr(nodes.vision_tool, 'extract_ui_layout', extractor_switch)

    state = {"messages": [SimpleNamespace(content=f"[IMAGE]: {str(img)}")]} 
    cmd = nodes.vision_node(state)
    # Expect two calls (first + retry)
    assert 'vision_elements' in cmd.update
    assert cmd.update['vision_status']['valid'] is True
