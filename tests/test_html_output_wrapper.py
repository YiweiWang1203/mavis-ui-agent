import hashlib
import json
from types import SimpleNamespace
import pytest
from src.utils.html_output_wrapper import parse_html_output, HtmlOutputError

HTML='<html><head><title>SYNTHETIC</title></head><body>离线 fixture</body></html>'

@pytest.mark.parametrize('raw,expected',[
 (HTML,HTML),(' \n'+HTML+'\n ',HTML),
 ('说明\n```html\n'+HTML+'\n```\nImplementation notes',HTML+'\n'),
 ('说明\r\n~~~HTML\r\n'+HTML+'\r\n~~~\r\n说明',HTML+'\r\n'),
 ('````html\n'+HTML+'\n````\nNotes',HTML+'\n'),
 ('<html><body><script>const x="```html";</script></body></html>', '<html><body><script>const x="```html";</script></body></html>')])
def test_original_substring_unicode_bytes(raw,expected):
 parsed=parse_html_output(raw);r=parsed['record'];a,b=r['character_range'];c,d=r['utf8_byte_range']
 assert parsed['code']==expected==raw[a:b]
 assert raw.encode('utf-8')[c:d]==expected.encode('utf-8')
 assert r['selected_code_sha256']==hashlib.sha256(expected.encode('utf-8')).hexdigest()
 assert r['raw_content_sha256']==hashlib.sha256(raw.encode('utf-8')).hexdigest()

@pytest.mark.parametrize('raw',[
 '', 'words only', '<html><body>incomplete',HTML+HTML,
 '```html\n'+HTML+'\n```\n```html\n'+HTML+'\n```',
 '```html\n'+HTML, '```python\n'+HTML+'\n```',
 '```html\n'+HTML+'\n~~~', '```html\n'+HTML+'\n```\n<div>other</div>',
 '```html\n'+HTML+'\n```\n```js\nx\n```',
 '<html><body>x</body></html> trailing words',
 '```html\n<html><body>x</body></html> trailing\n```',
 'prefix ` ``` `\n```html\n'+HTML+'\n```'])
def test_invalid_or_ambiguous_is_not_repaired(raw):
 with pytest.raises(HtmlOutputError):parse_html_output(raw)

@pytest.mark.parametrize('reason',['length',None,'tool_calls','timeout'])
def test_non_stop_never_accepted(reason):
 with pytest.raises(HtmlOutputError,match='NON_STOP'):parse_html_output(HTML,finish_reason=reason)


def test_actual_coder_and_export_share_parser(tmp_path,monkeypatch):
 from src.agents import coder
 from src.utils.pipeline_trace import PipelineTrace
 import importlib.util
 from pathlib import Path
 raw='说明\n```html\n'+HTML+'\n```\nKey Implementation Notes\nUnchanged description'
 requests=[]
 def create(**kwargs):
  requests.append(kwargs)
  return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw),finish_reason='stop')])
 monkeypatch.setenv('UI_REGION_TREE_MODE','off');monkeypatch.setenv('UI_RENDERER_MODE','llm')
 monkeypatch.setenv('UI_INPUT_CONTRACT_MODE','off');monkeypatch.setenv('UI_CODER_CONTRACT_MODE','baseline')
 monkeypatch.setattr(coder,'_get_openai_client',lambda:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
 monkeypatch.setattr(coder,'save_html_asset',lambda code:None)
 with PipelineTrace(tmp_path/'trace'):
  returned=coder.generate_frontend_code({'elements':[]})
 path=Path(__file__).resolve().parents[1]/'scripts/region_tree_paired_runner.py'
 spec=importlib.util.spec_from_file_location('shared_export_wrapper',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 (tmp_path/'coder_response.json').write_text(json.dumps({'content':raw,'finish_reason':'stop'}),encoding='utf-8')
 record=module.export_coder_html(tmp_path,returned['code'])
 assert len(requests)==1 and returned['code']==HTML+'\n'
 assert (tmp_path/'original_coder.html').read_bytes()==returned['code'].encode('utf-8')
 trace=json.loads(next((tmp_path/'trace').glob('*coder_output_wrapper.json')).read_text(encoding='utf-8'))
 assert trace['record']==record['output_wrapper']==parse_html_output(raw)['record']
