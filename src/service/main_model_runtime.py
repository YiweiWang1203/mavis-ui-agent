"""Bounded provider boundary used by the main UI nodes, not an experiment runner."""
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
import time

from src.utils.single_attempt_transport import isolated_sdk_call, write_new

ACTIVE = ContextVar('main_model_runtime', default=None)
MODEL = 'Qwen/Qwen3-VL-32B-Instruct'


def main_client(stage):
    runtime = ACTIVE.get()
    return runtime.client(stage) if runtime else None


def note_vision_repair(feedback):
    runtime = ACTIVE.get()
    if runtime:
        if runtime.failed or runtime.used != ['vision_initial'] or runtime.repair_reason is not None:
            raise RuntimeError('UNAUTHORIZED_VISION_REPAIR')
        runtime.repair_reason = feedback
        write_new(runtime.folder / 'vision_repair_trigger.json', feedback)


class MainModelRuntime:
    def __init__(self, output, dispatch=None):
        self.folder = Path(output)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.dispatch = dispatch or isolated_sdk_call
        self.used = []
        self.repair_reason = None
        self.failed = False

    def __enter__(self):
        self.token = ACTIVE.set(self)
        return self

    def __exit__(self, *args):
        ACTIVE.reset(self.token)

    def client(self, stage):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: self.create(stage, **kwargs))))

    def create(self, stage, **kwargs):
        if self.failed:
            raise RuntimeError('PRIOR_REQUEST_FAILED_NO_RETRY')
        if stage == 'vision':
            slot = 'vision_initial' if not self.used else 'vision_repair'
        else:
            slot = stage
        if stage not in ('vision', 'architect', 'coder') or slot in self.used or len(self.used) >= 4:
            raise RuntimeError('MAIN_STAGE_ALREADY_CONSUMED_OR_UNAUTHORIZED')
        expected = ('vision' if not self.used else
                    'vision' if self.used == ['vision_initial'] and self.repair_reason is not None else
                    'coder' if self.used[-1] == 'architect' else 'architect')
        if stage != expected:
            raise RuntimeError('MAIN_STAGE_ORDER_VIOLATION')
        if kwargs.get('model') != MODEL:
            raise RuntimeError('MAIN_MODEL_CONFIGURATION_MISMATCH')
        self.used.append(slot)  # Claim before dispatch; failure consumes the slot.
        request = {**kwargs, 'max_tokens': 8192, 'timeout': 600}
        write_new(self.folder / (slot + '_request.json'), request)
        terminal = {'stage': stage, 'slot': slot, 'usage': None, 'currency_cost': None,
                    'automatic_retries': 0, 'dispatch_attempts': 1}
        start = time.monotonic()
        try:
            diagnostics = self.folder / (slot + '_stages')
            diagnostics.mkdir()
            packet = self.dispatch(request, deadline=600, diagnostics_directory=diagnostics)
            write_new(self.folder / (slot + '_response.json'), packet)
            if not packet.get('ok'):
                raise RuntimeError('PROVIDER_' + str(packet.get('error_type', 'UNKNOWN')))
            response = packet['response']
            terminal.update(usage=response.get('usage'), provider_response_id=response.get('id'))
            choices = response.get('choices', [])
            if len(choices) != 1 or choices[0].get('finish_reason') != 'stop':
                raise RuntimeError('INCOMPLETE_MODEL_RESPONSE')
            text = choices[0].get('message', {}).get('content')
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError('EMPTY_MODEL_RESPONSE')
            terminal['status'] = 'RETURNED_NOT_USER_ACCEPTANCE'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text),
                finish_reason='stop')], usage=response.get('usage'))
        except BaseException as error:
            self.failed = True
            terminal.update(status='FAILED_NO_RETRY', error_type=type(error).__name__)
            raise
        finally:
            terminal['elapsed_seconds'] = time.monotonic() - start
            write_new(self.folder / (slot + '_terminal.json'), terminal)
