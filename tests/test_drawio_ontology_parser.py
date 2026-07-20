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
        <mxCell id="canvas" value="canvas" style="rounded=0;" vertex="1" parent="1">
          <mxGeometry x="0" y="0" width="400" height="800" as="geometry"/>
        </mxCell>
        <mxCell id="std-region" value="type=region;interactive=true;shape=rectangle" style="rounded=0;" vertex="1" parent="1">
          <mxGeometry x="10" y="20" width="100" height="80" as="geometry"/>
        </mxCell>
        <mxCell id="std-text" value="type=text;text_content=用户名;interactive=false" style="text;" vertex="1" parent="1">
          <mxGeometry x="20" y="120" width="160" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="cn-card" value="可交互商品卡片" style="rounded=1;" vertex="1" parent="1">
          <mxGeometry x="20" y="180" width="200" height="120" as="geometry"/>
        </mxCell>
        <mxCell id="cn-avatar" value="头像" style="ellipse;" vertex="1" parent="1">
          <mxGeometry x="30" y="320" width="60" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="cn-id" value="ID信息" style="text;" vertex="1" parent="1">
          <mxGeometry x="100" y="320" width="120" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="cn-divider" value="分割线" style="shape=line;" vertex="1" parent="1">
          <mxGeometry x="0" y="400" width="400" height="2" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""
    path = tmp_path / "fixture.drawio"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_drawio_to_ontology_supports_standard_and_chinese_labels(tmp_path):
    parser = _load_parser()
    path = _write_fixture(tmp_path)

    payload = parser.parse_drawio_to_ontology(str(path))
    validated = UIElementOntologyPayload.model_validate(payload)
    by_id = {element["id"]: element for element in payload["elements"]}

    assert validated.schema_version == "ui_element_ontology_v0.1"
    assert len(payload["elements"]) == 6
    assert by_id["std-region"]["type"] == "region"
    assert by_id["std-region"]["interactive"] is True
    assert by_id["std-region"]["shape"] == "rectangle"
    assert by_id["std-text"]["type"] == "text"
    assert by_id["std-text"]["text_content"] == "用户名"
    assert by_id["std-text"]["interactive"] is False
    assert by_id["cn-card"]["type"] == "region"
    assert by_id["cn-card"]["interactive"] is True
    assert by_id["cn-avatar"]["type"] == "image"
    assert by_id["cn-avatar"]["shape"] == "circle"
    assert by_id["cn-id"]["type"] == "text"
    assert by_id["cn-divider"]["type"] == "divider"
    assert by_id["cn-divider"]["shape"] == "line"

    for element in payload["elements"]:
        bbox = element["bbox"]
        assert 0 <= bbox["x_min"] < bbox["x_max"] <= 1
        assert 0 <= bbox["y_min"] < bbox["y_max"] <= 1
