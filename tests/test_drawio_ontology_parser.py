import importlib.util
from pathlib import Path

from src.schemas.ui_element_ontology import UIElementOntologyPayload


def _load_parser():
    module_path = Path(__file__).resolve().parents[1] / "src" / "tools" / "drawio_ontology_parser.py"
    spec = importlib.util.spec_from_file_location("drawio_ontology_parser", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_fixture(tmp_path):
    content = """<mxfile>
  <diagram name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="canvas" value="" style="rounded=0;whiteSpace=wrap;html=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="400" height="800" as="geometry"/>
        </mxCell>
        <mxCell id="legend-outside" value="type=text;text_content=图例" style="strokeColor=#00CC00;" vertex="1" parent="1">
          <mxGeometry x="0" y="0" width="80" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="group" value="" style="group" vertex="1" parent="1">
          <mxGeometry x="120" y="120" width="300" height="300" as="geometry"/>
        </mxCell>
        <mxCell id="std-region" value="type=region;interactive=true;shape=rectangle" style="rounded=0;" vertex="1" parent="1">
          <mxGeometry x="110" y="120" width="100" height="80" as="geometry"/>
        </mxCell>
        <mxCell id="std-text" value="type=text;text_content=用户名;interactive=false" style="text;" vertex="1" parent="1">
          <mxGeometry x="120" y="220" width="160" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="green-text" value="" style="strokeColor=#00CC00;" vertex="1" parent="1">
          <mxGeometry x="120" y="280" width="120" height="30" as="geometry"/>
        </mxCell>
        <mxCell id="red-icon" value="" style="ellipse;strokeColor=#FF0000;" vertex="1" parent="1">
          <mxGeometry x="120" y="330" width="40" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="red-avatar" value="头像" style="ellipse;strokeColor=#FF0000;" vertex="1" parent="1">
          <mxGeometry x="180" y="330" width="60" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="blue-card" value="可交互商品卡片" style="rounded=0;strokeColor=#0000FF;" vertex="1" parent="1">
          <mxGeometry x="120" y="420" width="200" height="120" as="geometry"/>
        </mxCell>
        <mxCell id="cn-id" value="ID信息" style="text;" vertex="1" parent="1">
          <mxGeometry x="120" y="560" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="cn-divider" value="分割线" style="shape=line;" vertex="1" parent="1">
          <mxGeometry x="100" y="620" width="400" height="2" as="geometry"/>
        </mxCell>
        <mxCell id="html-value" value="&lt;font style=&quot;font-size: 6px;&quot;&gt;交互区域&lt;/font&gt;" style="rounded=0;" vertex="1" parent="1">
          <mxGeometry x="120" y="650" width="120" height="40" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
    path = tmp_path / "fixture.drawio"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_drawio_to_ontology_supports_standard_chinese_and_style_fallbacks(tmp_path):
    parser = _load_parser()
    path = _write_fixture(tmp_path)

    payload = parser.parse_drawio_to_ontology(str(path))
    validated = UIElementOntologyPayload.model_validate(payload)
    by_id = {element["id"]: element for element in payload["elements"]}

    assert validated.schema_version == "ui_element_ontology_v0.1"
    assert "canvas" not in by_id
    assert "legend-outside" not in by_id
    assert "group" not in by_id
    assert len(payload["elements"]) == 9

    assert by_id["std-region"]["type"] == "region"
    assert by_id["std-region"]["interactive"] is True
    assert by_id["std-region"]["shape"] == "rectangle"
    assert by_id["std-text"]["type"] == "text"
    assert by_id["std-text"]["text_content"] == "用户名"
    assert by_id["std-text"]["interactive"] is False
    assert by_id["green-text"]["type"] == "text"
    assert by_id["red-icon"]["type"] == "icon"
    assert by_id["red-icon"]["shape"] == "circle"
    assert by_id["red-icon"]["interactive"] is True
    assert by_id["red-avatar"]["type"] == "image"
    assert by_id["red-avatar"]["shape"] == "circle"
    assert by_id["red-avatar"]["interactive"] is False
    assert by_id["blue-card"]["type"] == "region"
    assert by_id["blue-card"]["interactive"] is True
    assert by_id["cn-id"]["type"] == "text"
    assert by_id["cn-divider"]["type"] == "divider"
    assert by_id["cn-divider"]["shape"] == "line"
    assert by_id["html-value"]["type"] == "region"
    assert by_id["html-value"]["interactive"] is True

    for element in payload["elements"]:
        bbox = element["bbox"]
        assert 0 <= bbox["x_min"] < bbox["x_max"] <= 1
        assert 0 <= bbox["y_min"] < bbox["y_max"] <= 1
