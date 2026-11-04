"""Production video entry using the shared UI nodes and bounded provider runtime."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import re

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    from src.utils.pipeline_trace import plain
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(plain(value), stream, ensure_ascii=False, indent=2)


def safe_diagnostic(error):
    text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    for key, value in os.environ.items():
        if value and len(value) >= 4 and any(word in key.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)bearer\s+[^\s\"\']+', 'Bearer [REDACTED]', text)
    return {'error_type': type(error).__name__, 'sanitized_traceback': text}


def build_main_ui_graph(output):
    from langgraph.graph import START, END, StateGraph
    from src.graph import nodes
    from src.utils.pipeline_trace import state_summary
    output = Path(output)
    def wrap(name, fn):
        def invoke(state):
            state = dict(state)
            save(output / (name + '_input.json'), state)
            started = time.monotonic()
            try:
                result = fn(state)
                state.update(result.update)
                reason = None
                if name == 'vision' and not (state.get('vision_status') or {}).get('valid'):
                    reason = {'vision_status': state.get('vision_status')}
                elif name == 'architect' and (not isinstance(state.get('ui_state_json'), dict)
                        or state['ui_state_json'].get('error') or not state['ui_state_json'].get('elements')):
                    reason = {'ui_state_error': (state.get('ui_state_json') or {}).get('error', 'EMPTY_UI_STATE')}
                elif name == 'coder' and not state.get('final_code'):
                    reason = {'coder_error': 'NO_FINAL_CODE_RETURNED'}
                if reason:
                    state['failed_node'] = name
                    state['node_failure_reason'] = reason
            except Exception as error:
                state['failed_node'] = name
                state['node_error_type'] = type(error).__name__
                save(output / (name + '_error.json'), safe_diagnostic(error))
            state['node_history'] = state.get('node_history', []) + [
                {'node': name, 'seconds': time.monotonic() - started,
                 'status': 'FAILED' if state.get('failed_node') else 'RETURNED_NOT_ACCEPTANCE'}]
            save(output / (name + '_output.json'), state)
            return state
        return invoke
    def after_vision(state):
        return 'architect' if not state.get('failed_node') and state.get('vision_status', {}).get('valid') else 'review'
    def after_architect(state):
        ui = state.get('ui_state_json')
        return 'coder' if not state.get('failed_node') and isinstance(ui, dict) and ui.get('elements') and not ui.get('error') else 'review'
    def review(state):
        state = dict(state)
        path = state.get('final_code_path')
        code = state.get('final_code')
        persisted = bool(code and isinstance(path, str) and Path(path).is_file()
                         and Path(path).read_text(encoding='utf-8') == code)
        state['review'] = {'reviewer': 'local_artifact_and_structure_audit',
            'semantic_model_review': (state.get('ui_state_json') or {}).get('page_meta', {}).get('semantic_review'),
            'plan_selection': (state.get('ui_state_json') or {}).get('page_meta', {}).get('plan_selection'),
            'semantic_model_passed': (state.get('ui_state_json') or {}).get('page_meta', {}).get('semantic_review_passed'),
            'semantic_contract_issues': (state.get('ui_state_json') or {}).get('page_meta', {}).get('semantic_contract_issues'),
            'semantic_contract_passed': (state.get('ui_state_json') or {}).get('page_meta', {}).get('semantic_contract_passed'),
            'html_persisted': persisted,
            'html_validation': state.get('html_validation'),
            'html_contract_passed': (state.get('html_validation') or {}).get('passed'),
            'raw_candidate_path': state.get('raw_candidate_path'),
            'structure': state_summary(state.get('ui_state_json')),
            'browser_behavior': 'NOT_EXECUTED', 'semantic_requirement_coverage': 'UNKNOWN',
            'limitations': 'Artifact persistence and structure checks do not imply semantic or browser acceptance. Bounded planning repair and plan selection are recorded in request evidence and review.'}
        save(output / 'review.json', state['review'])
        return state
    graph = StateGraph(dict)
    graph.add_node('vision', wrap('vision', nodes.vision_node))
    graph.add_node('architect', wrap('architect', nodes.ui_architect_node))
    graph.add_node('coder', wrap('coder', nodes.code_node))
    graph.add_node('review', review)
    graph.add_edge(START, 'vision')
    graph.add_conditional_edges('vision', after_vision, ['architect', 'review'])
    graph.add_conditional_edges('architect', after_architect, ['coder', 'review'])
    graph.add_edge('coder', 'review')
    graph.add_edge('review', END)
    return graph.compile()


def run_main_video(*, video_path, user_prompt, output_dir, run_id,
                   rotate_degrees=180, image_path=None, preferred_locale='auto'):
    config_path = ROOT / 'config/main_ui.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    profile = config.get("runtime_profile", "baseline4")
    request_limit = {"baseline4": 4, "semantic7": 7}.get(profile)
    if request_limit is None:
        raise ValueError("UNKNOWN_RUNTIME_PROFILE")
    if (profile == "semantic7") != (config['environment'].get('UI_REGION_REVIEW_MODE') == "semantic7"):
        raise ValueError("REVIEW_RUNTIME_PROFILE_MISMATCH")
    if (config.get('max_physical_requests_per_case'), config.get('max_output_tokens'),
        config.get('timeout_seconds'), config.get('automatic_retries'), config.get('enable_asr')) != (request_limit, 8192, 600, 0, True):
        raise ValueError('UNSUPPORTED_MAIN_BUDGET_CONFIG')
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    before = {key: os.environ.get(key) for key in config['environment']}
    old_run = os.environ.get('MAVIS_MAIN_RUN_ID')
    old_asr = os.environ.get('MAVIS_ASR_MODEL_CONFIG')
    for key, value in config['environment'].items():
        os.environ[key] = value
    os.environ['MAVIS_MAIN_RUN_ID'] = run_id
    os.environ['MAVIS_ASR_MODEL_CONFIG'] = str(ROOT / 'config/asr_model_identity.json')
    terminal = {'status': 'STARTED', 'run_id': run_id, 'utc': datetime.now(timezone.utc).isoformat(),
        'host': platform.node(), 'interpreter': sys.executable, 'python': platform.python_version(),
        'project_root': str(ROOT), 'output_dir': str(output), 'input_video': str(Path(video_path).resolve()),
        'input_video_sha256': sha(video_path), 'prompt_sha256': hashlib.sha256(user_prompt.encode()).hexdigest(),
        'config_sha256': sha(config_path), 'config': config, 'model_calls': [],
        'html_generated': False, 'currency_cost': None, 'browser_acceptance': 'NOT_EXECUTED'}
    runtime = None
    try:
        terminal['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        terminal['tracked_dirty'] = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '--', 'src', 'config', 'scripts/run_video_ui_workflow.py'], cwd=ROOT, text=True).splitlines()
        if terminal['tracked_dirty']:
            raise RuntimeError('MAIN_TRACKED_SOURCE_DIRTY')
        save(output / 'run_identity.json', terminal)
        from src.service.main_model_runtime import MainModelRuntime
        from src.utils.pipeline_trace import PipelineTrace
        from src.service.input_adapter import prepare_workflow_input
        from langchain_core.messages import HumanMessage
        with PipelineTrace(output / 'trace', terminal), MainModelRuntime(output / 'requests', profile=profile) as runtime:
            prepared = prepare_workflow_input(text=user_prompt, video_path=video_path, image_path=image_path,
                preprocess_output_dir=str(output / 'preprocess'), rotate_degrees=rotate_degrees,
                enable_asr=True, vision_image_mode='recognition')
            save(output / 'prepared_input.json', prepared)
            state = prepared['state']
            if preferred_locale != 'auto':
                state['preferred_locale'] = preferred_locale
            state['messages'] = [HumanMessage(content=m['content']) for m in state['messages']]
            nodes = output / 'nodes'
            nodes.mkdir()
            final = build_main_ui_graph(nodes).invoke(state)
            save(output / 'final_state.json', final)
            terminal['model_calls'] = list(runtime.used)
            terminal['node_history'] = final.get('node_history', [])
            terminal['review'] = final.get('review')
            terminal['html_generated'] = bool(final.get('review', {}).get('html_persisted'))
            if terminal['html_generated']:
                path = Path(final['final_code_path']).resolve()
                terminal.update(status='HTML_GENERATED_PENDING_BROWSER_ACCEPTANCE', html_path=str(path), html_sha256=sha(path))
                terminal['html_contract_passed'] = final.get('review', {}).get('html_contract_passed')
                if terminal['html_contract_passed'] is False:
                    terminal['status'] = 'HTML_CONTRACT_FAILED_PENDING_BROWSER_ACCEPTANCE'
                raw_path = final.get('raw_candidate_path')
                if raw_path and Path(raw_path).is_file():
                    terminal['raw_html_path'] = str(Path(raw_path).resolve())
                    terminal['raw_html_sha256'] = sha(raw_path)
                save(path.parent / 'source_manifest.json', {k: terminal[k] for k in (
                    'run_id', 'commit', 'input_video', 'input_video_sha256', 'config_sha256', 'html_path', 'html_sha256',
                    'html_contract_passed', 'raw_html_path', 'raw_html_sha256') if k in terminal})
            else:
                terminal.update(status='NO_HTML', failed_node=final.get('failed_node'),
                    node_error_type=final.get('node_error_type'), vision_status=final.get('vision_status'),
                    ui_error=(final.get('ui_state_json') or {}).get('error'))
    except BaseException as error:
        terminal.update(status='FAILED_NO_RETRY', error_type=type(error).__name__)
        save(output / 'failure_diagnostic.json', safe_diagnostic(error))
    finally:
        if runtime is not None:
            terminal['model_calls'] = list(runtime.used)
        terminal['request_records'] = [str(path.relative_to(output)) for path in sorted((output / 'requests').glob('*_terminal.json'))]
        for key, value in before.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        for key, value in [('MAVIS_MAIN_RUN_ID', old_run), ('MAVIS_ASR_MODEL_CONFIG', old_asr)]:
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        save(output / 'terminal.json', terminal)
        save(output / 'artifact_sha256.json', {str(path.relative_to(output)): sha(path)
             for path in output.rglob('*') if path.is_file()})
    return terminal
