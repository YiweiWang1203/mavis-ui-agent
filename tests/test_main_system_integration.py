import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.service.main_model_runtime import MainModelRuntime, MODEL, main_client
from src.service.main_model_runtime import note_vision_repair


def test_original_condition_repair_is_one_extra_slot(tmp_path):
    calls = []
    def dispatch(request, **kwargs):
        calls.append(request)
        return {'ok': True, 'response': {'choices': [{'finish_reason': 'stop',
            'message': {'content': 'test'}}]}}
    with MainModelRuntime(tmp_path / 'repair', dispatch) as runtime:
        runtime.create('vision', model=MODEL)
        with pytest.raises(RuntimeError): runtime.create('vision', model=MODEL)
        note_vision_repair({'previous_validation': {'valid': False}})
        runtime.create('vision', model=MODEL)
        runtime.create('architect', model=MODEL)
        runtime.create('coder', model=MODEL)
        with pytest.raises(RuntimeError): runtime.create('vision', model=MODEL)
        assert runtime.used == ['vision_initial', 'vision_repair', 'architect', 'coder']
    assert len(calls) == 4


def test_html_document_extraction_excludes_tail():
    coder = load_coder()
    result = coder.strip_markdown_code_fence('说明\n```html\n<!DOCTYPE html><html><body>保留</body></html>\n```\n说明尾文')
    assert result == '<!DOCTYPE html><html><body>保留</body></html>'


@pytest.mark.parametrize('inside', ['<script>const closing="</html>";</script>',
    '<!-- a literal </html> in a comment -->', '<script>const template=`</html>`;</script>'])
def test_html_tag_literal_does_not_truncate_page(inside):
    coder = load_coder()
    document = '<!DOCTYPE html><html><body>' + inside + '<button id="last">must remain</button></body></html>'
    assert coder.strip_markdown_code_fence(document) == document
    assert coder.strip_markdown_code_fence('```html\n' + document + '\n```\n解释') == document


def test_multiple_or_unclosed_fences_not_guessed():
    coder = load_coder()
    with pytest.raises(ValueError):
        coder.strip_markdown_code_fence('```html\n<html></html>')
    with pytest.raises(ValueError):
        coder.strip_markdown_code_fence('```html\n<html></html>\n```\n```html\n<html></html>\n```')
    assert not coder.is_complete_html_document('<html><script>const x="</html>";</script>')
    assert coder.is_complete_html_document('<html><script>const x="</html>";</script></html>')


def test_three_real_stage_slots_and_failed_slot_consumed(tmp_path):
    calls = []
    def dispatch(request, **kwargs):
        calls.append(request)
        return {'ok': True, 'response': {'choices': [{'finish_reason': 'stop',
            'message': {'content': 'test'}}], 'usage': {'total_tokens': 7}}}
    with MainModelRuntime(tmp_path / 'requests', dispatch) as runtime:
        for stage in ('vision', 'architect', 'coder'):
            main_client(stage).chat.completions.create(model=MODEL, messages=[])
        with pytest.raises(RuntimeError):
            main_client('coder').chat.completions.create(model=MODEL, messages=[])
        assert runtime.used == ['vision_initial', 'architect', 'coder']
    assert len(calls) == 3
    assert all(c['max_tokens'] == 8192 and c['timeout'] == 600 for c in calls)
    assert main_client('coder') is None
    def fail(*args, **kwargs): raise TimeoutError()
    with MainModelRuntime(tmp_path / 'failed', fail) as runtime:
        with pytest.raises(TimeoutError): runtime.create('vision', model=MODEL)
        with pytest.raises(RuntimeError): runtime.create('vision', model=MODEL)
    terminal = json.loads((tmp_path / 'failed/vision_initial_terminal.json').read_text())
    assert terminal['status'] == 'FAILED_NO_RETRY'


def test_truncated_response_is_not_html_success(tmp_path):
    def dispatch(*args, **kwargs):
        return {'ok': True, 'response': {'choices': [{'finish_reason': 'length',
            'message': {'content': '<html>partial'}}]}}
    with MainModelRuntime(tmp_path / 'requests', dispatch) as runtime:
        with pytest.raises(RuntimeError, match='INCOMPLETE'):
            runtime.create('vision', model=MODEL)


