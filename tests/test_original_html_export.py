import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from src.agents.coder import strip_markdown_code_fence


def module():
    path=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py'
    spec=importlib.util.spec_from_file_location('html_export_test',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def save_response(folder,raw,finish='stop'):
    (folder/'coder_response.json').write_text(json.dumps({'content':raw,'finish_reason':finish},ensure_ascii=False),encoding='utf-8')


@pytest.mark.parametrize('fenced',[True,False])
def test_exact_production_extraction_and_separate_hashes(tmp_path,fenced):
    html='<!DOCTYPE html>\n<html><head><title>工程合成</title></head><body>  synthetic  </body></html>'
    raw='  ```html\n'+html+'\n```  ' if fenced else html
    save_response(tmp_path,raw);response_before=(tmp_path/'coder_response.json').read_bytes()
    record=module().export_coder_html(tmp_path,strip_markdown_code_fence(raw))
    expected=html+'\n' if fenced else html
    assert (tmp_path/'original_coder.html').read_bytes()==expected.encode('utf-8')
    assert (tmp_path/'coder_response.json').read_bytes()==response_before
    assert record['html_sha256']==hashlib.sha256(expected.encode('utf-8')).hexdigest()
    assert record['raw_content_utf8_sha256']==hashlib.sha256(raw.encode('utf-8')).hexdigest()
    assert record['browser_acceptance']=='NOT_EXECUTED'


@pytest.mark.parametrize('raw,finish,rendered',[
    ('<html><body>cut','length','<html><body>cut'),
    ('','stop',''),
    ('SYNTHETIC_NO_CODE','stop','SYNTHETIC_NO_CODE'),
    ('<html><body>cut','stop','<html><body>cut'),
    ('<html><body>ok</body></html>','stop','<html><body>REPAIRED</body></html>'),
])
def test_failure_never_exports_display_page(tmp_path,raw,finish,rendered):
    save_response(tmp_path,raw,finish)
    with pytest.raises(ValueError):module().export_coder_html(tmp_path,rendered)
    assert not list(tmp_path.glob('*.html')) and not (tmp_path/'html_export.json').exists()


def test_response_parse_failure_never_exports(tmp_path):
    (tmp_path/'coder_response.json').write_text('INVALID_JSON',encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):module().export_coder_html(tmp_path,'<html><body>x</body></html>')
    assert not list(tmp_path.glob('*.html'))
