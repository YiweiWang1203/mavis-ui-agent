import json
from pathlib import Path

from src.agents.ui_architect import repair_ui_state_with_vision
from src.utils.layout_solver import solve_ui_layout


def test_main_target_preserves_layout_and_uses_only_verified_identity(monkeypatch):
    config = json.loads((Path(__file__).resolve().parents[1] / 'config/main_ui.json').read_text())
    monkeypatch.setenv('UI_FUSION_MODE', config['environment']['UI_FUSION_MODE'])
    obs = dict(x_min=.45, y_min=.45, x_max=.55, y_max=.55)
    vision = {'elements': [{'id': v, 'bbox': obs} for v in ['a','b','c']]}
    ref = lambda v: [{'source': 'vision', 'id': v}]
    def obj(i, box, **fields):
        return dict(id=i, type='button', spatial_info={'bbox': box}, **fields)
    data = {'page_meta': {'viewport': {'width': 400, 'height': 800}}, 'elements': [
        obj('a', [0,0,400,100]),
        obj('child', [10,10,50,40], parent_id='a', source_refs=ref('b')),
        obj('conflict', [100,10,150,40], source_refs=ref('a')),
        obj('c', [20,20,20,30]),
        obj('unresolved', None, source_refs=ref('missing'))]}
    fixed = repair_ui_state_with_vision(data, vision)
    rows = {e['id']: e for e in fixed['elements']}
    assert list(rows) == ['a','child','conflict','c','unresolved']
    assert rows['child']['source_refs'][0] == ref('b')[0]
    assert rows['child']['spatial_info']['evidence_bbox'] == obs
    assert rows['child']['spatial_info']['bbox'] == [10,10,50,40]
    assert rows['conflict']['source_refs'] == [{'source':'architect','id':'conflict'}]
    assert rows['conflict']['source_refs_observed'] == ref('a')
    assert rows['unresolved']['source_refs_observed'] == ref('missing')
    assert rows['c']['spatial_info']['source'] == 'projected_vision_fallback'
    assert rows['unresolved']['spatial_info']['source'] == 'unresolved_target_bbox'
    fixed['elements'].pop()
    compiled = solve_ui_layout(fixed, layout_mode='preserve_target', coordinate_space='target_px_xyxy')
    assert compiled['elements'][1]['parent_id'] == 'a'
    assert compiled['elements'][1]['spatial_info']['bbox'] == [10,10,50,40]