def load_coder():
    spec = importlib.util.spec_from_file_location('main_test_coder', ROOT / 'src/agents/coder.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_coder_receives_original_sources_and_persists(tmp_path, monkeypatch):
    coder = load_coder()
    monkeypatch.setenv('UI_RENDERER_MODE', 'llm')
    monkeypatch.setenv('UI_CODER_CONTRACT_MODE', 'main_system_v1')
    monkeypatch.setenv('MAVIS_MAIN_RUN_ID', 'source_trace')
    monkeypatch.setattr(coder, 'HTML_OUTPUT_DIR', tmp_path)
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='```html\n<!DOCTYPE html><html><body><input id="editor"></body></html>\n```'), finish_reason='stop')])
    monkeypatch.setattr(coder, '_get_openai_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    state = {'page_meta': {'viewport': {'width': 1000, 'height': 700}}, 'elements': []}
    result = coder.generate_frontend_code(state, original_user_request='source-original', asr_transcript='source-speech')
    assert isinstance(result, dict)
    assert Path(result['file_path']).parent == tmp_path / 'source_trace'
    assert Path(result['file_path']).read_text(encoding='utf-8') == result['code']
    request = captured[0]['messages'][1]['content']
    assert '[Original User Request]\nsource-original' in request
    assert '[Fresh ASR Transcript]\nsource-speech' in request
    assert 'Display-only' in captured[0]['messages'][0]['content']


def test_shared_code_node_passes_sources_without_manual_groups(monkeypatch):
    pytest.importorskip('langgraph')
    # Execute the actual node function with its original surrounding runtime dependencies stubbed.
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    tree = ast.parse((ROOT / 'src/graph/nodes.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'code_node')
    node.decorator_list = []
    node.returns = None
    for arg in node.args.args: arg.annotation = None
    import logging, os
    env = dict(logger=logging.getLogger('test'), HumanMessage=HumanMessage, Command=Command,
               RESPONSE_FORMAT='{} {}', os=os)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<real-code-node>', 'exec'), env)
    import src.agents.coder as coder
    received = []
    monkeypatch.setattr(coder, 'generate_frontend_code', lambda state, **kwargs: received.append(kwargs) or {'code': '<html></html>', 'file_path': 'test'})
    monkeypatch.setenv('UI_CODER_CONTRACT_MODE', 'main_system_v1')
    result = env['code_node']({'ui_state_json': {'elements': [{'id': 'a'}]},
        'original_user_request': 'request', 'asr_transcript': 'fresh-speech'})
    assert received[0]['asr_transcript'] == 'fresh-speech'
    assert received[0]['original_user_request'] == 'request'
    assert result.update['final_code'] == '<html></html>'


def test_platform_minimal_patch_preserves_old_fallbacks():
    import re
    tree = ast.parse((ROOT / 'src/preprocess/platform_inferencer.py').read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_infer_from_text')
    fn.decorator_list = []
    fn.returns = None
    for arg in fn.args.args: arg.annotation = None
    env = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<platform-rule>', 'exec'), env)
    infer = lambda s: env['_infer_from_text'](None, s)
    assert infer('我需要一个电脑页面大小的聊天对话页面') == 'desktop'
    assert infer('电脑页面不错') == 'desktop'
    assert infer('电脑页面不要手机页面') == 'desktop'
    assert infer('not mobile desktop') == 'desktop'
    assert infer('在电脑上传图片，做手机页面') == 'mobile'
    assert infer('后台管理系统') == 'desktop'


def test_main_graph_reaches_review_and_keeps_context(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    import src.graph as graph_package
    from src.service.main_ui_workflow import build_main_ui_graph
    seen = []
    html = tmp_path / 'generated.html'
    html.write_text('<html></html>')
    def node(name):
        def invoke(state):
            assert main_client(name) is not None
            seen.append(name)
            if name == 'vision': update = {'vision_status': {'valid': True}}
            elif name == 'architect': update = {'ui_state_json': {'elements': [{'id': 'a'}]}}
            else: update = {'final_code': '<html></html>', 'final_code_path': str(html)}
            return SimpleNamespace(update=update)
        return invoke
    monkeypatch.setattr(graph_package, 'nodes', SimpleNamespace(vision_node=node('vision'), ui_architect_node=node('architect'), code_node=node('coder')), raising=False)
    folder = tmp_path / 'nodes'; folder.mkdir()
    with MainModelRuntime(tmp_path / 'requests'):
        result = build_main_ui_graph(folder).invoke({'original_user_request': 'keep'})
    assert seen == ['vision', 'architect', 'coder']
    assert result['review']['html_persisted']
    assert result['original_user_request'] == 'keep'


def test_graph_failure_identifies_node_and_redacts_secret(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    import src.graph as graph_package
    from src.service.main_ui_workflow import build_main_ui_graph
    monkeypatch.setenv('TEST_API_KEY', 'should-not-appear')
    def fail(state): raise ValueError('failure: should-not-appear')
    def forbidden(state): raise AssertionError('downstream must not run')
    monkeypatch.setattr(graph_package, 'nodes', SimpleNamespace(vision_node=fail,
        ui_architect_node=forbidden, code_node=forbidden), raising=False)
    result = build_main_ui_graph(tmp_path).invoke({})
    assert result['failed_node'] == 'vision'
    text = (tmp_path / 'vision_error.json').read_text(encoding='utf-8')
    assert 'should-not-appear' not in text and '[REDACTED]' in text and 'ValueError' in text
    assert not result['review']['html_persisted']
