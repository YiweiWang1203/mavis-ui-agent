"""Offline actual shared-node/request checks; no provider or video execution."""
import ast
import json
import logging
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace, ModuleType

from src.service.planner_input import build_planner_intent

ROOT = Path(__file__).resolve().parents[1]


def extract(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    fn.returns = None
    for arg in fn.args.args + fn.args.kwonlyargs:
        arg.annotation = None
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / path), 'exec'), namespace)
    return namespace[name]


def test_stable_sources_survive_vision_message_replacement():
    state = {'original_user_request': 'original request', 'asr_transcript': 'fresh speech',
             'preprocess_platform_hint': {'platform': 'desktop', 'target_size': [1366, 768]},
             'messages': [{'role': 'human', 'name': 'vision', 'content': 'vision success'}]}
    intent = build_planner_intent(state)
    assert 'original request' in intent and 'fresh speech' in intent
    assert '1366' in intent and 'vision success' not in intent


def test_legacy_human_fallback_never_takes_tool_status():
    state = {'messages': [SimpleNamespace(type='human', name='vision', content='status'),
                          SimpleNamespace(type='human', name=None, content='legacy user')]}
    assert 'legacy user' in build_planner_intent(state)
    assert 'status' not in build_planner_intent(state)
    assert 'status' not in build_planner_intent({'messages': state['messages'][:1]})


def test_blank_sources_fall_back_without_rewriting_nonblank_text():
    state = {'original_user_request': '  ', 'asr_transcript': '\n ',
             'voice_intent': '  actual meeting speech  ',
             'messages': [{'role': 'human', 'name': 'vision', 'content': 'status-only'},
                          {'role': 'user', 'content': '  original human text  '}]}
    intent = build_planner_intent(state)
    assert '[Original User Request]\n  original human text  \n' in intent
    assert '[Fresh ASR Transcript]\n  actual meeting speech  \n' in intent
    assert 'status-only' not in intent
    state.update(original_user_request='  stable request  ', asr_transcript='  stable ASR  ')
    intent = build_planner_intent(state)
    assert '[Original User Request]\n  stable request  \n' in intent
    assert '[Fresh ASR Transcript]\n  stable ASR  \n' in intent
    assert 'actual meeting speech' not in intent


def test_actual_node_to_actual_architect_request(monkeypatch):
    # AST executes unchanged shared functions; only imports/client/finalizer are fake.
    # This checks request construction, not the LangGraph runtime or layout quality.
    for key in ('UI_STRUCTURE_MODE', 'UI_SEMANTIC_TYPE_MODE', 'UI_RELATION_SPECIALIST_MODE', 'UI_INPUT_SEMANTIC_AUDIT_MODE'):
        monkeypatch.delenv(key, raising=False)
    module = ModuleType('src.utils.architect_image_context')
    module.architect_request_content = lambda content, *args, **kwargs: content
    monkeypatch.setitem(sys.modules, module.__name__, module)
    calls = []
    response_state = {'page_meta': {'viewport': {'width': 1366, 'height': 768}}, 'elements': []}
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_state)))])
    namespace = {'os': os, 'json': json, 'trace_event': lambda *a, **kw: None,
        'read_ui_architect_prompt': lambda: (ROOT / 'src/prompts/ui_architect.md').read_text(encoding='utf-8'),
        'infer_locale_from_text': lambda text: 'zh-CN',
        '_get_openai_client': lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        'finalize_ui_state': lambda value, *a: value,
        'TargetGeometryRejected': type('TargetGeometryRejected', (Exception,), {})}
    generate = extract('src/agents/ui_architect.py', 'generate_ui_state', namespace)
    env = {'logger': logging.getLogger('offline'), 're': re, 'generate_ui_state': generate,
           'json': json, 'RESPONSE_FORMAT': '{} {}',
           'HumanMessage': lambda **kw: SimpleNamespace(**kw),
           'Command': lambda **kw: SimpleNamespace(**kw)}
    node = extract('src/graph/nodes.py', 'ui_architect_node', env)
    result = node({'messages': [SimpleNamespace(content='vision success', type='human', name='vision')],
        'original_user_request': 'desktop request', 'asr_transcript': 'fresh full transcript',
        'preprocess_platform_hint': {'platform': 'desktop', 'target_size': [1366, 768]},
        'vision_elements': {'canvas': {'width': 1366, 'height': 768}, 'elements': []}, 'voice_intent': None})
    assert len(calls) == 1
    request = calls[0]['messages'][1]['content']
    assert 'desktop request' in request and 'fresh full transcript' in request
    assert '1366' in request and 'vision success' not in request
    assert result.update['ui_state_json'] == response_state
    prompt = calls[0]['messages'][0]['content']
    assert '假设一个宽 375' not in prompt and 'target_size' in prompt


def test_adapter_persists_platform_hint():
    source = (ROOT / 'src/service/input_adapter.py').read_text(encoding='utf-8')
    assert '"preprocess_platform_hint": (video_result or {}).get("platform_hint")' in source


def test_image_path_keeps_required_vision_guard_without_message_marker():
    env = {'logger': logging.getLogger('offline'), 're': re,
           'HumanMessage': lambda **kw: SimpleNamespace(**kw),
           'Command': lambda **kw: SimpleNamespace(**kw)}
    node = extract('src/graph/nodes.py', 'ui_architect_node', env)
    result = node({'messages': [], 'original_user_request': 'request',
                   'recognition_image_path': 'real_image.jpg', 'vision_elements': None})
    assert result.update['ui_state_json']['error']
